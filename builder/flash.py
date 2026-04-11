"""flash.sh 自动生成 — 从 FINAL_CONFIG 生成刷写脚本。"""

from pathlib import Path


class FlashGenerator:
    """生成可执行的 flash.sh 刷写脚本。"""

    def generate(self, config: dict, target_dir: Path):
        """生成 flash.sh 到 target_dir。"""
        flash_tool = config.get("flash_tool", "upgrade_tool")
        board = config["board"]
        product = config.get("product", "default")
        variant = config.get("variant", "release")

        script = f"""#!/bin/bash
# 自动生成 by flange — 请勿手动编辑
# board: {board}  product: {product}  variant: {variant}
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
FLASH_TOOL="{flash_tool}"

flash_bootloader() {{
    echo "刷写 bootloader..."
    "$FLASH_TOOL" db "$SCRIPT_DIR/bootloader/miniloader.bin"
    sleep 1
    "$FLASH_TOOL" wl 0x40 "$SCRIPT_DIR/bootloader/idbloader.img"
    "$FLASH_TOOL" wl 0x4000 "$SCRIPT_DIR/bootloader/bootloader.img"
}}

flash_kernel() {{
    echo "刷写 boot 分区..."
    "$FLASH_TOOL" wl 0x8000 "$SCRIPT_DIR/image/boot.img"
}}

flash_rootfs() {{
    echo "刷写 rootfs..."
    "$FLASH_TOOL" wl 0x40000 "$SCRIPT_DIR/image/rootfs.img"
}}

flash_all() {{
    flash_bootloader
    flash_kernel
    flash_rootfs
    echo "刷写完成，重启设备..."
    "$FLASH_TOOL" rd
}}

case "${{1:-all}}" in
    bootloader) flash_bootloader ;;
    kernel)     flash_kernel ;;
    rootfs)     flash_rootfs ;;
    all)        flash_all ;;
    *)          echo "用法: $0 [bootloader|kernel|rootfs|all]" ;;
esac
"""
        flash_sh = target_dir / "flash.sh"
        flash_sh.parent.mkdir(parents=True, exist_ok=True)
        flash_sh.write_text(script)
        flash_sh.chmod(0o755)
