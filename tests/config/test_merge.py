"""config/merge.py 的测试套件。

覆盖 deep_merge 和 resolve_conditions 的全部规则，包括：
- 标量覆盖、字典递归合并、列表覆盖
- +key 追加语义与条件标记
- 三层合并场景（platform → SoC → board）
- 条件解析（variant / product 匹配与丢弃）
"""

import copy

import pytest

from builder.config.merge import deep_merge, resolve_conditions


# ── deep_merge 测试 ──────────────────────────────────────────────


class TestDeepMergeScalar:
    """标量覆盖：override 中的标量值替换 base 中的同名键。"""

    def test_scalar_override(self):
        base = {"kernel": "5.10", "debug": False}
        override = {"kernel": "6.1", "debug": True}
        result = deep_merge(base, override)
        assert result == {"kernel": "6.1", "debug": True}


class TestDeepMergeDict:
    """字典递归合并。"""

    def test_dict_recursive_merge(self):
        base = {"kernel": {"version": "5.10", "config": "defconfig"}}
        override = {"kernel": {"version": "6.1", "modules": ["wifi"]}}
        result = deep_merge(base, override)
        assert result == {
            "kernel": {
                "version": "6.1",
                "config": "defconfig",
                "modules": ["wifi"],
            }
        }


class TestDeepMergeList:
    """列表覆盖（非追加）：override 的列表完全替换 base 的列表。"""

    def test_list_override_not_append(self):
        base = {"packages": ["systemd", "bash"]}
        override = {"packages": ["busybox"]}
        result = deep_merge(base, override)
        assert result == {"packages": ["busybox"]}


class TestDeepMergeAppend:
    """+key 追加语义。"""

    def test_append_to_existing_list(self):
        """base 有 key 时，+key 的值追加到 key 列表。"""
        base = {"packages": ["systemd", "bash"]}
        override = {"+packages": ["gdb", "strace"]}
        result = deep_merge(base, override)
        assert result == {"packages": ["systemd", "bash", "gdb", "strace"]}
        # +packages 不应残留在结果中
        assert "+packages" not in result

    def test_append_preserved_when_no_base_key(self):
        """base 无对应 key 时，+key 原样保留（留给下游处理）。"""
        base = {"kernel": "5.10"}
        override = {"+packages": ["gdb"]}
        result = deep_merge(base, override)
        assert result == {"kernel": "5.10", "+packages": ["gdb"]}

    def test_append_condition_same_key(self):
        """+key:condition 合并同名带条件键时追加。"""
        base = {"+packages:debug": ["valgrind"]}
        override = {"+packages:debug": ["gdb"]}
        result = deep_merge(base, override)
        assert result == {"+packages:debug": ["valgrind", "gdb"]}

    def test_append_chains_when_no_plain_base_key(self):
        """连续两层 +key 在 base 一直没 plain key 时也应追加而非覆盖。

        典型场景：platform 层 +packages: [A]，board 层 +packages: [B]，
        基础 rootfs 无 plain packages（由 package_set 动态展开）。两层
        +key 必须都到达 resolve_conditions 折叠阶段，否则后者会覆盖
        前者，违反 +key "追加而非替换" 的语义。
        """
        base = {"kernel": "5.10"}  # 无 packages，无 +packages
        platform = {"+packages": ["firmware-brcm80211"]}
        board = {"+packages": ["bluez"]}

        merged = deep_merge(base, platform)
        merged = deep_merge(merged, board)

        # 两层 +packages 都应在结果中，list 已拼接
        assert merged["+packages"] == ["firmware-brcm80211", "bluez"]
        # plain packages 不应被错误生成
        assert "packages" not in merged

    def test_append_chains_dict_form(self):
        """同上，但 +key 是 dict 形态时走 deep_merge。"""
        base = {"kernel": "5.10"}
        a = {"+config": {"opt_a": True}}
        b = {"+config": {"opt_b": False}}
        merged = deep_merge(deep_merge(base, a), b)
        assert merged["+config"] == {"opt_a": True, "opt_b": False}


class TestDeepMergePreservation:
    """base 中独有的键在合并后保留。"""

    def test_base_keys_preserved(self):
        base = {"arch": "arm64", "packages": ["systemd"]}
        override = {"kernel": "6.1"}
        result = deep_merge(base, override)
        assert result == {
            "arch": "arm64",
            "packages": ["systemd"],
            "kernel": "6.1",
        }


class TestDeepMergeThreeLayer:
    """模拟 platform → SoC → board 三层合并。"""

    def test_three_layer_merge(self):
        platform = {
            "arch": "arm64",
            "packages": ["systemd", "bash"],
            "kernel": {"version": "5.10"},
        }
        soc = {
            "soc": "rk3566",
            "+packages": ["firmware-rockchip"],
            "kernel": {"config": "rockchip_defconfig"},
        }
        board = {
            "board": "radxa-zero-3w",
            "+packages": ["wifi-tools"],
            "kernel": {"dts": "rk3566-radxa-zero-3w.dtb"},
        }

        merged = deep_merge(platform, soc)
        merged = deep_merge(merged, board)

        assert merged["arch"] == "arm64"
        assert merged["soc"] == "rk3566"
        assert merged["board"] == "radxa-zero-3w"
        # 两次 +packages 追加
        assert merged["packages"] == [
            "systemd",
            "bash",
            "firmware-rockchip",
            "wifi-tools",
        ]
        # kernel 递归合并
        assert merged["kernel"] == {
            "version": "5.10",
            "config": "rockchip_defconfig",
            "dts": "rk3566-radxa-zero-3w.dtb",
        }


class TestDeepMergeNestedAppend:
    """嵌套字典内的 +key 追加。"""

    def test_nested_dict_with_plus_key(self):
        base = {"rootfs": {"packages": ["systemd"], "locale": "en_US"}}
        override = {"rootfs": {"+packages": ["gdb"]}}
        result = deep_merge(base, override)
        assert result == {
            "rootfs": {
                "packages": ["systemd", "gdb"],
                "locale": "en_US",
            }
        }
        assert "+packages" not in result["rootfs"]


class TestDeepMergeImmutability:
    """deep_merge 不得修改输入字典。"""

    def test_does_not_mutate_inputs(self):
        base = {"packages": ["systemd"], "kernel": {"version": "5.10"}}
        override = {"+packages": ["gdb"], "kernel": {"config": "foo"}}
        base_copy = copy.deepcopy(base)
        override_copy = copy.deepcopy(override)

        deep_merge(base, override)

        assert base == base_copy
        assert override == override_copy


# ── resolve_conditions 测试 ──────────────────────────────────────


class TestResolveUnconditional:
    """无条件键原样保留。"""

    def test_unconditional_keys_preserved(self):
        config = {"arch": "arm64", "packages": ["systemd"]}
        result = resolve_conditions(config, product="generic", variant="release")
        assert result == {"arch": "arm64", "packages": ["systemd"]}


class TestResolveVariantOverride:
    """匹配的 variant 条件键覆盖同名无条件键。"""

    def test_matching_variant_override(self):
        config = {
            "packages": ["systemd"],
            "packages:debug": ["systemd", "gdb", "strace"],
        }
        result = resolve_conditions(config, product="generic", variant="debug")
        assert result == {"packages": ["systemd", "gdb", "strace"]}

    def test_non_matching_variant_discarded(self):
        config = {
            "packages": ["systemd"],
            "packages:debug": ["systemd", "gdb", "strace"],
        }
        result = resolve_conditions(config, product="generic", variant="release")
        assert result == {"packages": ["systemd"]}


class TestResolveAppendCondition:
    """带条件的 +key 追加。"""

    def test_matching_variant_append(self):
        config = {
            "packages": ["systemd"],
            "+packages:debug": ["gdb", "strace"],
        }
        result = resolve_conditions(config, product="generic", variant="debug")
        assert result == {"packages": ["systemd", "gdb", "strace"]}

    def test_matching_product_append(self):
        config = {
            "packages": ["systemd"],
            "+packages:smart-display": ["weston", "chromium"],
        }
        result = resolve_conditions(
            config, product="smart-display", variant="release"
        )
        assert result == {"packages": ["systemd", "weston", "chromium"]}

    def test_non_matching_product_discarded(self):
        config = {
            "packages": ["systemd"],
            "+packages:smart-display": ["weston"],
        }
        result = resolve_conditions(config, product="router", variant="release")
        assert result == {"packages": ["systemd"]}


class TestResolveMultipleConditions:
    """多条件同时生效。"""

    def test_multiple_conditions_apply(self):
        config = {
            "packages": ["systemd"],
            "+packages:debug": ["gdb"],
            "+packages:smart-display": ["weston"],
        }
        result = resolve_conditions(
            config, product="smart-display", variant="debug"
        )
        assert "gdb" in result["packages"]
        assert "weston" in result["packages"]
        assert "systemd" in result["packages"]


class TestResolveNestedConditions:
    """嵌套字典中的条件解析。"""

    def test_nested_dict_conditions(self):
        config = {
            "rootfs": {
                "packages": ["systemd"],
                "+packages:debug": ["gdb"],
            }
        }
        result = resolve_conditions(config, product="generic", variant="debug")
        assert result == {"rootfs": {"packages": ["systemd", "gdb"]}}


class TestResolveConditionalOverride:
    """带条件的普通键（无 + 前缀）覆盖同名无条件键。"""

    def test_conditional_override_replaces(self):
        config = {
            "partitions": ["boot", "rootfs"],
            "partitions:smart-display": ["boot", "rootfs", "data", "media"],
        }
        result = resolve_conditions(
            config, product="smart-display", variant="release"
        )
        assert result == {
            "partitions": ["boot", "rootfs", "data", "media"],
        }


class TestResolveUnconditionalAppend:
    """无条件 +key 追加（无 :condition 后缀）。"""

    def test_unconditional_append(self):
        config = {
            "packages": ["systemd"],
            "+packages": ["bash"],
        }
        result = resolve_conditions(config, product="generic", variant="release")
        assert result == {"packages": ["systemd", "bash"]}


class TestResolveFullScenario:
    """完整三层场景集成测试。

    模拟 platform → SoC → board 合并后，再做条件解析。
    """

    def test_full_three_layer_scenario(self):
        # 第一层：platform（通用 arm64）
        platform = {
            "arch": "arm64",
            "packages": ["systemd", "bash"],
            "rootfs": {"locale": "en_US", "packages": ["base-files"]},
        }
        # 第二层：SoC
        soc = {
            "soc": "rk3566",
            "+packages": ["firmware-rockchip"],
            "rootfs": {"+packages": ["linux-firmware"]},
        }
        # 第三层：board
        board = {
            "board": "radxa-zero-3w",
            "+packages": ["wifi-tools"],
            "+packages:debug": ["gdb", "strace"],
            "+packages:smart-display": ["weston"],
            "rootfs": {
                "+packages": ["networkmanager"],
                "+packages:debug": ["valgrind"],
            },
        }

        # 合并三层
        merged = deep_merge(platform, soc)
        merged = deep_merge(merged, board)

        # 场景 1：debug variant
        debug_result = resolve_conditions(merged, product="generic", variant="debug")
        assert debug_result["arch"] == "arm64"
        assert debug_result["soc"] == "rk3566"
        assert debug_result["board"] == "radxa-zero-3w"
        # packages: 基础 + soc追加 + board追加 + debug追加
        assert "systemd" in debug_result["packages"]
        assert "firmware-rockchip" in debug_result["packages"]
        assert "wifi-tools" in debug_result["packages"]
        assert "gdb" in debug_result["packages"]
        assert "strace" in debug_result["packages"]
        # smart-display 条件不匹配，不含 weston
        assert "weston" not in debug_result["packages"]
        # rootfs 嵌套
        assert "base-files" in debug_result["rootfs"]["packages"]
        assert "linux-firmware" in debug_result["rootfs"]["packages"]
        assert "networkmanager" in debug_result["rootfs"]["packages"]
        assert "valgrind" in debug_result["rootfs"]["packages"]

        # 场景 2：smart-display product, release variant
        display_result = resolve_conditions(
            merged, product="smart-display", variant="release"
        )
        assert "weston" in display_result["packages"]
        assert "gdb" not in display_result["packages"]
        assert "valgrind" not in display_result["rootfs"]["packages"]
