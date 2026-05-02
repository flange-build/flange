"""config/registry.py 的测试套件。

覆盖：
- discover_boards 板级扫描
- get_board_config 三层合并（platform -> SoC -> board）
- resolve_config 完整条件解析（product/variant）
"""

import pytest

from builder.config.registry import discover_boards, get_board_config, resolve_config


# ── 所有已知板子 ──────────────────────────────────────────────────

ALL_BOARDS = [
    "radxa-zero3w",
    "neons-core3566-nanob",
    "tspi-rk3566",
    "orangepi-cm4",
]


# ── discover_boards 测试 ─────────────────────────────────────────


class TestDiscoverBoards:
    """扫描 board/*/config.py 发现板子。"""

    def test_discovers_all_four_boards(self):
        boards = discover_boards()
        for name in ALL_BOARDS:
            assert name in boards, f"应发现板子 {name}"

    def test_board_has_required_keys(self):
        boards = discover_boards()
        for name in ALL_BOARDS:
            cfg = boards[name]
            assert cfg["board"] == name
            assert "soc" in cfg
            assert "platform" in cfg
            assert "products" in cfg
            assert "variants" in cfg


# ── get_board_config 测试 ────────────────────────────────────────


class TestGetBoardConfig:
    """三层合并：platform -> SoC -> board。"""

    @pytest.fixture()
    def boards(self):
        return discover_boards()

    @pytest.mark.parametrize("board_name", ALL_BOARDS)
    def test_merged_has_platform_fields(self, boards, board_name):
        """合并后应包含平台层字段。"""
        merged = get_board_config(board_name, boards=boards)
        assert merged["vendor"] == "rockchip"
        assert merged["flash_tool"] == "upgrade_tool"
        assert merged["arch"] == "aarch64"

    @pytest.mark.parametrize("board_name", ALL_BOARDS)
    def test_merged_has_soc_fields(self, boards, board_name):
        """合并后应包含 SoC 层字段。"""
        merged = get_board_config(board_name, boards=boards)
        assert merged["soc"] == "rk3566"
        assert "partitions" in merged
        assert merged["partitions"]["format"] == "gpt"

    @pytest.mark.parametrize("board_name", ALL_BOARDS)
    def test_merged_has_board_fields(self, boards, board_name):
        """合并后应包含板级字段。"""
        merged = get_board_config(board_name, boards=boards)
        assert merged["board"] == board_name
        assert "kernel" in merged
        assert "bootloader" in merged
        assert "boot" in merged

    def test_radxa_kernel_dts(self, boards):
        """radxa-zero3w 的 kernel.dts 应正确。"""
        merged = get_board_config("radxa-zero3w", boards=boards)
        assert merged["kernel"]["dts"] == "rk3566-radxa-zero-3w"

    def test_neons_kernel_commit(self, boards):
        """neons-core3566-nanob 应有非空 kernel commit。"""
        merged = get_board_config("neons-core3566-nanob", boards=boards)
        assert merged["kernel"]["commit"] == "e62b45adc7f89f5c8ea1918960b8c78e7c97ebf5"

    def test_tspi_bootloader_commit(self, boards):
        """tspi-rk3566 应有非空 bootloader commit。"""
        merged = get_board_config("tspi-rk3566", boards=boards)
        assert merged["bootloader"]["commit"] == "3c60a711e61015c1a61247837afbeaa85bd7fbf2"

    def test_orangepi_empty_commits(self, boards):
        """orangepi-cm4 的 kernel/bootloader commit 应为空。"""
        merged = get_board_config("orangepi-cm4", boards=boards)
        assert merged["kernel"]["commit"] == ""
        assert merged["bootloader"]["commit"] == ""

    def test_kernel_merges_soc_defconfig(self, boards):
        """板级 kernel 应继承 SoC 的 defconfig。"""
        merged = get_board_config("radxa-zero3w", boards=boards)
        assert merged["kernel"]["defconfig"] == "rockchip_linux_defconfig"

    def test_bootloader_merges_soc_defconfig(self, boards):
        """板级 bootloader 应继承 SoC 的 defconfig。"""
        merged = get_board_config("radxa-zero3w", boards=boards)
        assert merged["bootloader"]["defconfig"] == "rk3568_defconfig"

    def test_rootfs_inherits_platform_packages(self, boards):
        """板级 rootfs 应继承平台层的 packages 列表。"""
        merged = get_board_config("radxa-zero3w", boards=boards)
        assert "systemd" in merged["rootfs"]["packages"]
        assert "bash" in merged["rootfs"]["packages"]

    def test_rootfs_has_board_custom_packages(self, boards):
        """板级 rootfs 应包含板级自定义包。

        平台层默认 custom_packages 包含 adbd 与 recoveryctl（recoveryctl 用于
        normal 模式下 ADB 触发 reboot 切换到 recovery），以及首次启动扩容
        App。
        """
        merged = get_board_config("radxa-zero3w", boards=boards)
        assert merged["rootfs"]["custom_packages"] == [
            "adbd", "recoveryctl", "flange-rootfs-grow"]

    def test_rootfs_has_grow_dependencies(self, boards):
        """normal rootfs 应包含首次启动扩容 App 的运行期依赖。"""
        merged = get_board_config("radxa-zero3w", boards=boards)
        packages = set(merged["rootfs"]["packages"])
        assert {"cloud-guest-utils", "gdisk", "e2fsprogs", "util-linux"} <= packages

    def test_rkbin_merges_platform_and_soc(self, boards):
        """rkbin 应合并平台层 repo/branch 和 SoC 层 ini_prefix。"""
        merged = get_board_config("radxa-zero3w", boards=boards)
        assert merged["rkbin"]["repo"] == "https://github.com/radxa/rkbin"
        assert merged["rkbin"]["branch"] == "develop-v2024.10"
        assert merged["rkbin"]["ini_prefix"] == "RK3566"

    def test_unknown_board_raises(self, boards):
        """查询不存在的板子应抛出 KeyError。"""
        with pytest.raises(KeyError):
            get_board_config("nonexistent-board", boards=boards)


# ── resolve_config 测试 ──────────────────────────────────────────


class TestResolveConfig:
    """完整配置解析：三层合并 + 条件展开。"""

    @pytest.fixture()
    def boards(self):
        return discover_boards()

    @pytest.mark.parametrize("board_name", ALL_BOARDS)
    def test_resolve_release(self, boards, board_name):
        """release 变体不应包含 debug 包。"""
        resolved = resolve_config(
            board_name, product="default", variant="release", boards=boards
        )
        # release 模式不应有 debug 工具
        rootfs_pkgs = resolved.get("rootfs", {}).get("packages", [])
        assert "gdb" not in rootfs_pkgs
        assert "valgrind" not in rootfs_pkgs

    @pytest.mark.parametrize("board_name", ALL_BOARDS)
    def test_resolve_debug(self, boards, board_name):
        """debug 变体应追加调试工具包。"""
        resolved = resolve_config(
            board_name, product="default", variant="debug", boards=boards
        )
        rootfs_pkgs = resolved.get("rootfs", {}).get("packages", [])
        assert "gdb" in rootfs_pkgs
        assert "strace" in rootfs_pkgs
        assert "tcpdump" in rootfs_pkgs
        assert "valgrind" in rootfs_pkgs

    @pytest.mark.parametrize("board_name", ALL_BOARDS)
    def test_resolve_preserves_core_fields(self, boards, board_name):
        """条件解析后核心字段不丢失。"""
        resolved = resolve_config(
            board_name, product="default", variant="release", boards=boards
        )
        assert resolved["board"] == board_name
        assert resolved["vendor"] == "rockchip"
        assert resolved["soc"] == "rk3566"
        assert "partitions" in resolved

    def test_resolve_debug_has_base_packages_too(self, boards):
        """debug 变体也应包含基础 rootfs 包。"""
        resolved = resolve_config(
            "radxa-zero3w", product="default", variant="debug", boards=boards
        )
        rootfs_pkgs = resolved["rootfs"]["packages"]
        # 基础包仍然在
        assert "systemd" in rootfs_pkgs
        assert "openssh-server" in rootfs_pkgs

    def test_rootfs_common_packages_are_platform_independent(self):
        """rootfs 公共包应同时进入 Rockchip 与 A733 的最终配置。"""
        configs = [
            resolve_config("radxa-zero3w", product="default", variant="release"),
            resolve_config("radxa-cubie-a7z", product="default", variant="release"),
            resolve_config("tspi-rk3566", product="default", variant="release"),
        ]

        for resolved in configs:
            rootfs_pkgs = set(resolved["rootfs"]["packages"])
            assert {
                "systemd", "systemd-sysv", "dbus", "network-manager",
                "iputils-ping", "iproute2", "openssh-server", "sudo",
                "bash", "ca-certificates", "locales",
                "cloud-guest-utils", "gdisk", "e2fsprogs", "util-linux",
                "python3", "kmod", "wpasupplicant", "usbutils",
                "net-tools", "systemd-timesyncd", "btop",
            } <= rootfs_pkgs

    def test_rootfs_package_sets_select_variant_packages(self):
        """rootfs 应按 variant 选择不同包集合。"""
        release_cfg = resolve_config(
            "radxa-zero3w", product="default", variant="release"
        )
        debug_cfg = resolve_config(
            "radxa-zero3w", product="default", variant="debug"
        )

        release_pkgs = set(release_cfg["rootfs"]["packages"])
        debug_pkgs = set(debug_cfg["rootfs"]["packages"])

        assert "release" in release_cfg["rootfs"]["package_set"]
        assert "debug" in debug_cfg["rootfs"]["package_set"]
        assert {"gdb", "strace", "tcpdump", "valgrind"}.isdisjoint(
            release_pkgs
        )
        assert {"gdb", "strace", "tcpdump", "valgrind"} <= debug_pkgs

    def test_rootfs_packages_are_deduplicated(self):
        """公共包上移后，板级追加不应造成重复安装参数。"""
        resolved = resolve_config(
            "tspi-rk3566", product="default", variant="release"
        )
        packages = resolved["rootfs"]["packages"]

        assert len(packages) == len(set(packages))
