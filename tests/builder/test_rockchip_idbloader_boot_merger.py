"""RK3576 idbloader 经 boot_merger 装配（取代 mkimage -T rksd）。

覆盖 openspec selfbuild-rk3576-spi-image：
- `_extract_idb_path` 从 RK3576MINIALL.ini 的 [OUTPUT] IDB_PATH= 解析 idblock 文件名；
- `idbloader_method=="boot_merger"` 时 compile 跳过 mkimage、拷 boot_merger 的 IDB_PATH
  产物为 idbloader.img，且不提前 return（_firmware_dir 赋值、collect 不抛）；
- 其他 RK35xx（无 idbloader_method）仍走 mkimage -T rksd。
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from builder.platforms.rockchip.bootloader import RockchipBootloaderBuilder


_INI = """\
[CHIP_NAME]
NAME=RK3576
[CODE471_OPTION]
NUM=1
Path1=bin/rk35/rk3576_ddr_v1.10.bin
[LOADER_OPTION]
NUM=3
FlashBoost=bin/rk35/rk3576_boost_v1.03.bin
FlashData=bin/rk35/rk3576_ddr_v1.10.bin
FlashBoot=bin/rk35/rk3576_spl_v1.08.bin
[OUTPUT]
PATH=rk3576_spl_loader_v1.10.108.bin
IDB_PATH=rk3576_idblock_v1.10.108.img
[FLAG]
CREATE_IDB=true
[SYSTEM]
NEWIDB=true
"""


# --------------------------------------------------------------------------- #
# _extract_idb_path 纯函数
# --------------------------------------------------------------------------- #

def test_extract_idb_path_parses_output_section():
    b = RockchipBootloaderBuilder(docker=None, source=None)
    assert b._extract_idb_path(_INI) == "rk3576_idblock_v1.10.108.img"


def test_extract_idb_path_distinct_from_output_path():
    """[OUTPUT] 同含 PATH= 与 IDB_PATH=；两个解析器不得互相误匹配。"""
    b = RockchipBootloaderBuilder(docker=None, source=None)
    assert b._extract_idb_path(_INI) == "rk3576_idblock_v1.10.108.img"
    assert b._extract_output_path(_INI) == "rk3576_spl_loader_v1.10.108.bin"


def test_extract_idb_path_absent_returns_none():
    b = RockchipBootloaderBuilder(docker=None, source=None)
    ini = "[OUTPUT]\nPATH=only_loader.bin\n"
    assert b._extract_idb_path(ini) is None


# --------------------------------------------------------------------------- #
# compile() 分支
# --------------------------------------------------------------------------- #

def _make_firmware_dir(tmp_path: Path) -> Path:
    fw = tmp_path / "firmware"
    (fw / "RKBOOT").mkdir(parents=True)
    (fw / "RKTRUST").mkdir()
    (fw / "RKBOOT" / "RK3576MINIALL.ini").write_text(_INI)
    # compile 会先解析显式/兼容 trust INI 路径；具体 BL31 内容由测试 patch
    # _parse_trust_ini 注入，这里只提供真实路径以覆盖路径契约。
    (fw / "RKTRUST" / "RK3576TRUST.ini").write_text("[BL31_OPTION]\n")
    (fw / "bin" / "rk35").mkdir(parents=True)
    (fw / "bin" / "rk35" / "rk3576_bl31_v1.24.elf").write_bytes(b"\x7fELF-fake-bl31")
    (fw / "tools").mkdir()
    (fw / "tools" / "boot_merger").write_bytes(b"#!fake")
    # 模拟 boot_merger 已产出的 NEWIDB idblock
    (fw / "rk3576_idblock_v1.10.108.img").write_bytes(b"RKNS" + b"\x00" * 60)
    return fw


def _builder_with(tmp_path):
    fw = _make_firmware_dir(tmp_path)
    src = tmp_path / "uboot"
    (src / "tools").mkdir(parents=True)
    # 自编 SPL（make 产物）：boot_merger 模式把 ini FlashBoot 换成它（复刻官方）
    (src / "spl").mkdir(parents=True)
    (src / "spl" / "u-boot-spl.bin").write_bytes(b"SELFBUILT-SPL" + b"\x00" * 100)
    docker = MagicMock()
    source = MagicMock()
    source.ensure_firmware.return_value = fw
    b = RockchipBootloaderBuilder(docker=docker, source=source)
    return b, src, fw, docker


def _docker_calls_flat(docker):
    """把 docker.run 的所有调用参数拍平成一个字符串列表，便于断言。"""
    flat = []
    for call in docker.run.call_args_list:
        args = call.args[0] if call.args else call.kwargs.get("args", [])
        flat.append(" ".join(str(a) for a in args))
    return flat


def test_boot_merger_mode_skips_mkimage_and_copies_idblock(tmp_path):
    b, src, fw, docker = _builder_with(tmp_path)
    config = {
        "architecture": {
            "userspace": "aarch64", "kernel": "arm64", "bootloader": "arm",
        },
        "rkbin": {"ini_prefix": "RK3576", "trust_ini_prefix": "RK3576",
                  "mkimage_chip": "rk3576"},
        "bootloader": {"idbloader_method": "boot_merger",
                       "defconfig": ["rock-4d-spi-rk3576_defconfig"]},
        "jobs": 0,
    }
    with patch.object(b, "make"), patch.object(
        b, "_parse_trust_ini",
        return_value=(fw / "bin" / "rk35" / "rk3576_bl31_v1.24.elf", None)
    ):
        b.compile(src, config)

    calls = _docker_calls_flat(docker)
    # 不调用 mkimage -T rksd
    assert not any("rksd" in c for c in calls), calls
    # 调用 boot_merger
    assert any("boot_merger" in c for c in calls), calls
    # idblock 被拷为 idbloader.img（NEWIDB 内容）
    idb = src / "idbloader.img"
    assert idb.exists()
    assert idb.read_bytes().startswith(b"RKNS")
    # 不提前 return：末尾 _firmware_dir / _ini_prefix 赋值
    assert b._firmware_dir == fw
    assert b._ini_prefix == "RK3576"
    # boot_merger 用的副本 ini：FlashBoot 换成自编 SPL（修 SGRF/UFS DMA 根因），
    # boost/DDR 仍 rkbin（不动）
    run_ini = src / "RK3576MINIALL_selfspl.ini"
    assert run_ini.exists()
    ini_txt = run_ini.read_text()
    assert f"FlashBoot={src / 'spl' / 'u-boot-spl.bin'}" in ini_txt
    assert "FlashBoost=bin/rk35/rk3576_boost" in ini_txt


def test_boot_merger_mode_requires_selfbuilt_spl(tmp_path):
    """boot_merger 模式缺自编 SPL（spl/u-boot-spl.bin）须明确报错。"""
    b, src, fw, docker = _builder_with(tmp_path)
    (src / "spl" / "u-boot-spl.bin").unlink()  # 删掉自编 SPL
    config = {
        "architecture": {
            "userspace": "aarch64", "kernel": "arm64", "bootloader": "arm",
        },
        "rkbin": {"ini_prefix": "RK3576", "trust_ini_prefix": "RK3576",
                  "mkimage_chip": "rk3576"},
        "bootloader": {"idbloader_method": "boot_merger",
                       "defconfig": ["rock-4d-spi-rk3576_defconfig"]},
        "jobs": 0,
    }
    with patch.object(b, "make"), patch.object(
        b, "_parse_trust_ini",
        return_value=(fw / "bin" / "rk35" / "rk3576_bl31_v1.24.elf", None)
    ):
        with pytest.raises(FileNotFoundError, match="自编 SPL"):
            b.compile(src, config)


def test_boot_merger_mode_collect_does_not_raise(tmp_path):
    b, src, fw, docker = _builder_with(tmp_path)
    config = {
        "architecture": {
            "userspace": "aarch64", "kernel": "arm64", "bootloader": "arm",
        },
        "rkbin": {"ini_prefix": "RK3576", "trust_ini_prefix": "RK3576",
                  "mkimage_chip": "rk3576"},
        "bootloader": {"idbloader_method": "boot_merger",
                       "defconfig": ["rock-4d-spi-rk3576_defconfig"]},
        "jobs": 0,
    }
    with patch.object(b, "make"), patch.object(
        b, "_parse_trust_ini",
        return_value=(fw / "bin" / "rk35" / "rk3576_bl31_v1.24.elf", None)
    ):
        b.compile(src, config)
        result = b.collect(src, config)
    assert result["idbloader"] == src / "idbloader.img"
    assert result["bootloader"] == src / "u-boot.itb"
    assert "miniloader" in result


def test_default_mode_uses_mkimage(tmp_path):
    """其他 RK35xx（无 idbloader_method）仍走 mkimage -T rksd。"""
    b, src, fw, docker = _builder_with(tmp_path)
    config = {
        "architecture": {
            "userspace": "aarch64", "kernel": "arm64", "bootloader": "arm",
        },
        "rkbin": {"ini_prefix": "RK3576", "trust_ini_prefix": "RK3576",
                  "mkimage_chip": "rk3576"},
        "bootloader": {"defconfig": ["rk3576_defconfig"]},  # 无 idbloader_method
        "jobs": 0,
    }
    with patch.object(b, "make"), patch.object(
        b, "_parse_trust_ini",
        return_value=(fw / "bin" / "rk35" / "rk3576_bl31_v1.24.elf", None)
    ):
        b.compile(src, config)

    calls = _docker_calls_flat(docker)
    # 走 mkimage -T rksd
    assert any("rksd" in c for c in calls), calls
    # 未拷 boot_merger idblock（idbloader.img 由 mkimage 产，mock 下不实际生成）
    assert not (src / "idbloader.img").exists()
