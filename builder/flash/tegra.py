"""NVIDIA Tegra186 tegraflash 刷写：构建期生成刷写包，宿主机调用 BSP 的 tegraflash。

构建期（image 组件与 flash-config 生成）：按 L4T flash.sh 的规则渲染分区布局、生成
版本文件与刷写参数，把刷写包内每个文件的摘要写进 ``manifest.json``。

宿主机期（``TegraFlashStrategy``）：在刷写包的临时副本里运行 tegraflash（它会在
当前目录写签名中间文件，且访问 USB 需要 root），调用顺序与实测成功的 flash.sh 一致：
``tegrarcm_v2 --uid`` → ``tegraflash --skipuid dump eeprom`` 核对模块身份 →
``tegraflash --cmd "flash; reboot"`` 或按分区 ``signwrite`` / ``write``。
tegraflash 的宿主二进制只有 x86_64 Linux 版本。
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path, PurePosixPath

from builder.flash.console import _info, _ok, _step
from builder.flash.model import (
    DeviceInfo, FlashConfig, FlashError, FlashPartition, PreFlashConfig,
)
from builder.flash.plan import TegraFlashPlan
from builder.flash.qdl_output import stream_qdl
from builder.flash.strategy import FlashStrategy

PLATFORM = "nvidiategra186"
BUNDLE_PATH = "image/tegraflash-bundle"
MANIFEST = "manifest.json"
LAYOUT = "flash.xml"
SYSTEM_IMAGE = "system.img"
VERSION_FILE = "emmc_bootblob_ver.txt"
# T186 的 USB Recovery（RCM）身份；PID 7c18 只属于 Tegra186，同时起到 SoC 核对作用。
RECOVERY_VID, RECOVERY_PID = "0955", "7c18"
USB_DEVICES = Path("/sys/bus/usb/devices")
# flange 构建产出、可单独更新的分区；其余是 NVIDIA 启动链，单刷需要 --yes。
USER_PARTITIONS = ("APP", "kernel-dtb")
# 这些分区模板 token 指向 flange 生成的文件，由 image 组件填写，配置不得声明。
GENERATED_TOKENS = ("APPSIZE", "APPFILE", "KERNELDTB-FILE", "LNXFILE", "BOOTCTRL-FILE", "VERFILE")
# tegraflash 参数顺序与 flash.sh 生成的 flashcmd.txt 一致。
BCT_ARG_ORDER = (
    "misc_config", "pinmux_config", "pmic_config", "pmc_config", "prod_config",
    "scr_config", "scr_cold_boot_config", "br_cmd_config", "dev_params",
)
MANIFEST_LIMIT = 4 * 1024 * 1024


def digest(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            sha.update(block)
    return sha.hexdigest()


def posix_cksum(data: bytes) -> int:
    """POSIX ``cksum`` 的 CRC（flash.sh 用它校验版本文件），与 zlib.crc32 不同。"""
    crc = 0

    def update(byte: int) -> None:
        nonlocal crc
        crc ^= byte << 24
        for _ in range(8):
            crc = ((crc << 1) ^ 0x04C11DB7) if crc & 0x80000000 else crc << 1
            crc &= 0xFFFFFFFF

    for byte in data:
        update(byte)
    length = len(data)
    while length:
        update(length & 0xFF)
        length >>= 8
    return ~crc & 0xFFFFFFFF


def render_layout(template: str, tokens: dict[str, str]) -> str:
    """按 flash.sh 的 sed 规则替换分区模板 token。

    token 以非 ``[A-Za-z0-9-]`` 字符为边界（``MB1NAME_b`` 仍会替换为 ``mb1_b``）；
    值为空的 token 若位于 ``<filename>`` 行，整行删除——分区保留但不写入文件。
    """
    if not tokens:
        return template
    pattern = re.compile(
        r"(?<![A-Za-z0-9-])("
        + "|".join(re.escape(name) for name in sorted(tokens, key=len, reverse=True))
        + r")(?![A-Za-z0-9-])"
    )
    unused = sorted(set(tokens) - set(pattern.findall(template)))
    if unused:
        raise FlashError(f"分区模板中不存在这些 token（拼写错误或模板不匹配）: {', '.join(unused)}")
    lines = []
    for line in template.splitlines(keepends=True):
        if "<filename>" in line:
            match = pattern.search(line)
            if match and tokens[match.group(1)] == "":
                continue
        lines.append(pattern.sub(lambda found: tokens[found.group(1)], line))
    return "".join(lines)


def layout_partitions(layout: str) -> list[dict]:
    """列出分区布局中需要写入文件的分区（名称、文件、字节数、是否签名）。"""
    try:
        root = ET.fromstring(layout)
    except ET.ParseError as error:
        raise FlashError(f"分区布局 XML 无效: {error}") from error
    partitions = []
    for device in root.findall("device"):
        for node in device.findall("partition"):
            filename = (node.findtext("filename") or "").strip()
            if not filename:
                continue
            if PurePosixPath(filename).name != filename:
                raise FlashError(f"分区 {node.get('name')} 的文件名不是刷写目录中的文件: {filename}")
            partitions.append({
                "name": node.get("name"),
                "file": filename,
                "bytes": int((node.findtext("size") or "0").strip(), 0),
                "sign": node.get("oem_sign") == "true",
            })
    names = [entry["name"] for entry in partitions]
    if len(names) != len(set(names)):
        raise FlashError("分区布局中存在重名分区")
    return partitions


def flash_args(tegraflash: dict) -> list[str]:
    """除 ``--cmd`` 外的 tegraflash 参数，等价于 flash.sh 生成的 flashcmd.txt。"""
    bct = tegraflash["bct_configs"]
    args = ["--bl", tegraflash["bl"]]
    if "sdram_config" in bct:
        args += ["--sdram_config", bct["sdram_config"]]
    args += ["--odmdata", tegraflash["odmdata"], "--applet", tegraflash["applet"],
             "--cfg", LAYOUT, "--chip", tegraflash["chip"]]
    for name in BCT_ARG_ORDER:
        if name in bct:
            args += [f"--{name}", bct[name]]
    args += ["--bins", "; ".join(f"{entry['type']} {entry['file']}" for entry in tegraflash["bins"])]
    return args


def version_file(bsp_version: str, identity: dict, timestamp: str) -> str:
    """flash.sh 写入 VER 分区的 NV3 版本文件（OTA 工具读取）。"""
    fields = dict(re.findall(r"^(BSP_BRANCH|BSP_MAJOR|BSP_MINOR)=(\S+)$", bsp_version, re.M))
    if len(fields) != 3:
        raise FlashError("BSP nv_tegra/bsp_version 缺少 BSP_BRANCH / BSP_MAJOR / BSP_MINOR")
    body = (
        "NV3\n"
        f"# R{fields['BSP_BRANCH']} , REVISION: {fields['BSP_MAJOR']}.{fields['BSP_MINOR']}\n"
        f"BOARDID={identity['board_id']} BOARDSKU={identity['board_sku']} FAB={identity['fabs'][0]}\n"
        f"{timestamp}\n"
    )
    data = body.encode()
    return body + f"BYTES:{len(data)} CRC32:{posix_cksum(data)}\n"


def write_manifest(bundle: Path, config: dict, partitions: list[dict], args: list[str]) -> None:
    """记录刷写包全部文件摘要；宿主机刷写前据此拒绝任何被替换或混入的文件。"""
    files = {}
    for path in sorted(bundle.rglob("*")):
        relative = path.relative_to(bundle).as_posix()
        if relative == MANIFEST:
            continue
        if path.is_symlink():
            files[relative] = {"symlink": os.readlink(path)}
        elif path.is_file():
            files[relative] = {"sha256": digest(path), "bytes": path.stat().st_size}
    tegraflash = config["bootloader"]["tegraflash"]
    manifest = {
        "version": 1,
        "board": config["board"],
        "soc": config["soc"],
        "chip": tegraflash["chip"],
        "applet": tegraflash["applet"],
        "identity": tegraflash["identity"],
        "args": args,
        "partitions": [
            {**entry, "protected": entry["name"] not in USER_PARTITIONS} for entry in partitions
        ],
        "files": files,
    }
    (bundle / MANIFEST).write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")


def validate_bundle(bundle: Path) -> dict:
    """刷写包必须与 manifest 完全一致：文件集合、摘要、链接目标都不能变。"""
    manifest_path = bundle / MANIFEST
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise FlashError(f"缺少 tegraflash manifest: {manifest_path}")
    if manifest_path.stat().st_size > MANIFEST_LIMIT:
        raise FlashError("tegraflash manifest 超出大小限制")
    try:
        manifest = json.loads(manifest_path.read_text())
    except (OSError, ValueError) as error:
        raise FlashError("tegraflash manifest 无效") from error
    if not isinstance(manifest, dict) or manifest.get("version") != 1:
        raise FlashError("tegraflash manifest 版本不受支持")
    files = manifest.get("files")
    if not isinstance(files, dict):
        raise FlashError("tegraflash manifest 缺少文件清单")
    actual = {
        path.relative_to(bundle).as_posix()
        for path in bundle.rglob("*")
        if path.is_symlink() or path.is_file()
    } - {MANIFEST}
    if actual != set(files):
        extra, missing = sorted(actual - set(files)), sorted(set(files) - actual)
        raise FlashError(f"刷写包文件与 manifest 不一致；多出: {extra or '无'}，缺少: {missing or '无'}")
    mismatched = []
    for relative, expected in files.items():
        path = bundle / relative
        if "symlink" in expected:
            target = (path.parent / expected["symlink"]).resolve()
            if (not path.is_symlink() or os.readlink(path) != expected["symlink"]
                    or not target.is_relative_to(bundle.resolve())):
                mismatched.append(relative)
        elif (path.is_symlink() or path.stat().st_size != expected.get("bytes")
              or digest(path) != expected.get("sha256")):
            mismatched.append(relative)
    if mismatched:
        raise FlashError(f"刷写包文件摘要与 manifest 不符: {', '.join(mismatched)}")
    for entry in manifest.get("partitions") or []:
        if entry.get("file") not in files:
            raise FlashError(f"分区 {entry.get('name')} 引用的文件不在刷写包内: {entry.get('file')}")
    for required in (LAYOUT, "tegraflash.py"):
        if required not in files:
            raise FlashError(f"刷写包缺少 {required}")
    return manifest


def flash_partitions(manifest: dict) -> list[FlashPartition]:
    """tegraflash 按分区名写入，偏移由它自行分配，这里不记录偏移。"""
    return [
        FlashPartition(
            name=entry["name"],
            offset="-",
            type="ext4" if entry["name"] == "APP" else "raw",
            image=f"{BUNDLE_PATH}/{entry['file']}",
            protected=entry["protected"],
            size=str(entry["bytes"] // 512),
        )
        for entry in manifest["partitions"]
    ]


def make_flash_config(config: dict, target_dir: Path) -> FlashConfig:
    bundle = target_dir / BUNDLE_PATH
    manifest = validate_bundle(bundle)
    return FlashConfig(
        platform=PLATFORM, flash_tool="tegraflash", board=config["board"],
        product=config.get("product", "default"), variant=config.get("variant", "release"),
        soc=config["soc"], storage_type="emmc", partitions=flash_partitions(manifest),
        pre_flash=PreFlashConfig(usb_vid=RECOVERY_VID, usb_pid=RECOVERY_PID),
        bundle_manifest=f"{BUNDLE_PATH}/{MANIFEST}",
        bundle_manifest_sha256=digest(bundle / MANIFEST),
    )


# 宿主机执行期 ---------------------------------------------------------------

# tegraflash 写满 28 GiB APP（稀疏镜像只写有效数据）实测约 10~15 分钟，留足余量。
FLASH_TIMEOUT = 3600
PROBE_TIMEOUT = 120


class TegraFlashStrategy(TegraFlashPlan, FlashStrategy):
    """全部写入前完成刷写包摘要、唯一 Recovery 设备与模块 EEPROM 身份核对。"""

    allow_protected = False
    supports_no_reboot = False
    uses_named_partitions = True

    def preflight(self, target_dir, config, partitions):
        if sys.platform != "linux" or platform.machine().lower() not in {"x86_64", "amd64"}:
            raise FlashError(
                "tegraflash 的宿主工具（tegrarcm_v2 / tegradevflash_v2 等）只有 x86_64 Linux 版本，"
                "请在 x86_64 Linux 宿主上刷写"
            )
        _step("校验 tegraflash 刷写包摘要（system.img 较大，需要一些时间）")
        manifest_path = target_dir / BUNDLE_PATH / MANIFEST
        if (config.bundle_manifest != f"{BUNDLE_PATH}/{MANIFEST}" or not manifest_path.is_file()
                or digest(manifest_path) != config.bundle_manifest_sha256):
            raise FlashError("tegraflash manifest 与 flash-config 摘要不符，请重新 flange build")
        self.bundle = target_dir / BUNDLE_PATH
        self.manifest = validate_bundle(self.bundle)
        canonical = flash_partitions(self.manifest)
        if config.partitions != canonical:
            raise FlashError("flash-config 与刷写包分区不一致，请重新 flange build")
        self.full = list(partitions) == canonical
        if not self.full:
            for part in partitions:
                if part not in canonical:
                    raise FlashError(f"单刷分区不是刷写包中的原始条目: {part.name}")
                if part.protected and not self.allow_protected:
                    raise FlashError(
                        f"{part.name} 是 NVIDIA 启动链分区（受保护）；核对刷写包后使用 --yes 明确确认"
                    )
        self.workdir = None

    def find_tool(self, project_dir: Path) -> Path:
        python = shutil.which("python3")
        if not python:
            raise FlashError("未找到 python3：tegraflash.py 需要宿主 python3")
        if os.geteuid() != 0 and not shutil.which("sudo"):
            raise FlashError("tegraflash 访问 USB Recovery 设备需要 root，未找到 sudo")
        return Path(python)

    @staticmethod
    def _recovery_devices() -> list[DeviceInfo]:
        devices = []
        for node in sorted(USB_DEVICES.glob("*")):
            vendor, product = node / "idVendor", node / "idProduct"
            if not vendor.is_file() or not product.is_file():
                continue
            if (vendor.read_text().strip(), product.read_text().strip()) == (RECOVERY_VID, RECOVERY_PID):
                devices.append(DeviceInfo(PLATFORM, "recovery", "Tegra186 USB Recovery", serial=node.name))
        return devices

    def detect_device(self, tool: Path):
        devices = self._recovery_devices()
        if len(devices) > 1:
            raise FlashError(
                f"检测到 {len(devices)} 台 Tegra186 Recovery 设备（USB {RECOVERY_VID}:{RECOVERY_PID}）；请只连接目标 TX2"
            )
        return devices[0] if devices else None

    def wait_for_device(self, tool: Path, timeout: int = 120) -> DeviceInfo:
        if self.detect_device(tool) is None:
            _info("让 TX2 进入 USB Recovery：按住 REC，按一下 RST，约 2 秒后松开 REC")
        return super().wait_for_device(tool, timeout)

    @staticmethod
    def _as_root(command: list[str]) -> list[str]:
        return command if os.geteuid() == 0 else ["sudo", *command]

    def _prepare_workdir(self) -> None:
        """tegraflash 在当前目录写签名文件，复制刷写包，大镜像以链接引用。"""
        self.workdir = Path(tempfile.mkdtemp(prefix="flange-tegraflash-"))
        for relative, entry in self.manifest["files"].items():
            source, target = self.bundle / relative, self.workdir / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            if "symlink" in entry:
                target.symlink_to(entry["symlink"])
            elif relative == SYSTEM_IMAGE:
                target.symlink_to(source.resolve())
            else:
                shutil.copy2(source, target)
        _info(f"tegraflash 工作目录：{self.workdir}")

    def _run(self, name: str, command: list[str], *, timeout: int) -> None:
        log = self.workdir / f"flange-{name}.log"
        _info(f"实时日志：{log}")
        try:
            code = stream_qdl(self._as_root(command), self.workdir, log, timeout)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise FlashError(f"{name} 执行失败或超时（不自动重试），日志: {log}；{error}") from error
        if code:
            raise FlashError(f"{name} 失败（退出码 {code}），日志: {log}")

    def _tegraflash(self, tool: Path, name: str, cmd: str, *, timeout: int) -> None:
        self._run(name, [str(tool), "tegraflash.py", *self.manifest["args"], "--cmd", cmd],
                  timeout=timeout)

    def _board_info(self) -> dict[str, str]:
        values = {}
        for key, flag in (("board_id", "-i"), ("fab", "-f"), ("board_sku", "-k"), ("revision", "-r")):
            result = subprocess.run(
                self._as_root(["./chkbdinfo", flag, "cvm.bin"]), cwd=self.workdir,
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode:
                raise FlashError(f"chkbdinfo {flag} 解析 EEPROM 失败: {result.stderr.strip()}")
            values[key] = result.stdout.strip()
        return values

    def pre_flash(self, tool, target_dir, config, device=None):
        # --no-wait 只跳过等待，不跳过设备枚举与身份核对。
        observed = self.detect_device(tool)
        if observed is None or (device and observed.serial != device.serial):
            raise FlashError(f"未检测到唯一的 USB Recovery 设备（{RECOVERY_VID}:{RECOVERY_PID}）")
        if os.geteuid() != 0:
            subprocess.run(["sudo", "-v"], check=True)
        self._prepare_workdir()
        _step("读取模块 EEPROM 核对身份")
        self._run("tegrarcm-uid", ["./tegrarcm_v2", "--uid"], timeout=PROBE_TIMEOUT)
        self._run(
            "dump-eeprom",
            [str(tool), "tegraflash.py", "--chip", self.manifest["chip"],
             "--applet", self.manifest["applet"], "--skipuid",
             "--cmd", "dump eeprom boardinfo cvm.bin"],
            timeout=PROBE_TIMEOUT,
        )
        info, expected = self._board_info(), self.manifest["identity"]
        if (info["board_id"] != expected["board_id"] or info["board_sku"] != expected["board_sku"]
                or info["fab"] not in expected["fabs"]):
            raise FlashError(
                "模块身份与刷写包不符，已停止且未写入任何分区；"
                f"期望 board ID {expected['board_id']} / SKU {expected['board_sku']} / "
                f"FAB {', '.join(expected['fabs'])}，实际 {info['board_id']} / {info['board_sku']} / "
                f"{info['fab']}（REV {info['revision']}）"
            )
        _ok(f"模块身份一致：{info['board_id']}-{info['fab']}-{info['board_sku']}-{info['revision']}")

    def pre_flash_all(self, tool, target_dir, config, device=None):
        self.pre_flash(tool, target_dir, config, device)
        if self.allow_protected:
            return
        if os.environ.get("FLANGE_NO_INTERACTION") or not sys.stdin.isatty():
            raise FlashError("全量刷写会重写整个 eMMC（含 APP 上的全部数据）；确认后添加 --yes")
        answer = input("  ⚠ 将重写 TX2 的整个 eMMC（分区表、启动链与 APP 全部数据）。确认？[y/N] ")
        if answer.strip().lower() != "y":
            raise KeyboardInterrupt

    def flash_whole_disk(self, tool, target_dir, config) -> bool:
        self._tegraflash(tool, "flash", "flash; reboot", timeout=FLASH_TIMEOUT)
        return True

    def write_named_partition(self, tool, part, image, config):
        entry = next(item for item in self.manifest["partitions"] if item["name"] == part.name)
        # 与 flash.sh -k 一致：需要 OEM 签名的分区用 signwrite，其余直接 write。
        verb = "signwrite" if entry["sign"] else "write"
        self._tegraflash(tool, f"write-{part.name}", f"{verb} {part.name} {entry['file']}; reboot",
                         timeout=FLASH_TIMEOUT)

    def write_partition(self, tool, offset, image):
        raise FlashError("tegraflash 只能按分区名写入，不支持按偏移写")

    def reboot(self, tool):
        # 刷写命令本身以 reboot 结束；成功后清理 root 写入的工作目录，失败时保留日志。
        if self.workdir is not None:
            subprocess.run(self._as_root(["rm", "-rf", str(self.workdir)]), check=False)
            self.workdir = None
