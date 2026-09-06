"""平台刷写策略（**宿主机执行期**）。

每个平台一个策略类，封装该平台的设备检测、进入下载模式、写分区的工具链
调用（rkdeveloptool / upgrade_tool / qdl / xfel …）。这些命令全部在开发者
的机器上执行，不在 Docker 内、不产出任何构建产物，因此本模块**不进**构建
逻辑指纹 —— 改刷写工具的调用方式不该让 kernel 重新编译。
"""

import hashlib
import json
import os
import re
import sys
import shutil
import subprocess
import tempfile
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

from builder.flash.plan import (
    AllwinnerA733FlashPlan,
    AmlogicFlashPlan,
    FlashPlan,
    QualcommFlashPlan,
    RockchipFlashPlan,
)
from builder.flash.console import (
    _c, _err, _header, _info, _ok, _step, _tty, _warn,
)
from builder.flash.model import (
    DeviceInfo,
    FlashConfig,
    FlashError,
    FlashPartition,
    PreFlashConfig,
    _atomic_write_text,
)
from builder.flash.spi import (
    SPI_IDBLOADER_OFFSET,
    SPI_IMG_ALIGN,
    SPI_NOR_SIZE,
    SPI_UBOOT_OFFSET,
    build_spi_image,
)
from builder.partition.rockchip import (
    parse_parameter_file,
    parse_parameter_text,
    validate_parameter_capacity,
)
from builder.partition.size import parse_size
from builder.paths import PROJECT_ROOT
from builder.term import Role, supports_color



# ---------------------------------------------------------------------------
# 平台刷写策略
# ---------------------------------------------------------------------------

class FlashStrategy(FlashPlan, ABC):
    """平台刷写策略基类。"""

    @abstractmethod
    def find_tool(self, project_dir: Path) -> Path:
        """查找平台刷写工具路径，未找到抛 FlashError。"""

    @abstractmethod
    def detect_device(self, tool: Path) -> Optional[DeviceInfo]:
        """检测设备，返回 DeviceInfo 或 None。"""

    @abstractmethod
    def pre_flash(self, tool: Path, target_dir: Path, config: FlashConfig,
                  device: Optional["DeviceInfo"] = None):
        """刷写前准备（如 Rockchip 上传 miniloader）。"""

    def pre_flash_all(self, tool: Path, target_dir: Path, config: FlashConfig,
                      device: Optional["DeviceInfo"] = None):
        """全量刷写前准备；默认复用单分区准备流程。"""
        self.pre_flash(tool, target_dir, config, device)

    @abstractmethod
    def write_partition(self, tool: Path, offset: int, image: Path):
        """写入单个分区。"""

    def write_gpt(self, tool: Path, target_dir: Path, config: "FlashConfig"):
        """在分区写入前刷新 GPT 表。默认 no-op；需要的平台覆盖。

        Rockchip upgrade_tool 的 WL 命令仅按 offset 写 LBA，不会更新 GPT 表；
        分区表变更（如新增 recovery）必须显式刷一次 GPT，否则 kernel 看不到
        新分区，``Waiting for root device PARTLABEL=...`` 会死等。
        """
        return

    def preflight(
        self,
        target_dir: Path,
        config: "FlashConfig",
        partitions: list[FlashPartition],
    ) -> None:
        """执行任何设备写操作前的本地产物校验；默认 no-op。"""
        return

    def write_named_partition(
        self,
        tool: Path,
        part: FlashPartition,
        image: Path,
        config: "FlashConfig",
    ) -> None:
        """按分区模型写入；默认退化为 offset 写。"""
        self.write_partition(tool, int(part.offset, 0), image)

    @abstractmethod
    def reboot(self, tool: Path):
        """重启设备。"""

    def flash_whole_disk(self, tool: Path, target_dir: Path,
                         config: "FlashConfig") -> bool:
        """整盘刷写钩子（如 edl-ng write-sector 整 raw.img）。

        返回 True 表示已处理（FlashExecutor 跳过 per-partition 循环）；
        默认返回 False，走传统的逐分区 write_partition 流程。
        Qualcomm 等"整盘写"平台覆盖此方法即可，零侵入现有平台。
        """
        return False

    def wait_for_device(self, tool: Path, timeout: int = 30) -> DeviceInfo:
        """等待设备就绪，超时抛 FlashError。"""
        _step("等待设备连接...")
        deadline = time.time() + timeout
        # Spinner 字符集
        frames = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
        idx = 0
        while time.time() < deadline:
            info = self.detect_device(tool)
            if info:
                if _tty() and supports_color():
                    sys.stdout.write("\r\033[K")
                _ok(f"已检测到 {info.platform} 设备 ({info.mode} 模式)")
                return info
            remaining = int(deadline - time.time())
            if _tty() and supports_color():
                frame = frames[idx % len(frames)]
                sys.stdout.write(
                    f"\r{_c(Role.ACTIVE, f'  {frame} 等待设备连接... ({remaining}s)')}")
                sys.stdout.flush()
                idx += 1
            time.sleep(1)
        if _tty() and supports_color():
            sys.stdout.write("\r\033[K")
        _err(f"等待设备超时（{timeout}s）")
        raise FlashError(
            f"等待设备超时（{timeout}s）。\n"
            "请确认设备已通过 USB 连接并进入刷写模式。"
        )


class RockchipFlashStrategy(RockchipFlashPlan, FlashStrategy):
    """Rockchip 刷写策略 — 使用 upgrade_tool。"""

    TOOL_NAME = "upgrade_tool"

    def find_tool(self, project_dir: Path) -> Path:
        platform = "macos" if sys.platform == "darwin" else "linux"
        tool = project_dir / "tools" / platform / "upgrade_tool" / "upgrade_tool"
        if not tool.exists():
            raise FlashError(f"未找到 {self.TOOL_NAME}: {tool}")
        return tool

    def detect_device(self, tool: Path) -> Optional[DeviceInfo]:
        try:
            result = subprocess.run(
                [str(tool), "LD"],
                capture_output=True, text=True, timeout=5,
            )
            raw_output = result.stdout + result.stderr
            count_match = re.search(
                r"connected\s*\(\s*(\d+)\s*\)", raw_output, re.I)
            if count_match:
                count = int(count_match.group(1))
            else:
                count = len(re.findall(r"\bDevNo\s*=", raw_output, re.I))
            if count > 1:
                raise FlashError(
                    f"检测到 {count} 台 Rockchip 设备；为防止误刷，请只连接一台")
            output = raw_output.lower()
            if "maskrom" in output:
                return DeviceInfo("rockchip", "maskrom", "Rockchip Maskrom 设备")
            if "loader" in output:
                return DeviceInfo("rockchip", "loader", "Rockchip Loader 设备")
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            pass
        return None

    @staticmethod
    def _identity_corpus(output: str) -> str:
        """把工具输出及其中的十六进制 ASCII 字节合并为可匹配文本。"""
        decoded: list[str] = []
        for match in re.finditer(
            r"(?:(?<![0-9a-fA-F])[0-9a-fA-F]{2}(?:\s+|$)){2,}",
            output,
        ):
            tokens = re.findall(r"[0-9a-fA-F]{2}", match.group(0))
            raw = bytes(int(token, 16) for token in tokens)
            decoded.append("".join(
                chr(value) if 32 <= value < 127 else " " for value in raw
            ))
        return output + "\n" + "\n".join(decoded)

    @staticmethod
    def _read_identity(tool: Path, command: str) -> str:
        result = subprocess.run(
            [str(tool), command], capture_output=True, text=True)
        output = (result.stdout or "") + (result.stderr or "")
        if result.returncode != 0 or not output.strip():
            raise FlashError(
                f"upgrade_tool {command} 设备身份读取失败"
                f"（exit {result.returncode}）:\n{output}")
        return output

    @staticmethod
    def _require_identity_match(
        label: str,
        corpus: str,
        patterns: list[str],
    ) -> None:
        if patterns and not any(
            re.search(pattern, corpus, re.I) for pattern in patterns
        ):
            raise FlashError(
                f"Rockchip {label}身份与 flash-config 不匹配；"
                f"期望任一 {patterns!r}，工具输出:\n{corpus}")

    def _verify_device_identity(
        self,
        tool: Path,
        config: FlashConfig,
    ) -> None:
        """在 UL/DI/WL 前验证 SoC 与存储，RID 用于唯一设备诊断。"""
        identity = config.identity
        chip_patterns = list(identity.chip_patterns)
        if not chip_patterns and config.soc:
            chip_patterns = [re.escape(config.soc)]
        if not chip_patterns and not identity.storage_patterns:
            return

        chip_output = self._read_identity(tool, "RCI")
        flash_output = self._read_identity(tool, "RFI")
        chip_corpus = self._identity_corpus(chip_output)
        try:
            flash_id_output = self._read_identity(tool, "RID")
        except FlashError:
            if identity.require_rid:
                raise
            flash_id_output = ""
        flash_corpus = self._identity_corpus(
            flash_output + "\n" + flash_id_output)
        self._require_identity_match("SoC", chip_corpus, chip_patterns)
        self._require_identity_match(
            "存储", flash_corpus, identity.storage_patterns)
        _ok(f"设备身份已确认（{config.soc or 'Rockchip'} / {config.storage_type}）")

    _UDEV_HINT = (
        "upgrade_tool DB 无法打开 USB（Creating Comm Object failed）——maskrom 的 "
        "BootROM USB 需要 root 权限。\n"
        "  装 udev 规则（推荐，一次性，之后免 sudo）：\n"
        "    echo 'SUBSYSTEM==\"usb\", ATTRS{idVendor}==\"2207\", MODE=\"0666\", "
        "GROUP=\"plugdev\"' | sudo tee /etc/udev/rules.d/99-rockchip.rules\n"
        "    sudo udevadm control --reload-rules && sudo udevadm trigger\n"
        "    然后拔插设备重进 maskrom；或临时改用 sudo 跑 flash。")

    def _download_boot(self, tool: Path, miniloader: Path):
        """DB 上传 miniloader；comm 失败时给 udev/权限提示而非裸 traceback。"""
        _info("上传 miniloader（DB）...", role=Role.ACTIVE)
        r = subprocess.run([str(tool), "DB", str(miniloader)],
                           capture_output=True, text=True)
        if r.returncode != 0:
            out = (r.stdout or "") + (r.stderr or "")
            if "Comm Object" in out:
                raise FlashError(self._UDEV_HINT)
            raise FlashError(f"upgrade_tool DB 失败（exit {r.returncode}）:\n{out}")
        time.sleep(1)

    def _upgrade_loader(self, tool: Path, miniloader: Path):
        """用工具文档顺序 ``UL <Loader> -noreset`` 写入并保持 loader。"""
        _info(f"写入 miniloader（UL {miniloader.name} -noreset）...", role=Role.ACTIVE)
        r = subprocess.run(
            [str(tool), "UL", str(miniloader), "-noreset"],
            capture_output=True,
            text=True,
        )
        if r.returncode != 0:
            out = (r.stdout or "") + (r.stderr or "")
            if "Comm Object" in out:
                raise FlashError(self._UDEV_HINT)
            raise FlashError(
                f"upgrade_tool UL {miniloader.name} -noreset 失败"
                f"（exit {r.returncode}）:\n{out}")
        time.sleep(1)

    def pre_flash(self, tool: Path, target_dir: Path, config: FlashConfig,
                  device: Optional["DeviceInfo"] = None):
        # DB (Download Boot) 仅在 maskrom 模式下上传 loader；
        # 设备已在 loader 模式时跳过，避免 "did not support this operation"
        if device is None:
            device = self.detect_device(tool)
        if device and device.mode != "maskrom":
            _info(f"设备已在 {device.mode} 模式，跳过 DB")
        elif config.pre_flash.download_boot:
            miniloader = target_dir / config.pre_flash.download_boot
            if not miniloader.exists():
                raise FlashError(f"未找到 miniloader: {miniloader}")
            self._download_boot(tool, miniloader)
        self._verify_device_identity(tool, config)
        # 仅显式声明 selector 的多介质 loader 执行 SSD（如 UFS=SATA）。
        # 单介质 RK3506 SPI NAND loader 不提供 SSD feature，storage 为空时保持
        # loader 当前介质，后续仍由 storage_type=spinand 进入 DI 路径。
        if config.storage:
            self._switch_storage(tool, config.storage)

    def pre_flash_all(self, tool: Path, target_dir: Path, config: FlashConfig,
                      device: Optional["DeviceInfo"] = None):
        """SPI NAND 全刷用原厂 UL 流程，其余介质保持既有 DB/SSD 路径。"""
        if (config.storage_type != "spinand"
                or not config.pre_flash.download_boot):
            return self.pre_flash(tool, target_dir, config, device)
        miniloader = target_dir / config.pre_flash.download_boot
        if not miniloader.exists():
            raise FlashError(f"未找到 miniloader: {miniloader}")
        if device is None:
            device = self.detect_device(tool)
        if device and device.mode == "maskrom":
            # DB 只在 RAM 中启动同一 miniloader，先取得身份信息，再允许 UL
            # 发生首次持久写入。
            self._download_boot(tool, miniloader)
        self._verify_device_identity(tool, config)
        self._upgrade_loader(tool, miniloader)
        if config.storage:
            self._switch_storage(tool, config.storage)

    def preflight(
        self,
        target_dir: Path,
        config: FlashConfig,
        partitions: list[FlashPartition],
    ) -> None:
        """SPI NAND 刷写前校验 parameter、mtd index、镜像与容量。"""
        if (config.partition_format != "mtd"
                and config.storage_type != "spinand"):
            return
        if (config.storage_type == "spinand"
                and any(part.name == "idbloader" for part in partitions)):
            raise FlashError(
                "SPI NAND flash-config 仍包含 idbloader 具名写入，属于旧版构建产物；"
                "请执行 flange build image -f 重新生成后再刷写")
        if not config.storage_size:
            raise FlashError("SPI NAND flash-config 缺少 storage_size")
        parameter = target_dir / (config.parameter or "parameter.txt")
        try:
            entries = parse_parameter_file(parameter)
            storage_bytes = parse_size(config.storage_size).bytes
            validate_parameter_capacity(entries, storage_bytes)
        except (OSError, ValueError) as exc:
            raise FlashError(f"SPI NAND parameter 刷写前校验失败: {exc}") from exc
        if not config.parameter_sha256:
            raise FlashError(
                "SPI NAND flash-config 缺少 parameter_sha256；"
                "请执行 flange build image -f 重新生成")
        actual_sha256 = hashlib.sha256(parameter.read_bytes()).hexdigest()
        if actual_sha256 != config.parameter_sha256:
            raise FlashError(
                "SPI NAND parameter 与 flash-config 摘要不一致；"
                "请执行 flange build image -f 重新生成")
        by_name = {entry.name: entry for entry in entries}
        if config.rootfs_mtd_index is None:
            raise FlashError("SPI NAND flash-config 缺少 rootfs_mtd_index")
        index = config.rootfs_mtd_index
        actual = entries[index].name if 0 <= index < len(entries) else "越界"
        if actual != "rootfs":
            raise FlashError(
                f"rootfs_mtd_index={index} 对应 {actual!r}，期望 'rootfs'")

        for part in partitions:
            entry = by_name.get(part.name)
            if entry is None:
                raise FlashError(
                    f"SPI NAND parameter 中不存在 flash-config 分区 {part.name!r}")
            try:
                config_offset = int(part.offset, 0)
                config_size = (
                    None if part.size == "remaining" else int(part.size, 0)
                )
            except (TypeError, ValueError) as exc:
                raise FlashError(
                    f"flash-config 分区 {part.name} offset/size 非法；"
                    "请重新构建 image") from exc
            if config_offset != entry.offset or config_size != entry.size:
                raise FlashError(
                    f"分区 {part.name} 布局不一致：flash-config="
                    f"0x{config_offset:x}/{part.size}，parameter="
                    f"0x{entry.offset:x}/"
                    f"{'remaining' if entry.size is None else f'0x{entry.size:x}'}")
            image = target_dir / part.image
            if not image.is_file():
                raise FlashError(f"SPI NAND 分区 {part.name} 镜像不存在: {image}")
            limit = entry.size_bytes(storage_bytes)
            image_bytes = image.stat().st_size
            if limit is None or image_bytes > limit:
                raise FlashError(
                    f"SPI NAND 分区 {part.name} 镜像 {image_bytes} bytes 超过容量 "
                    f"{limit} bytes")

    @staticmethod
    def _parse_storage_no(ssd_output: str, name: str) -> Optional[str]:
        """从 ``upgrade_tool SSD`` 列表解析指定存储名的编号。

        列表行形如 ``No=9\tSATA(*)``，``(*)`` 是当前激活标记，须忽略。"""
        for line in ssd_output.splitlines():
            m = re.match(r"\s*No=(\d+)\s+(\S+)", line)
            if m and m.group(2).split("(")[0].upper() == name.upper():
                return m.group(1)
        return None

    def _switch_storage(self, tool: Path, name: str):
        """把 loader 当前存储切到 name（如 UFS 的 "SATA"）。"""
        # SSD 无参时进入交互列表；喂 Q 退出以仅取列表。
        listing = subprocess.run(
            [str(tool), "SSD"], input="Q\n",
            capture_output=True, text=True)
        no = self._parse_storage_no(listing.stdout, name)
        if no is None:
            raise FlashError(
                f"upgrade_tool SSD 列表中未找到存储 {name!r}；"
                f"输出:\n{listing.stdout}")
        _info(f"切换存储到 {name}（SSD {no}）...", role=Role.ACTIVE)
        subprocess.run([str(tool), "SSD", no], check=True)
        _ok(f"存储 → {name}")

    def write_partition(self, tool: Path, offset: int, image: Path):
        try:
            size_mb = image.stat().st_size / (1024 * 1024)
            size_str = f", {size_mb:.1f}MB"
        except OSError:
            size_str = ""
        _info(f"写入 {image.name} (offset=0x{offset:X}{size_str})...", role=Role.ACTIVE)
        subprocess.run(
            [str(tool), "WL", str(offset), str(image)],
            check=True,
        )
        _ok(f"{image.name}")

    def write_named_partition(
        self,
        tool: Path,
        part: FlashPartition,
        image: Path,
        config: FlashConfig,
    ) -> None:
        """SPI NAND 用 DI 具名分区写；块设备 GPT 保持 WL offset 路径。"""
        if (config.partition_format != "mtd"
                and config.storage_type != "spinand"
                and not config.storage):
            return super().write_named_partition(tool, part, image, config)
        flag = self.DI_FLAGS.get(part.name, f"-{part.name}")
        _info(f"写 {part.name}（DI {flag}）...", role=Role.ACTIVE)
        subprocess.run([str(tool), "DI", flag, str(image)], check=True)
        _ok(part.name)

    # GPT primary：protective MBR 在 LBA 0，GPT header 在 LBA 1，紧随 16KiB
    # entries array（128 entry × 128 B，与扇区大小无关）。rockchip upgrade_tool
    # 拒绝 WL 0（保护 boot region），跳过 protective MBR，从 LBA 1 起写
    # header + entries 即可让 kernel 看到完整分区表。
    GPT_HEADER_LBA = 1
    GPT_ENTRY_ARRAY_BYTES = 16384  # 128 × 128，GPT 标准定长

    def _gpt_slice(self, sector: int) -> tuple[int, int]:
        """返回从 raw.img 截取 primary GPT 的 (起始字节, 长度字节)。

        起始 = LBA1 × sector；长度 = 1 个扇区 header + 16KiB entries array。
        512 时 = 512 + 16384 = 16896 = 33×512，与旧写死 33 扇区一致；
        4096 时 = 4096 + 16384 = 20480。"""
        seek = self.GPT_HEADER_LBA * sector
        length = sector + self.GPT_ENTRY_ARRAY_BYTES
        return seek, length

    def _gpt_wl_offset(self, sector: int) -> int:
        """GPT header 写入设备的 upgrade_tool WL 偏移（单位恒为 512 字节）。

        GPT primary header 位于设备 byte = GPT_HEADER_LBA × sector（4K 设备
        即 byte 4096）。WL 偏移单位是 512 字节（实板证实：idbloader entry
        offset 0x40 经 WL 64 落到 byte 32KB），故 WL 偏移 =
        GPT_HEADER_LBA × sector ÷ 512。512 设备→1（历史一致，回归安全）；
        4096 设备→8。早期版本直接传逻辑 LBA(1) 导致 4K 上 header 被写到
        byte 512，u-boot 在 byte 4096 读到垃圾 → GPT signature 错 → abort。"""
        return self.GPT_HEADER_LBA * sector // 512

    def write_gpt(self, tool: Path, target_dir: Path, config: "FlashConfig"):
        if config.partition_format == "mtd":
            return
        # UFS 与 SPI NAND 的分区表都由 flash_whole_disk 的
        # `DI -p parameter.txt` 写入；SPI NAND 即使不支持 SSD、storage 为空，
        # 也不得退回 WL raw.img 的 GPT 路径。
        if config.storage or config.storage_type == "spinand":
            return
        raw_img = target_dir / "image" / "raw.img"
        if not raw_img.exists():
            _warn(f"未找到 raw.img: {raw_img}，跳过 GPT 刷新（旧 GPT 可能丢失新分区）")
            return
        # 从 raw.img LBA 1 起截取 header + entries —— 跳过 protective MBR。
        # 扇区大小取自 flash-config（UFS=4096，eMMC/SD=512）。
        import tempfile
        sector = config.sector_size
        seek, size = self._gpt_slice(sector)
        wl_offset = self._gpt_wl_offset(sector)
        with tempfile.NamedTemporaryFile(suffix=".gpt.bin", delete=False) as tmp:
            with raw_img.open("rb") as f:
                f.seek(seek)
                tmp.write(f.read(size))
            tmp_path = Path(tmp.name)
        try:
            _info(f"刷新 GPT 表（WL {wl_offset}, "
                  f"扇区 {sector}, {size // 1024}KB）...", role=Role.ACTIVE)
            subprocess.run(
                [str(tool), "WL", str(wl_offset), str(tmp_path)],
                check=True,
            )
            _ok("GPT")
        finally:
            try:
                tmp_path.unlink()
            except OSError:
                pass

    def reboot(self, tool: Path):
        _info("重启设备...", role=Role.ACTIVE)
        subprocess.run([str(tool), "RD"], check=True)

    # upgrade_tool di 的已定义分区缩写；未列出的分区用 -<分区名> 指定。
    DI_FLAGS = {
        "uboot": "-u", "boot": "-b", "recovery": "-r",
        "kernel": "-k", "misc": "-m", "trust": "-t", "system": "-s",
    }

    def flash_whole_disk(self, tool: Path, target_dir: Path,
                         config: "FlashConfig") -> bool:
        """参数化 Rockchip 路径：`DI -p parameter.txt` + 具名 DI。

        UFS/SATA 由显式 storage selector 进入；SPI NAND 由 storage_type 进入，
        可不支持 SSD 并保持 loader 当前介质。传统 eMMC/SD 板返回 False，
        继续 WL offset 路径。"""
        if not config.storage and config.storage_type != "spinand":
            return False
        param = target_dir / (config.parameter or "parameter.txt")
        if not param.exists():
            raise FlashError(
                f"未找到 parameter.txt: {param}（请重新 build）")
        _info("写 parameter 分区布局（DI -p）...", role=Role.ACTIVE)
        subprocess.run([str(tool), "DI", "-p", str(param)], check=True)
        _ok("parameter/GPT")
        for part in config.partitions:
            image = target_dir / part.image
            if not image.exists():
                _info(f"跳过 {part.name}: {image} 不存在")
                continue
            self.write_named_partition(tool, part, image, config)
        return True

    def flash_spi_firmware(self, tool: Path, target_dir: Path,
                           device: Optional["DeviceInfo"] = None):
        """架构 A2：把合成的 spi.img（idbloader@32KiB + u-boot.itb@8MiB）写进
        SPI NOR。流程：DB miniloader → SSD SPINOR → WL 0 spi.img → RD。

        spi.img 由 build_spi_image 在构建期生成（board 声明 flash_spi_loader）。
        device 由调用方（wait_for_device）传入，避免在 DB 前再跑一次 LD 导致
        upgrade_tool "Creating Comm Object failed!"（与 pre_flash 同款契约）。"""
        spi = target_dir / "bootloader" / "spi.img"
        if not spi.exists():
            raise FlashError(
                f"未找到 spi.img: {spi}（board 需声明 flash_spi_loader 并重新 build）")
        if device is None:
            device = self.detect_device(tool)
        miniloader = target_dir / "bootloader" / "miniloader.bin"
        if device and device.mode == "maskrom" and miniloader.exists():
            self._download_boot(tool, miniloader)
        self._switch_storage(tool, "SPINOR")
        _info("写 SPI 启动固件（WL 0 spi.img）...", role=Role.ACTIVE)
        subprocess.run([str(tool), "WL", "0", str(spi)], check=True)
        _ok("spi.img")
        _info("重启设备...", role=Role.ACTIVE)
        subprocess.run([str(tool), "RD"], check=True)

class AllwinnerA733FlashStrategy(AllwinnerA733FlashPlan, FlashStrategy):
    """Allwinner A733 刷写策略 — SD 卡 dd 模式。"""

    def find_tool(self, project_dir: Path) -> Path:
        # SD 卡 dd 模式使用系统 dd，返回占位路径
        return Path("/usr/bin/dd")

    def detect_device(self, tool: Path) -> Optional[DeviceInfo]:
        # SD 卡模式不依赖 USB 设备检测
        return None

    def pre_flash(self, tool: Path, target_dir: Path, config: FlashConfig,
                  device: Optional["DeviceInfo"] = None):
        # SD 卡模式无需 pre_flash
        pass

    def write_partition(self, tool: Path, offset: int, image: Path):
        # SD 卡模式通过 raw.img dd，不逐分区写入
        pass

    def reboot(self, tool: Path):
        _info("SD 卡模式：请手动插入 SD 卡并重启设备")

class AmlogicFlashStrategy(AmlogicFlashPlan, FlashStrategy):
    """Amlogic 刷写策略 — 两段式 USB Burning。

    流程（详见 design.md Decision 5）：

    pre_flash 阶段：按板卡文档进入 MaskROM 模式
    （USB ``1b8e:c003``）。host 端调 ``boot-g12.py``（pyamlboot 提供的
    G12A/G12B/SM1 系列入口脚本，VIM3L 的 S905D3 属 SM1，复用 G12 协议）
    把裸 FIP ``bootloader/u-boot.bin`` 推到 SoC DDR；BL2 在 SRAM 解密执行
    → BL31 → u-boot proper；u-boot 启动后自动进入 fastboot gadget 模式
    （由 mainline board defconfig + ``flange_fastboot.config`` fragment 启用）。

    flash 主流程：host 端 ``fastboot`` 命令依次写各分区，``bootloader``
    分区由 u-boot 端板级 ``CONFIG_FASTBOOT_FLASH_MMC_DEV`` 指向 eMMC hw
    boot0 分区，offset 0x200；其他分区写 user area GPT。最后
    ``fastboot reboot``。

    host 端依赖：
    - ``pyamlboot``（pip install pyamlboot 或 git clone superna9999/pyamlboot），
      实际入口脚本 ``boot-g12.py``（不是 ``python3 -m pyamlboot.pyamlboot``）
    - ``android-tools-fastboot``（Ubuntu apt 包）
    """

    # MaskROM 模式 USB VID/PID（Amlogic 通用 BootROM 描述符）

    # pyamlboot 入口脚本名（由 pip install pyamlboot 暴露到 PATH，或在
    # 本地 git clone 后位于 repo 根）。SM1 family 的 S905D3 复用 G12
    # 协议（同代加密 v3），与 G12A/G12B/S905X3 共用。
    PYAMLBOOT_ENTRY = "boot-g12.py"

    # 枚举和只读握手共用总时限，每次探测还受剩余时限约束。
    FASTBOOT_WAIT_TIMEOUT = 30
    FASTBOOT_PROBE_TIMEOUT = 5
    FASTBOOT_GPT_TIMEOUT = 30

    def __init__(self) -> None:
        self._fastboot_serial: str | None = None

    def find_tool(self, project_dir: Path) -> Path:
        """查找 host 端 fastboot 工具。

        amlogic 主流程靠 host fastboot；pyamlboot 在 pre_flash 单独走
        ``shutil.which("boot-g12.py")``，不进 ``find_tool`` 路径。
        """
        from shutil import which
        fastboot = which("fastboot")
        if not fastboot:
            raise FlashError(
                "未找到 fastboot 命令。请安装：\n"
                "  Ubuntu: sudo apt install android-tools-fastboot\n"
                "  macOS:  brew install android-platform-tools"
            )
        return Path(fastboot)

    def detect_device(self, tool: Path) -> Optional[DeviceInfo]:
        """检测 amlogic 设备（MaskROM 或 fastboot 任一即可）。

        amlogic 刷写两段式：刚上电按 KEY1 时设备在 MaskROM 模式
        （``1b8e:c003``），``fastboot devices`` 看不到；pre_flash 推完
        u-boot 后才切到 fastboot gadget。``FlashExecutor.flash_all`` 在
        pre_flash 之前调 wait_for_device，所以这里必须把 MaskROM 也算
        "设备就绪"，否则首刷会卡死直到超时。

        探测顺序：MaskROM USB → fastboot devices（pre_flash 后用）。
        """
        # 1) MaskROM 阶段（pre_flash 前的常态）
        if self._probe_maskrom():
            return DeviceInfo("amlogic", "maskrom",
                              f"Amlogic MaskROM 设备 "
                              f"({self.MASKROM_VID}:{self.MASKROM_PID})")

        # 2) fastboot 阶段（pre_flash 推完 u-boot 之后）
        try:
            if self._find_fastboot_serial(tool, self.FASTBOOT_PROBE_TIMEOUT):
                return DeviceInfo("amlogic", "fastboot", "Amlogic fastboot 设备")
        except (subprocess.SubprocessError, OSError):
            pass
        return None

    @staticmethod
    def _find_fastboot_serial(tool: Path, timeout: float) -> str | None:
        """枚举唯一 fastboot 设备；错误输出不能当作设备序列号。"""
        result = subprocess.run(
            [str(tool), "devices"], check=True,
            capture_output=True, text=True, timeout=timeout,
        )
        serials = []
        for line in result.stdout.splitlines():
            fields = line.split()
            if len(fields) >= 2 and fields[1] == "fastboot":
                serials.append(fields[0])
        if len(serials) > 1:
            raise FlashError("检测到多台 fastboot 设备；请只连接待刷写的一台设备")
        return serials[0] if serials else None

    def _wait_fastboot_ready(self, tool: Path) -> None:
        """在写入前确认 USB 枚举和协议响应；只重试只读命令。"""
        self._fastboot_serial = None
        timeout = self.FASTBOOT_WAIT_TIMEOUT
        deadline = time.monotonic() + timeout
        last_error = "尚未枚举到 fastboot 设备"
        _info(f"等待 fastboot 就绪（USB 枚举与通信握手，最长 {timeout}s）...",
              role=Role.ACTIVE)
        while (remaining := deadline - time.monotonic()) > 0:
            phase = "USB 枚举"
            try:
                serial = self._find_fastboot_serial(
                    tool, min(self.FASTBOOT_PROBE_TIMEOUT, remaining))
                remaining = deadline - time.monotonic()
                if serial and remaining > 0:
                    phase = "通信握手"
                    result = subprocess.run(
                        [str(tool), "-s", serial, "getvar", "version"],
                        check=True, capture_output=True, text=True,
                        timeout=min(self.FASTBOOT_PROBE_TIMEOUT, remaining),
                    )
                    output = result.stdout + result.stderr
                    if re.search(r"^[ \t]*(?:\(bootloader\)[ \t]*)?version:[ \t]*\S+",
                                 output, re.MULTILINE):
                        self._fastboot_serial = serial
                        _ok(f"fastboot 已就绪 · {serial}")
                        return
                    last_error = "fastboot 未返回有效的 version 响应"
                else:
                    last_error = "尚未枚举到 fastboot 设备"
            except subprocess.TimeoutExpired:
                # run 会终止并回收超时进程；下一次探测重新打开 USB 会话。
                last_error = f"fastboot {phase}无响应"
            except subprocess.CalledProcessError as error:
                detail = str(error.stderr or error.stdout or error).strip()
                last_error = f"fastboot {phase}失败：{detail[-500:]}"
            except OSError as error:
                raise FlashError(f"无法执行 fastboot：{error}") from error
            remaining = deadline - time.monotonic()
            if remaining > 0:
                time.sleep(min(1, remaining))
        raise FlashError(
            f"等待 fastboot 就绪超时（{timeout}s）：{last_error}。\n"
            "尚未写入 GPT 或分区。请检查 USB 连接及其他刷写进程，"
            "确认板卡进入 fastboot 模式后重新运行 flange flash。"
        )

    def _probe_maskrom(self) -> bool:
        """探测 USB 总线上是否有 MaskROM 设备（``1b8e:c003``）。

        Linux 用 ``lsusb``；macOS 用 ``ioreg -p IOUSB -l``（system_profiler
        在某些非交互 shell 下输出为空，ioreg 更可靠）。任一工具不在或
        返回非零都视为"没找到"，由调用方决定是否继续等待。
        """
        vid = int(self.MASKROM_VID, 16)
        pid = int(self.MASKROM_PID, 16)
        # Linux 路径：lsusb 输出 `Bus xxx Device yyy: ID 1b8e:c003 Amlogic, Inc.`
        try:
            res = subprocess.run(
                ["lsusb"], capture_output=True, text=True, timeout=3,
            )
            if res.returncode == 0 and (
                f"{self.MASKROM_VID}:{self.MASKROM_PID}".lower()
                in res.stdout.lower()
            ):
                return True
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            pass
        # macOS 路径：ioreg 把 idVendor / idProduct 暴露为十进制
        try:
            res = subprocess.run(
                ["ioreg", "-p", "IOUSB", "-l"],
                capture_output=True, text=True, timeout=3,
            )
            if res.returncode == 0:
                out = res.stdout
                if (f'"idVendor" = {vid}' in out
                        and f'"idProduct" = {pid}' in out):
                    return True
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            pass
        return False

    @staticmethod
    def _resolve_pyamlboot_entry(entry: str) -> str:
        """绕过 pyenv 的 Shell shim，避免 macOS 清除动态库搜索环境。"""
        path = Path(entry).resolve()
        if path.parent.name != "shims":
            return str(path)
        pyenv = shutil.which("pyenv")
        if not pyenv:
            raise FlashError("boot-g12.py 指向 shim，但找不到 pyenv；请恢复 pyenv 或使用真实脚本路径")
        try:
            root = subprocess.check_output([pyenv, "root"], text=True, timeout=5).strip()
            if path.parent != (Path(root) / "shims").resolve():
                raise FlashError(f"无法识别 boot-g12.py 的 shim：{path}；请把真实脚本目录加入 PATH")
            resolved = Path(subprocess.check_output(
                [pyenv, "which", path.name], text=True, timeout=5,
            ).strip()).resolve()
        except (OSError, subprocess.SubprocessError) as error:
            raise FlashError(f"无法解析 pyenv 中的 boot-g12.py：{error}") from error
        if resolved.parent == path.parent or not resolved.is_file() or not os.access(resolved, os.X_OK):
            raise FlashError(f"pyenv 未返回可执行的真实 boot-g12.py：{resolved}")
        return str(resolved)

    @staticmethod
    def _darwin_dyld_lib_path() -> Optional[str]:
        """在 macOS 上返回应注入子进程 DYLD_FALLBACK_LIBRARY_PATH 的路径。

        pyamlboot 的 pyusb 通过 ctypes 加载 libusb；macOS 上 brew 装的
        libusb 在 /opt/homebrew/lib（Apple Silicon）或 /usr/local/lib
        （Intel）。前者不在 dyld 默认搜索路径，后者虽在但若残留 x86_64
        老 dylib 会与 arm64 Python arch 失配。把 brew 的 lib 路径强行
        加入 fallback 搜索路径，并先解析 Shell shim，直接启动真实入口。

        非 macOS 返回 None（Linux 走 udev rule / sudo 不需要这层）。
        """
        if sys.platform != "darwin":
            return None
        # brew --prefix 是权威；进程不存在时退到 Apple Silicon / Intel 默认路径
        try:
            prefix = subprocess.check_output(
                ["brew", "--prefix"], text=True, timeout=3,
            ).strip()
            return f"{prefix}/lib"
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError,
                subprocess.CalledProcessError):
            pass
        for guess in ("/opt/homebrew", "/usr/local"):
            if (Path(guess) / "lib" / "libusb-1.0.dylib").exists():
                return f"{guess}/lib"
        return None

    def _wait_maskrom_device(self, timeout: int = 30) -> None:
        """等待 USB 总线列出 MaskROM 设备。

        探测沿用 ``_probe_maskrom``（Linux lsusb / macOS ioreg）。两者都
        没找到或调用失败时仅打印 warning，不阻塞 —— pyamlboot 本身会在
        没有设备时报错，让其错误冒泡更直观。
        """
        _info(f"等待 MaskROM 设备（USB {self.MASKROM_VID}:{self.MASKROM_PID}）...",
              role=Role.ACTIVE)
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._probe_maskrom():
                _ok("MaskROM 设备已就绪")
                return
            time.sleep(1)
        _warn(f"等待 MaskROM 设备超时（{timeout}s），仍尝试 pyamlboot")

    def pre_flash(self, tool: Path, target_dir: Path, config: FlashConfig,
                  device: Optional["DeviceInfo"] = None):
        """pyamlboot 把 u-boot 推到 SoC DDR；板已在 fastboot 模式时跳过。

        ``detect_device`` 已能区分 MaskROM 与 fastboot 两种模式：
          - ``mode="maskrom"``：板刚通过 KEY1 + USB-C 进 BootROM，需要走完整
            的 pyamlboot 推送流程把 u-boot 上 DDR；
          - ``mode="fastboot"``：板已经在 u-boot fastboot gadget 模式（典型
            场景：上一轮 ``flange flash`` 用 ``fastboot reboot bootloader``
            重回 fastboot，或 Linux 跑 ``reboot bootloader`` 后 u-boot
            PREBOOT 检测 reboot_mode 自动进 fastboot）。此时 u-boot 已在
            DDR 跑，确认通信就绪后进入分区刷写。

        跳过 pyamlboot 可省去重复上传和 sudo 提示，同时
        避免要求用户接串口手动敲 ``fastboot usb 0`` —— PREBOOT 条件触发
        让 u-boot 自动进 fastboot，host 端 ``flange flash`` 就能纯 USB
        无人值守完成。
        """
        self._fastboot_serial = None
        if device is not None and device.mode == "fastboot":
            _info("板已在 fastboot 模式（u-boot 已在 DDR），跳过 pyamlboot 推送")
            self._wait_fastboot_ready(tool)
            return

        from shutil import which

        if not config.pre_flash.download_boot:
            raise FlashError(
                "amlogic pre_flash 缺少 download_boot 字段；请检查 flash-config.json"
            )
        boot_image = target_dir / config.pre_flash.download_boot
        if not boot_image.exists():
            raise FlashError(f"未找到引导镜像: {boot_image}")

        pyamlboot = which(self.PYAMLBOOT_ENTRY)
        if not pyamlboot:
            raise FlashError(
                f"未找到 {self.PYAMLBOOT_ENTRY}。请安装：\n"
                "  pip install pyamlboot\n"
                "  或 git clone https://github.com/superna9999/pyamlboot.git\n"
                "    并把仓库根目录加入 PATH"
            )
        if sys.platform == "darwin":
            pyamlboot = self._resolve_pyamlboot_entry(pyamlboot)

        # MaskROM 设备探测（best-effort）
        self._wait_maskrom_device(timeout=30)

        _info(f"上传 u-boot 到 SoC DDR（{boot_image.name}）...", role=Role.ACTIVE)
        # boot-g12.py 通常需要 root 权限访问 USB raw endpoint；
        # 若用户已配置 udev rule，sudo 可省略。这里默认带 sudo 与
        # Rockchip upgrade_tool 一致心智（rockchip 也需要 udev 或 sudo）。
        #
        # macOS Apple Silicon 特殊处理：brew 装的 libusb 在
        # /opt/homebrew/lib/，不在 dyld 默认搜索路径（/usr/local/lib，
        # /usr/lib）。若系统遗留 /usr/local/lib/libusb-1.0.dylib（Intel
        # x86_64 老 brew 或 Rosetta 工具留下的），ctypes find_library 会
        # 撞到 arch 失配的那一份，pyusb 报 "No backend available"。
        # 通过 ``env DYLD_FALLBACK_LIBRARY_PATH=<brew>/lib`` 透给子进程
        # 传入真实入口。DYLD_* 不能直接穿过 sudo，也不能在 env 之后
        # 再经过 pyenv 的 Shell shim；后者会再次触发 macOS 的环境清理。
        cmd = ["sudo"]
        dyld_extra = self._darwin_dyld_lib_path()
        if dyld_extra:
            cmd += ["env", f"DYLD_FALLBACK_LIBRARY_PATH={dyld_extra}"]
        cmd += [str(pyamlboot), str(boot_image)]
        subprocess.run(cmd, check=True)
        _ok("U-Boot 已上传到 DDR")
        self._wait_fastboot_ready(tool)

    def _run_fastboot(
        self, tool: Path, *args: str, timeout: float | None = None,
    ) -> None:
        """绑定已握手设备执行命令，透传输出，写入失败不自动重试。"""
        if self._fastboot_serial is None:
            raise FlashError("fastboot 尚未完成就绪握手；请重新运行 flange flash")
        cmd = [str(tool), "-s", self._fastboot_serial, *args]
        try:
            subprocess.run(cmd, check=True, timeout=timeout)
        except subprocess.TimeoutExpired as error:
            action = " ".join(args[:2])
            raise FlashError(
                f"fastboot {action} 超时（{timeout}s），设备端执行结果未知。\n"
                "已停止后续刷写，请检查 USB 连接并重新进入刷写模式后运行 flange flash。"
            ) from error

    def write_gpt(self, tool: Path, target_dir: Path, config: "FlashConfig"):
        """``fastboot oem format`` 让 u-boot 按实际 eMMC 容量重建 GPT。

        u-boot 端约定（详见目标板采用的 ``flange_fastboot.config``）：
          - PREBOOT 设 ``partitions`` env，含 user area GPT 分区描述
            （boot + rootfs；bootloader 在 hw boot0 不入 user area GPT）
          - ``CONFIG_FASTBOOT_CMD_OEM_FORMAT=y`` 启 ``oem format`` 子命令
          - ``CONFIG_CMD_GPT=y`` + ``CONFIG_RANDOM_UUID=y`` 提供 gpt write
            子命令与 UUID 生成
        ``oem format`` 内部直接调 ``gpt write mmc <FASTBOOT_FLASH_MMC_DEV>
        ${partitions}`` —— 按当前 mmc dev 容量计算 LBA / size，避开
        "raw.img GPT 字段指向 2GB 但 eMMC 14.6GB" 的尺寸不匹配问题，写完
        u-boot 自动 rescan 分区表，后续 ``flash boot/rootfs`` 立即可找到
        分区。本步骤必须在 ``fastboot flash boot/rootfs`` 之前。
        """
        _info("用 u-boot oem format 按实际 eMMC 容量重建 GPT...", role=Role.ACTIVE)
        self._run_fastboot(tool, "oem", "format", timeout=self.FASTBOOT_GPT_TIMEOUT)
        _ok("GPT")

    def write_partition(self, tool: Path, offset: int, image: Path):
        """通过 fastboot flash <name> <image> 写入分区。

        amlogic 的分区路由由 u-boot 端 ``CONFIG_FASTBOOT_GPT_NAME`` +
        ``CONFIG_FASTBOOT_FLASH_MMC_DEV=2`` 决定，不依赖 host 端 offset。
        分区名通过 ``image`` 文件路径反推 —— 在 ``flash_all`` 主流程中
        ``FlashExecutor`` 已按分区名调用，但抽象基类签名只给 offset，故
        这里从镜像路径反推分区名。
        """
        # 从镜像路径反推分区名：bootloader/u-boot.bin.sd.bin → bootloader,
        # boot/boot.img → boot, recovery/recovery.img → recovery,
        # rootfs/rootfs.img → rootfs。
        parent_name = image.parent.name
        partition_name = "bootloader" if parent_name == "bootloader" else parent_name

        try:
            size_mb = image.stat().st_size / (1024 * 1024)
            size_str = f", {size_mb:.1f}MB"
        except OSError:
            size_str = ""
        _info(f"fastboot flash {partition_name} ({image.name}{size_str})...", role=Role.ACTIVE)
        self._run_fastboot(tool, "flash", partition_name, str(image))
        _ok(f"{partition_name}")

    def reboot(self, tool: Path):
        """通过 fastboot reboot 触发 SoC 重启。"""
        _info("fastboot reboot...", role=Role.ACTIVE)
        self._run_fastboot(tool, "reboot")

class QualcommFlashStrategy(QualcommFlashPlan, FlashStrategy):
    """Qualcomm QCS6490 刷写策略 —— EDL 模式 + edl-ng（flange 首个高通刷写）。

    - 系统盘：``edl-ng --memory UFS write-sector 0 raw.img``（整盘，契合 flange raw.img）。
    - SPI EDK2 固件（bring-up 一次）：``edl-ng --loader prog_firehose_ddr.elf
      --memory spinor rawprogram rawprogram0.xml patch0.xml``。
    - EDL 模式需手动进入（按住 EDL 按钮 + USB3 上电）。
    """

    EDL_USB = "05c6:9008"  # Qualcomm HS-USB QDLoader 9008

    def find_tool(self, project_dir: Path) -> Path:
        """按 rockchip 同款约定 ``tools/<os>/<tool>/<tool>`` 定位；PATH 兜底。"""
        import shutil
        platform = "macos" if sys.platform == "darwin" else "linux"
        tool = project_dir / "tools" / platform / "edl-ng" / "edl-ng"
        if tool.exists():
            return tool
        exe = shutil.which("edl-ng")
        if exe:
            return Path(exe)
        raise FlashError(
            f"未找到 edl-ng。预期 {tool} 或 PATH。\n"
            "Radxa 下载：https://dl.radxa.com/q6a/images/edl-ng-dist.zip")

    def detect_device(self, tool: Path) -> Optional[DeviceInfo]:
        """被动 USB 枚举探测 EDL 9008（不调 edl-ng，避免抢 USB 会话）。

        起因：macOS 上若 detect 先用 edl-ng 开一次 USB 会话，紧接 write-sector
        再开一次，libusb darwin 偶发 transfer timed out + Sahara 握手失败、
        设备进入 Unknown 模式。这里只读 USB 拓扑信息（VID 05c6/PID 9008），
        不触碰设备，让 edl-ng 在真正刷写时独占会话。
        """
        if sys.platform == "darwin":
            # 用 ioreg（底层实时）而非 system_profiler（有缓存延迟、可能漏报）；
            # 匹配 idVendor=1478(0x05c6) + idProduct=36872(0x9008)。
            try:
                r = subprocess.run(["ioreg", "-p", "IOUSB", "-l"],
                                   capture_output=True, text=True, timeout=5)
                out = r.stdout
                if '"idVendor" = 1478' in out and '"idProduct" = 36872' in out:
                    return DeviceInfo(platform="qualcommqcs6490", mode="edl",
                                      description="Qualcomm HS-USB QDLoader 9008")
            except Exception:
                pass
        else:  # linux：读 /sys/bus/usb/devices
            try:
                for dev in Path("/sys/bus/usb/devices").glob("*"):
                    vid = dev / "idVendor"
                    pid = dev / "idProduct"
                    if vid.exists() and pid.exists():
                        if vid.read_text().strip() == "05c6" and \
                           pid.read_text().strip() == "9008":
                            return DeviceInfo(platform="qualcommqcs6490",
                                              mode="edl",
                                              description="Qualcomm HS-USB QDLoader 9008")
            except Exception:
                pass
        return None

    def pre_flash(self, tool: Path, target_dir: Path, config: FlashConfig,
                  device: Optional["DeviceInfo"] = None):
        # 系统盘刷写无需 pre_flash；SPI EDK2 固件单刷见 flash_spi_firmware（bring-up）。
        pass

    def write_partition(self, tool: Path, offset: int, image: Path):
        # Qualcomm 走整盘 write-sector（见 write_system_image），不逐分区写入。
        pass

    def reboot(self, tool: Path):
        try:
            subprocess.run([str(tool), "reset"], timeout=15)
        except Exception:
            _info("请手动断电重启 Q6A（退出 EDL 模式）")

    def flash_whole_disk(self, tool: Path, target_dir: Path,
                         config: "FlashConfig") -> bool:
        """整盘 edl-ng write-sector raw.img 到 UFS/eMMC（先 Sahara 上传 firehose loader）。"""
        raw = target_dir / "image" / "raw.img"
        if not raw.exists():
            raise FlashError(f"未找到整盘镜像 {raw}；请先执行 flange build")
        loader = self._locate_loader(target_dir)
        if (config.board in {"radxa-dragon-q6a", "radxa-dragon-q8b"}
                and loader.name != "prog_firehose_ufs.elf"):
            raise FlashError(
                f"未找到 {config.board} UFS firehose loader；"
                "请先执行 flange build bootloader")
        # 目标存储介质：v1 仅 UFS（板子默认）；后续可经 board/SoC config 覆盖。
        memory = "UFS"
        self.write_system_image(tool, raw, loader=loader, memory=memory)
        return True

    def _locate_loader(self, target_dir: Path) -> Path:
        """系统盘优先使用专用 UFS loader，兼容旧 QCS6490 产物。"""
        firmware_dir = target_dir / "bootloader" / "edk2-spi-firmware"
        for name in ("prog_firehose_ufs.elf", "prog_firehose_ddr.elf"):
            loader = firmware_dir / name
            if loader.exists():
                return loader
        raise FlashError(
            f"未找到 firehose loader：{firmware_dir}；"
            "请先执行 flange build bootloader")

    # ---- Qualcomm 专有（供 flash 编排 edl-ng 分支调用；非 ABC）----

    def write_system_image(self, tool: Path, raw_img: Path,
                           loader: Path, memory: str = "UFS"):
        """整盘写系统镜像。EDL 启动后处于 Sahara 模式，需先上传 firehose loader
        让设备进入 firehose 模式，再发 write-sector 指令。"""
        _step(f"edl-ng write-sector → {memory}（loader: {loader.name}）")
        cmd = [str(tool), "--loader", str(loader),
               "--memory", memory, "write-sector", "0", str(raw_img)]
        if subprocess.run(cmd).returncode != 0:
            raise FlashError("edl-ng write-sector 失败")

    def flash_spi_firmware(self, tool: Path, target_dir: Path,
                           device: Optional["DeviceInfo"] = None,
                           memory: str = "spinor"):
        """bring-up 一次性：刷 Radxa 预编 EDK2 SPI 固件。device 参数与 Rockchip
        签名对齐（Qualcomm 走 edl，不用它）。"""
        edk2_dir = target_dir / "bootloader" / "edk2-spi-firmware"
        loader = edk2_dir / "prog_firehose_ddr.elf"
        _step("edl-ng rawprogram → SPI EDK2 固件")
        cmd = [str(tool), "--loader", str(loader), "--memory", memory,
               "rawprogram", "rawprogram0.xml", "patch0.xml"]
        if subprocess.run(cmd, cwd=str(edk2_dir)).returncode != 0:
            raise FlashError("edl-ng SPI 固件刷写失败")

    def provision_ufs(self, tool: Path, target_dir: Path,
                      device: Optional["DeviceInfo"] = None,
                      profile: str = "lun0-only"):
        """按用户选择的布局一次性初始化全新 UFS。"""
        profiles = {
            "lun0-only": "provision_ufs31_lun0_only.xml",
            "qcom": "provision_ufs31.xml",
        }
        if profile not in profiles:
            raise FlashError(
                f"未知 UFS provisioning profile: {profile}；"
                f"可选: {', '.join(profiles)}")
        firmware_dir = target_dir / "bootloader" / "edk2-spi-firmware"
        loader = firmware_dir / "prog_firehose_ufs.elf"
        provision = firmware_dir / profiles[profile]
        missing = [path for path in (loader, provision) if not path.exists()]
        if missing:
            raise FlashError(
                f"缺少 UFS provisioning 产物：{', '.join(map(str, missing))}；"
                "请先执行 flange build bootloader")
        _step(f"edl-ng provision → UFS（profile: {profile}，一次性初始化）")
        cmd = [str(tool), "--loader", str(loader), "--memory", "UFS",
               "provision", str(provision)]
        if subprocess.run(cmd).returncode != 0:
            raise FlashError("edl-ng UFS provisioning 失败")
        _info("UFS 初始化完成；请重新进入 EDL 后执行 flange flash")


# 策略注册表
_FLASH_STRATEGIES: dict[str, type[FlashStrategy]] = {
    "rockchip": RockchipFlashStrategy,
    "allwinnera733": AllwinnerA733FlashStrategy,
    "amlogic": AmlogicFlashStrategy,
    "qualcommqcs6490": QualcommFlashStrategy,
    "qualcommsc8280xp": QualcommFlashStrategy,
}


def get_flash_strategy(platform: str, layer_stack=None) -> FlashStrategy:
    """根据平台名获取刷写策略实例。"""
    if layer_stack is not None:
        module = layer_stack.provider("flash", platform)
        if module is not None:
            result = module.create_strategy()
            if not isinstance(result, FlashStrategy):
                raise FlashError("create_strategy 必须返回 FlashStrategy")
            return result
    cls = _FLASH_STRATEGIES.get(platform)
    if not cls:
        raise FlashError(f"不支持的平台: {platform}（支持: {', '.join(_FLASH_STRATEGIES)}）")
    return cls()
