"""Rockchip UFS 刷写走 di（DownloadImage）路径测试。

UFS 板（flash_storage=SATA）：`di -p parameter.txt` 建 GPT + `di -<abbr> img`
逐分区，flash_whole_disk 返回 True 跳过基类 WL。非 UFS 板返回 False。
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch, MagicMock

from builder.flash import RockchipFlashStrategy, FlashConfig, FlashPartition


def _cfg(storage, parts):
    return FlashConfig(
        platform="rockchip", flash_tool="upgrade_tool",
        board="radxa-rock-4d", product="default", variant="debug",
        sector_size=4096, storage=storage,
        partitions=parts)


def _parts():
    names = [("idbloader", "bootloader/idbloader.img", "raw"),
             ("uboot", "bootloader/u-boot.itb", "raw"),
             ("boot", "boot/boot.img", "ext4"),
             ("recovery", "recovery/recovery.img", "ext4"),
             ("rootfs", "rootfs/rootfs.img", "ext4")]
    return [FlashPartition(name=n, offset="0x0", type=t, image=i)
            for n, i, t in names]


class TestDiFlashFlow:
    def test_no_storage_returns_false(self, tmp_path):
        """非 UFS 板不走 di，返回 False（继续基类 WL 逐分区）。"""
        s = RockchipFlashStrategy()
        assert s.flash_whole_disk(Path("ut"), tmp_path, _cfg("", _parts())) is False

    def test_ufs_di_sequence(self, tmp_path):
        # 准备 parameter.txt + 各分区镜像
        (tmp_path / "parameter.txt").write_text("CMDLINE: mtdparts=...\n")
        for rel in ("bootloader/idbloader.img", "bootloader/u-boot.itb",
                    "boot/boot.img", "recovery/recovery.img", "rootfs/rootfs.img"):
            p = tmp_path / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"x")
        s = RockchipFlashStrategy()
        with patch("builder.flash.strategy.subprocess.run") as run:
            run.return_value = MagicMock(returncode=0)
            ret = s.flash_whole_disk(Path("ut"), tmp_path, _cfg("SATA", _parts()))
        assert ret is True
        cmds = [c.args[0] for c in run.call_args_list]
        # 第一条：di -p parameter.txt
        assert cmds[0][1:3] == ["DI", "-p"]
        # 各分区用正确缩写/名字
        joined = [" ".join(map(str, c)) for c in cmds]
        assert any("DI -u " in j and "u-boot.itb" in j for j in joined)
        assert any("DI -b " in j and "boot.img" in j for j in joined)
        assert any("DI -r " in j and "recovery.img" in j for j in joined)
        # idbloader / rootfs 无标准缩写 → 用 -<分区名>
        assert any("DI -idbloader " in j for j in joined)
        assert any("DI -rootfs " in j for j in joined)
