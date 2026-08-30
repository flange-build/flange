"""Rockchip SPI NOR 启动固件（spi.img）合成（**构建期**）。

产物进 image 组件缓存，因此本模块**进**构建逻辑指纹。
"""

from pathlib import Path

from builder.flash.console import _info, _ok, _step
from builder.flash.model import FlashError


# ---------------------------------------------------------------------------
# Rockchip SPI NOR 启动固件（spi.img）合成
# ---------------------------------------------------------------------------

# SPI NOR 上的布局（字节偏移）。实板日志确认：rkbin SPL 在 SPI(MTD2) 上读
# u-boot.itb 于 sector 0x4000（= 8 MiB），与 eMMC/UFS 统一约定一致；idbloader
# 在 32 KiB（rk35xx BootROM 要求非 0 偏移）。
SPI_NOR_SIZE = 16 * 1024 * 1024          # 板载 SPI NOR 标称 16 MiB（容量上限校验用）
SPI_IDBLOADER_OFFSET = 0x8000            # 32 KiB
SPI_UBOOT_OFFSET = 0x800000             # 8 MiB（= sector 0x4000 × 512）
SPI_IMG_ALIGN = 0x10000                  # 镜像尾部上对齐 64 KiB


def build_spi_image(bootloader_dir: Path, out_path: Path,
                    idbloader_off: int = SPI_IDBLOADER_OFFSET,
                    uboot_off: int = SPI_UBOOT_OFFSET) -> Path:
    """把 idbloader.img + u-boot.itb 合成为可写入 SPI NOR 起始(LBA 0)的 spi.img。

    架构 A2：bootloader 全在 SPI（idbloader@32KiB + u-boot.itb@8MiB），UFS 只放
    OS。idbloader 用 mkimage -T rksd（RK3576 BootROM 已修复 SPI 散布 bug，无需
    rkspi）。

    镜像**只做到容纳 u-boot.itb 末端**（按 64KiB 上对齐），不填满整片 SPI ——
    SPINOR 实际可写扇区略少于标称容量（实测 32735 < 32768），写满会
    "partition too small"；尾部旧内容保留不影响启动（只用 idbloader+itb）。
    """
    idb = bootloader_dir / "idbloader.img"
    itb = bootloader_dir / "u-boot.itb"
    if not idb.exists() or not itb.exists():
        raise FlashError(f"合成 spi.img 缺少 {idb} 或 {itb}")
    idb_b = idb.read_bytes()
    itb_b = itb.read_bytes()
    end = uboot_off + len(itb_b)
    if end > SPI_NOR_SIZE:
        raise FlashError(
            f"u-boot.itb 末端 {end} 超过 SPI 容量 {SPI_NOR_SIZE}（u-boot.itb 太大）")
    size = (end + SPI_IMG_ALIGN - 1) & ~(SPI_IMG_ALIGN - 1)
    buf = bytearray(size)
    buf[idbloader_off:idbloader_off + len(idb_b)] = idb_b
    buf[uboot_off:uboot_off + len(itb_b)] = itb_b
    out_path.write_bytes(buf)
    return out_path


