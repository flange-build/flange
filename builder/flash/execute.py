"""刷写执行与 CLI 入口（**宿主机执行期**）。

读 `flash-config.json`，选平台策略，逐分区写入。同 strategy，**不进**构建
逻辑指纹。
"""

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

from builder.flash.console import (
    _GRAY, _GREEN, _RED_BOLD, _WHITE, _YELLOW,
    _c, _err, _header, _info, _ok, _step, _warn,
)
from builder.flash.generate import FlashConfigGenerator
from builder.flash.model import FlashConfig, FlashError, FlashPartition
from builder.flash.strategy import get_flash_strategy
from builder.paths import PROJECT_ROOT


# ---------------------------------------------------------------------------
# 刷写执行器（宿主机使用）
# ---------------------------------------------------------------------------

class FlashExecutor:
    """读取 flash-config.json 并执行刷写。"""

    def __init__(self, target_dir: Path, project_dir: Path = None):
        config_path = target_dir / "flash-config.json"
        if not config_path.exists():
            raise FlashError(f"未找到 flash-config.json: {config_path}\n请先执行 flange build")
        self.config = FlashConfig.from_json(config_path)
        self.target_dir = target_dir
        self.project_dir = project_dir or Path.cwd()
        self.strategy = get_flash_strategy(self.config.platform)

    def flash_all(self, no_wait: bool = False, no_reboot: bool = False):
        """全量刷写所有分区。"""
        cfg = self.config
        _header(f"flange flash · {cfg.board} · {cfg.product}-{cfg.variant}")
        # 先做所有本地、非破坏性校验；镜像/parameter 不一致时不等待设备，
        # 更不会上传 loader 或写入任何分区。
        self.strategy.preflight(self.target_dir, cfg, cfg.partitions)
        tool = self.strategy.find_tool(self.project_dir)
        device = None
        if not no_wait:
            device = self.strategy.wait_for_device(tool)
        self.strategy.pre_flash_all(tool, self.target_dir, cfg, device)

        _step("刷写分区")
        start = time.time()
        # 全量刷写时分区表可能变化（如新增 recovery），先把 GPT 表写下去；
        # 平台默认实现是 no-op，rockchip 通过 raw.img 前几个 sector 刷写 GPT。
        self.strategy.write_gpt(tool, self.target_dir, cfg)
        # 整盘刷写钩子（如 Qualcomm edl-ng write-sector raw.img）：返回 True
        # 表示已处理，跳过 per-partition 循环；默认 False，走逐分区流程。
        whole_disk_handled = self.strategy.flash_whole_disk(
            tool, self.target_dir, cfg)
        if whole_disk_handled is not True:
            for part in cfg.partitions:
                image = self.target_dir / part.image
                if not image.exists():
                    _warn(f"跳过 {part.name}: 镜像不存在")
                    continue
                if (cfg.partition_format == "mtd"
                        or cfg.storage_type == "spinand"):
                    self.strategy.write_named_partition(tool, part, image, cfg)
                else:
                    self.strategy.write_partition(
                        tool, int(part.offset, 0), image)
        if no_reboot:
            _info("跳过重启（--no-reboot）")
        else:
            self.strategy.reboot(tool)
        elapsed = time.time() - start

        sep = "─" * 58
        print()
        print(_c(_WHITE, sep))
        print(_c(_GREEN, f" ✓ 刷写完成{_c(_GRAY, f'  {elapsed:.1f}s')}"))
        print(_c(_WHITE, sep))
        print()

    def flash_partition(self, name: str, no_wait: bool = False, no_reboot: bool = False):
        """刷写指定分区。"""
        requested_name = name
        if (self.config.partition_format == "mtd"
                or self.config.storage_type == "spinand"):
            name = {
                "bootloader": "uboot",
                "kernel": "boot",
            }.get(name, name)
        part = None
        for p in self.config.partitions:
            if p.name == name:
                part = p
                break
        if not part:
            available = [p.name for p in self.config.partitions]
            raise FlashError(
                f"未知分区: {requested_name}\n可用分区: {', '.join(available)}"
            )
        image = self.target_dir / part.image
        if not image.exists():
            raise FlashError(f"镜像不存在: {image}")

        self.strategy.preflight(self.target_dir, self.config, [part])
        tool = self.strategy.find_tool(self.project_dir)
        device = None
        if not no_wait:
            device = self.strategy.wait_for_device(tool)
        # SPI NAND 的 bootloader 由 loader(SPL) + uboot(proper) 两部分组成。
        # 原厂单刷路径也先 UL MiniLoaderAll，再 DI -uboot；若这里只做 DB/DI，
        # 会继续从 NAND 启动旧 SPL，形成“旧 SPL + 新 proper”的混合链路。
        if (name == "uboot"
                and self.config.storage_type == "spinand"):
            self.strategy.pre_flash_all(
                tool, self.target_dir, self.config, device)
        else:
            self.strategy.pre_flash(
                tool, self.target_dir, self.config, device)
        if (self.config.partition_format == "mtd"
                or self.config.storage_type == "spinand"):
            self.strategy.write_named_partition(
                tool, part, image, self.config)
        else:
            self.strategy.write_partition(tool, int(part.offset, 0), image)
        if no_reboot:
            _info("跳过重启（--no-reboot）")
        else:
            self.strategy.reboot(tool)
        print()
        print(_c(_GREEN, f" ✓ 分区 {requested_name} 刷写完成"))

    # 整盘镜像由 image 组件产出，各平台 ARTIFACT_NAMES 统一命名为 raw.img。
    WHOLE_DISK_IMAGE = "image/raw.img"

    def flash_raw(self, device: str):
        """dd 整盘刷写。"""
        firmware = self.target_dir / self.WHOLE_DISK_IMAGE
        if not firmware.is_file():
            raise FlashError(
                f"未找到整盘镜像 {self.WHOLE_DISK_IMAGE}: {self.target_dir}\n"
                f"  先执行 flange build 生成 image 产物；"
                f"SPI NAND target 不产整盘镜像，请改用 flange flash <partition>"
            )

        size_mb = firmware.stat().st_size / (1024 * 1024)
        _header("flange flash --raw")
        _info(f"镜像: {firmware.name} ({size_mb:.0f} MB)")
        _info(f"目标: {device}")
        confirm = input(_c(_YELLOW, "  ⚠ 将覆盖目标设备全部数据！确认？[y/N] "))
        if confirm.lower() != "y":
            _info("已取消")
            return

        _step("dd 刷写")
        subprocess.run(
            ["sudo", "dd", f"if={firmware}", f"of={device}",
             "bs=4M", "status=progress", "conv=fsync"],
            check=True,
        )
        subprocess.run(["sync"], check=True)
        print()
        print(_c(_GREEN, " ✓ dd 刷写完成"))

    def list_partitions(self):
        """列出所有可刷写分区。"""
        cfg = self.config
        _header(f"flange flash --list · {cfg.board} · {cfg.product}-{cfg.variant}")
        print(f"  {'分区名':<16} {'偏移':<12} {'类型':<8} {'镜像路径'}")
        print(f"  {'─'*14}   {'─'*10}   {'─'*6}   {'─'*24}")
        for p in cfg.partitions:
            exists = _c(_GREEN, "✓") if (self.target_dir / p.image).exists() else _c(_RED_BOLD, "✗")
            print(f"  {p.name:<16} {p.offset:<12} {p.type:<8} {p.image} [{exists}]")
        print()


# ---------------------------------------------------------------------------
# CLI 入口（python3 -m builder.flash）
# ---------------------------------------------------------------------------

def _cli_main():
    parser = argparse.ArgumentParser(
        prog="python3 -m builder.flash",
        description="flange 刷写工具",
    )
    subparsers = parser.add_subparsers(dest="command")

    # run 子命令
    run_parser = subparsers.add_parser("run", help="执行刷写")
    run_parser.add_argument("--target-dir", required=True, help="构建产物目录")
    run_parser.add_argument("--project-dir", default=".", help="项目根目录")
    run_parser.add_argument("--no-wait", action="store_true", help="跳过设备等待")
    run_parser.add_argument("--no-reboot", action="store_true", help="刷写完成后不触发设备重启")
    run_parser.add_argument("--raw", metavar="DEVICE", help="dd 整盘刷写到指定设备")
    run_parser.add_argument("--list", action="store_true", dest="list_parts", help="列出可刷写分区")
    run_parser.add_argument("--spi-firmware", action="store_true", dest="spi_firmware",
                            help="刷 SPI boot 固件（Qualcomm bring-up 一次性；需在 EDL 模式）")
    run_parser.add_argument(
        "--provision-ufs", nargs="?", const="lun0-only",
        choices=("lun0-only", "qcom"), metavar="PROFILE",
        help=("一次性初始化全新 Qualcomm UFS：lun0-only 为单用户 LUN；"
              "qcom 为官方 LUN 0-7 布局"))
    run_parser.add_argument("partition", nargs="?", help="指定分区名（不指定则全量刷写）")

    # generate 子命令（构建引擎调用）
    gen_parser = subparsers.add_parser("generate", help="生成 flash-config.json")
    gen_parser.add_argument("--config", required=True, help="FINAL_CONFIG JSON 文件路径")
    gen_parser.add_argument("--target-dir", required=True, help="输出目录")

    args = parser.parse_args()

    if args.command == "run":
        target_dir = Path(args.target_dir)
        project_dir = Path(args.project_dir)
        executor = FlashExecutor(target_dir, project_dir)

        if args.list_parts:
            executor.list_partitions()
        elif args.raw:
            executor.flash_raw(args.raw)
        elif args.provision_ufs:
            if not hasattr(executor.strategy, "provision_ufs"):
                raise FlashError(
                    f"平台 {executor.config.platform} 不支持 --provision-ufs")
            tool = executor.strategy.find_tool(executor.project_dir)
            device = None
            if not args.no_wait:
                device = executor.strategy.wait_for_device(tool)
            executor.strategy.provision_ufs(
                tool, executor.target_dir, device,
                profile=args.provision_ufs)
        elif args.spi_firmware:
            # Qualcomm bring-up：edl-ng 刷 SPI EDK2 固件（仅支持该方法的策略）
            if not hasattr(executor.strategy, "flash_spi_firmware"):
                raise FlashError(
                    f"平台 {executor.config.platform} 不支持 --spi-firmware")
            tool = executor.strategy.find_tool(executor.project_dir)
            device = None
            if not args.no_wait:
                device = executor.strategy.wait_for_device(tool)
            executor.strategy.flash_spi_firmware(tool, executor.target_dir, device)
        elif args.partition:
            executor.flash_partition(args.partition, no_wait=args.no_wait, no_reboot=args.no_reboot)
        else:
            executor.flash_all(no_wait=args.no_wait, no_reboot=args.no_reboot)

    elif args.command == "generate":
        config = json.loads(Path(args.config).read_text())
        gen = FlashConfigGenerator()
        gen.generate(config, Path(args.target_dir))

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    _cli_main()
