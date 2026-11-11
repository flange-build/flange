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

    def test_enumeration_is_complete_and_consistent(self, boards):
        """枚举覆盖每块板的全部 product × variant 组合，并与解析结果一致。"""
        from itertools import product

        targets = get_valid_targets(boards=boards)
        assert targets
        assert len(targets) == len(set(targets))
        assert targets == sorted(targets)
        expected = {
            (name, product_name, variant)
            for name, config in boards.items()
            for product_name, variant in product(config["products"], config["variants"])
        }
        actual = set()
        for target in targets:
            parsed = parse_target(target, boards)
            identity = (parsed["board"], parsed["product"], parsed["variant"])
            assert "-".join(identity) == target
            actual.add(identity)
        assert actual == expected

    def test_small_spinand_board_excludes_desktop(self, boards):
        targets = get_valid_targets(boards=boards)
        assert not any(
            target.startswith("atk-rk3506b-desktop-") for target in targets
        )


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
