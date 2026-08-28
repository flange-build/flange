"""全部 target 的 canonical 语义矩阵与平台代表路径。"""

import pytest

from builder.config.canonical import kernel_device_tree
from builder.config.query import get_valid_targets, parse_target
from builder.config.registry import discover_boards, resolve_config
from builder.kconfig import defconfig_targets, render_kconfig


FORBIDDEN_KEYS = {
    "arch", "repos", "repo", "from_repo", "local_repo", "repo_subdir",
    "enable_configs", "disable_configs", "dts", "dtb", "dts_dir",
    "dtb_overlays", "vendor_overlays", "board_overlays",
    "package_overlays", "default_overlays",
}


@pytest.fixture(scope="module")
def configs():
    boards = discover_boards()
    targets = get_valid_targets(boards)
    assert len(boards) == 18
    assert len(targets) == 90
    return {
        target: resolve_config(**{
            "board_name": parsed["board"],
            "product": parsed["product"],
            "variant": parsed["variant"],
            "boards": boards,
        })
        for target in targets
        for parsed in [parse_target(target, boards)]
    }


def _mapping_paths(value, path=""):
    if isinstance(value, dict):
        yield path, value
        for key, child in value.items():
            yield from _mapping_paths(child, f"{path}.{key}" if path else key)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _mapping_paths(child, f"{path}[{index}]")


def test_all_targets_are_canonical(configs):
    for target, config in configs.items():
        for path, mapping in _mapping_paths(config):
            assert not (FORBIDDEN_KEYS & mapping.keys()), (target, path)
            assert all(not key.startswith("+") and ":" not in key for key in mapping), (
                target, path,
            )

        for component in ("kernel", "bootloader"):
            component_config = config.get(component) or {}
            targets = defconfig_targets(
                component_config.get("defconfig", []), f"{component}.defconfig"
            )
            assert all("CONFIG_" not in item for item in targets), target
            render_kconfig(component_config.get("config"), f"{component}.config")

        sources = config["sources"]
        for component in (
            "kernel", "bootloader", "kernel_bsp", "kernel_device", "rkbin",
            "device-tree-overlay",
        ):
            ref = (config.get(component) or {}).get("source")
            if ref:
                assert ref["name"] in sources, (target, component)


PLATFORM_CASES = {
    "radxa-zero3w-default-release": {
        "platform": "rockchip",
        "tree": ("rockchip", "rk3566-radxa-zero-3w"),
        "source": ("rockchip-kernel", "branch", "linux-6.1-stan-rkr5.1"),
        "kconfig": "CONFIG_DRM_GUD=y",
        "bootloader_targets": ["rk3568_defconfig"],
        "download": ("rootfs", "sha256", "04207713ece899c3740823d33690441ad3a7f0ded1101aca744e2b0f37ac7ff2"),
    },
    "khadas-vim3l-default-release": {
        "platform": "amlogic",
        "tree": ("amlogic", "meson-sm1-khadas-vim3l"),
        "source": ("linux-s905d3", "branch", "v6.12"),
        "kconfig": "CONFIG_ANDROID_BINDER_IPC=y",
        "bootloader_targets": ["khadas-vim3l_defconfig", "flange_fastboot.config"],
        "download": ("rootfs", "sha256", "04207713ece899c3740823d33690441ad3a7f0ded1101aca744e2b0f37ac7ff2"),
    },
    "radxa-cubie-a7z-default-release": {
        "platform": "allwinnera733",
        "tree": ("allwinner", "sun60i-a733-cubie-a7z"),
        "source": ("linux-a733", "branch", "main"),
        "kconfig": "CONFIG_DRM_GUD=y",
        "bootloader_targets": [],
        "download": ("bootloader.toolchain", "sha256", "89e9bfc7ffe615f40a72c2492df0488f25fc20404e5f474501c8d55941337f71"),
    },
    "radxa-dragon-q6a-default-release": {
        "platform": "qualcommqcs6490",
        "tree": ("qcom", "qcs6490-radxa-dragon-q6a"),
        "source": ("linux-qcs6490", "commit", "7473a9fca2b08623319e497f4f811746baddb7bc"),
        "kconfig": "# CONFIG_MODULE_SIG_FORCE is not set",
        "bootloader_targets": [],
        "download": ("bootloader.edk2_firmware", "sha256", "cf23a1742ae5d51c451947d82cb21fd3f1c10bbcd621d611f55520673e3f90ca"),
    },
    "radxa-dragon-q8b-default-release": {
        "platform": "qualcommsc8280xp",
        "tree": ("qcom", "sc8280xp-radxa-dragon-q8b"),
        "source": ("linux-sc8280xp", "branch", "linux-7.0.11"),
        "kconfig": "# CONFIG_DRM_AMDGPU is not set",
        "bootloader_targets": [],
        "download": ("bootloader.edk2_firmware", "sha256", "f9bd55ac342bad53f056f620bdbf6e090ab1ef80c99cbf90ed685a64d7980fb8"),
    },
}


def _get(config, path):
    value = config
    for key in path.split("."):
        value = value[key]
    return value


@pytest.mark.parametrize("target", PLATFORM_CASES)
def test_platform_builder_inputs_match_canonical_config(configs, target):
    config = configs[target]
    expected = PLATFORM_CASES[target]
    source, revision_key, revision = expected["source"]
    download_path, download_key, download_value = expected["download"]

    assert config["platform"] == expected["platform"]
    assert kernel_device_tree(config) == expected["tree"]
    assert config["kernel"]["source"]["name"] == source
    assert config["sources"][source][revision_key] == revision
    assert expected["kconfig"] in render_kconfig(
        config["kernel"].get("config"), "kernel.config"
    )
    assert defconfig_targets(
        config["bootloader"].get("defconfig", []), "bootloader.defconfig"
    ) == expected["bootloader_targets"]
    assert _get(config, download_path)[download_key] == download_value
