"""Rockchip bootloader: mkimage chip 标签可配置（rkbin.mkimage_chip）。

覆盖场景：
1. SoC config 缺失 mkimage_chip 时抛出含字段名的明确错误
2. 现网 SoC 配置的 mkimage_chip 字段已就位（rk3566 / rk3588 / rk3588s）
"""

from __future__ import annotations

from pathlib import Path

import pytest

from builder.config.registry import _load_soc_config
from builder.platforms.rockchip.bootloader import RockchipBootloaderBuilder


def test_compile_missing_mkimage_chip_raises_with_field_name(tmp_path):
    """SoC config 不带 rkbin.mkimage_chip 时，compile() 必须报含字段名的 KeyError。"""
    builder = RockchipBootloaderBuilder(docker=None, source=None)
    config = {
        "architecture": {
            "userspace": "aarch64", "kernel": "arm64", "bootloader": "arm",
        },
        "rkbin": {
            "ini_prefix": "RK3566",
            "trust_ini_prefix": "RK3568",
            # 故意不写 mkimage_chip
        },
    }

    with pytest.raises(KeyError, match="rkbin.mkimage_chip"):
        builder.compile(tmp_path, config)


def test_rk3566_soc_config_declares_mkimage_chip():
    """rk3566 SoC config 必须声明 mkimage_chip='rk3568'（同 die）。"""
    soc = _load_soc_config("rk3566")
    assert soc["rkbin"]["mkimage_chip"] == "rk3568"


def test_rk3588_soc_config_declares_mkimage_chip():
    """rk3588 SoC config 必须声明 mkimage_chip='rk3588'。"""
    soc = _load_soc_config("rk3588")
    assert soc["rkbin"]["mkimage_chip"] == "rk3588"


def test_rk3588s_soc_config_declares_mkimage_chip():
    """rk3588s SoC config 必须声明 mkimage_chip='rk3588'（与 rk3588 同 die）。"""
    soc = _load_soc_config("rk3588s")
    assert soc["rkbin"]["mkimage_chip"] == "rk3588"
