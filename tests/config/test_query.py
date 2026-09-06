"""config/query.py 的测试套件。

覆盖：
- get_valid_targets 目标枚举
- parse_target 目标解析（含连字符板名）
"""

import pytest

from builder.config.query import get_valid_targets, parse_target
from builder.config.registry import discover_boards


# ── get_valid_targets 测试 ───────────────────────────────────────


class TestGetValidTargets:
    """枚举所有 <board>-<product>-<variant> 目标。"""

    @pytest.fixture()
    def boards(self):
        return discover_boards()

    def test_returns_list(self, boards):
        targets = get_valid_targets(boards=boards)
        assert isinstance(targets, list)

    def test_expected_count(self, boards):
        """当前 19 个 board 的全部 product/variant 组合应完整枚举。"""
        targets = get_valid_targets(boards=boards)
        assert len(targets) == 94

    def test_contains_radxa_targets(self, boards):
        targets = get_valid_targets(boards=boards)
        assert "radxa-zero3w-default-debug" in targets
        assert "radxa-zero3w-default-release" in targets
        assert "radxa-zero3w-desktop-debug" in targets
        assert "radxa-zero3w-desktop-release" in targets

    def test_contains_khadas_vim3_targets(self, boards):
        targets = get_valid_targets(boards=boards)
        assert {
            "khadas-vim3-default-debug",
            "khadas-vim3-default-release",
            "khadas-vim3-desktop-debug",
            "khadas-vim3-desktop-release",
        } <= set(targets)

    def test_small_spinand_board_excludes_desktop(self, boards):
        targets = get_valid_targets(boards=boards)
        assert not any(
            target.startswith("atk-rk3506b-desktop-") for target in targets
        )

    def test_contains_neons_targets(self, boards):
        targets = get_valid_targets(boards=boards)
        assert "neons-core3566-nanob-default-debug" in targets
        assert "neons-core3566-nanob-default-release" in targets

    def test_contains_tspi_targets(self, boards):
        targets = get_valid_targets(boards=boards)
        assert "tspi-rk3566-default-debug" in targets
        assert "tspi-rk3566-default-release" in targets

    def test_contains_orangepi_targets(self, boards):
        targets = get_valid_targets(boards=boards)
        assert "orangepi-cm4-default-debug" in targets
        assert "orangepi-cm4-default-release" in targets
        assert "orangepi-cm4-amp-debug" in targets
        assert "orangepi-cm4-amp-release" in targets
        assert "orangepi-cm4-amp-rtt-debug" in targets
        assert "orangepi-cm4-amp-rtt-release" in targets

    def test_sorted_order(self, boards):
        """结果应按字母序排列。"""
        targets = get_valid_targets(boards=boards)
        assert targets == sorted(targets)


# ── parse_target 测试 ────────────────────────────────────────────


class TestParseTarget:
    """解析目标字符串，正确处理含连字符的板名。"""

    @pytest.fixture()
    def boards(self):
        return discover_boards()

    def test_parse_simple_board(self, boards):
        """解析单连字符板名（orangepi-cm4）。"""
        result = parse_target("orangepi-cm4-default-release", boards=boards)
        assert result == {
            "board": "orangepi-cm4",
            "product": "default",
            "variant": "release",
        }

    def test_parse_orangepi_amp_rtt(self, boards):
        """解析含连字符 product 的 Orange Pi CM4 AMP RT-Thread 目标。"""
        result = parse_target("orangepi-cm4-amp-rtt-release", boards=boards)
        assert result == {
            "board": "orangepi-cm4",
            "product": "amp-rtt",
            "variant": "release",
        }

    def test_parse_radxa(self, boards):
        """解析 radxa-zero3w 板名。"""
        result = parse_target("radxa-zero3w-default-debug", boards=boards)
        assert result == {
            "board": "radxa-zero3w",
            "product": "default",
            "variant": "debug",
        }

    def test_parse_neons_long_name(self, boards):
        """解析含多连字符的长板名（neons-core3566-nanob）。"""
        result = parse_target("neons-core3566-nanob-default-release", boards=boards)
        assert result == {
            "board": "neons-core3566-nanob",
            "product": "default",
            "variant": "release",
        }

    def test_parse_tspi(self, boards):
        """解析 tspi-rk3566 板名。"""
        result = parse_target("tspi-rk3566-default-debug", boards=boards)
        assert result == {
            "board": "tspi-rk3566",
            "product": "default",
            "variant": "debug",
        }

    def test_invalid_target_raises(self, boards):
        """无法匹配的目标应抛出 ValueError。"""
        with pytest.raises(ValueError):
            parse_target("nonexistent-board-default-release", boards=boards)

    def test_invalid_variant_raises(self, boards):
        """合法板名但非法 variant 应抛出 ValueError。"""
        with pytest.raises(ValueError):
            parse_target("radxa-zero3w-default-production", boards=boards)

    def test_roundtrip_all_targets(self, boards):
        """所有 get_valid_targets 的结果都应可被 parse_target 正确解析。"""
        targets = get_valid_targets(boards=boards)
        for target in targets:
            result = parse_target(target, boards=boards)
            assert "board" in result
            assert "product" in result
            assert "variant" in result
            # 验证反向拼接一致
            reconstructed = f"{result['board']}-{result['product']}-{result['variant']}"
            assert reconstructed == target
