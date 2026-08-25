"""Canonical Kconfig 公共语义测试。"""

import pytest

from builder.kconfig import defconfig_targets, render_kconfig


def test_defconfig_only_accepts_ordered_targets():
    assert defconfig_targets(
        ["base_defconfig", "vendor.config"], "kernel.defconfig"
    ) == ["base_defconfig", "vendor.config"]

    with pytest.raises(ValueError, match="config 对象"):
        defconfig_targets(
            ["base_defconfig", "CONFIG_NET=y"], "kernel.defconfig"
        )


def test_kernel_and_bootloader_share_symbol_renderer():
    values = {
        "CONFIG_ENABLED": "y",
        "CONFIG_MODULE": "m",
        "CONFIG_DISABLED": "n",
        "CONFIG_CMDLINE": '"console=ttyS0"',
    }
    expected = [
        'CONFIG_CMDLINE="console=ttyS0"',
        "# CONFIG_DISABLED is not set",
        "CONFIG_ENABLED=y",
        "CONFIG_MODULE=m",
    ]
    assert render_kconfig(values, "kernel.config") == expected
    assert render_kconfig(values, "bootloader.config") == expected


@pytest.mark.parametrize("value", [{"NET": "y"}, {"CONFIG_NET": "y\nBAD"}])
def test_renderer_rejects_invalid_symbol_or_value(value):
    with pytest.raises(ValueError):
        render_kconfig(value, "kernel.config")
