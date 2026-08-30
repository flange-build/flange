"""架构 A2：Rockchip SPI NOR 启动固件 spi.img 合成 + 刷写测试。

spi.img = idbloader.img@32KiB + u-boot.itb@8MiB（sector 0x4000，实板日志确认的
rkbin SPL 统一偏移）。刷写：DB → SSD SPINOR → WL 0 spi.img → RD。
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch, MagicMock

from builder.flash import (
    build_spi_image,
    RockchipFlashStrategy,
    SPI_IDBLOADER_OFFSET,
    SPI_UBOOT_OFFSET,
    SPI_NOR_SIZE,
)


class TestBuildSpiImage:
    def test_layout_offsets(self, tmp_path):
        bl = tmp_path / "bootloader"
        bl.mkdir()
        (bl / "idbloader.img").write_bytes(b"\xaa" * 4096)
        (bl / "u-boot.itb").write_bytes(b"\xbb" * 8192)
        out = build_spi_image(bl, bl / "spi.img")
        data = out.read_bytes()
        # 只做到容纳 itb 末端（64KiB 上对齐），不填满整片 SPI；须 < SPINOR 容量
        assert SPI_UBOOT_OFFSET + 8192 <= len(data) < SPI_NOR_SIZE
        assert len(data) % 0x10000 == 0
        # idbloader 落在 32KiB
        assert data[SPI_IDBLOADER_OFFSET:SPI_IDBLOADER_OFFSET + 4096] == b"\xaa" * 4096
        # u-boot.itb 落在 8MiB（sector 0x4000）
        assert data[SPI_UBOOT_OFFSET:SPI_UBOOT_OFFSET + 8192] == b"\xbb" * 8192
        # 偏移 0 处保持空（rk35xx BootROM 要求非 0 偏移）
        assert data[:SPI_IDBLOADER_OFFSET] == b"\x00" * SPI_IDBLOADER_OFFSET

    def test_uboot_8mib_sector_0x4000(self):
        # 实板日志：SPL "Trying fit image at 0x4000 sector" → 8 MiB
        assert SPI_UBOOT_OFFSET == 0x4000 * 512
        assert SPI_IDBLOADER_OFFSET == 0x8000  # 32 KiB


class TestFlashSpiFirmware:
    def test_di_db_ssd_wl_sequence(self, tmp_path):
        bl = tmp_path / "bootloader"
        bl.mkdir()
        (bl / "spi.img").write_bytes(b"x")
        (bl / "miniloader.bin").write_bytes(b"m")
        s = RockchipFlashStrategy()
        with patch("builder.flash.strategy.subprocess.run") as run, \
             patch.object(s, "detect_device",
                          return_value=MagicMock(mode="maskrom")), \
             patch.object(s, "_switch_storage") as switch:
            run.return_value = MagicMock(returncode=0, stdout="")
            s.flash_spi_firmware(Path("ut"), tmp_path)
        # 切到 SPINOR
        switch.assert_called_once_with(Path("ut"), "SPINOR")
        cmds = [" ".join(map(str, c.args[0])) for c in run.call_args_list]
        assert any("DB" in c and "miniloader.bin" in c for c in cmds)
        assert any("WL 0 " in c and "spi.img" in c for c in cmds)
        assert any(c.endswith("RD") for c in cmds)
