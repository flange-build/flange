"""flash.sh 生成测试。"""

import tempfile
from pathlib import Path
from builder.flash import FlashGenerator


class TestFlashGenerator:
    def test_generates_executable_script(self):
        config = {
            "board": "radxa-zero3w",
            "product": "default",
            "variant": "release",
            "flash_tool": "upgrade_tool",
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            gen = FlashGenerator()
            gen.generate(config, Path(tmpdir))
            flash_sh = Path(tmpdir) / "flash.sh"
            assert flash_sh.exists()
            assert flash_sh.stat().st_mode & 0o111  # 可执行

    def test_contains_board_info(self):
        config = {
            "board": "radxa-zero3w",
            "product": "smart-display",
            "variant": "debug",
            "flash_tool": "upgrade_tool",
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            gen = FlashGenerator()
            gen.generate(config, Path(tmpdir))
            content = (Path(tmpdir) / "flash.sh").read_text()
            assert "radxa-zero3w" in content
            assert "smart-display" in content
            assert "debug" in content

    def test_uses_config_flash_tool(self):
        config = {
            "board": "test",
            "product": "default",
            "variant": "release",
            "flash_tool": "qdl",
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            gen = FlashGenerator()
            gen.generate(config, Path(tmpdir))
            content = (Path(tmpdir) / "flash.sh").read_text()
            assert 'FLASH_TOOL="qdl"' in content

    def test_contains_all_flash_functions(self):
        config = {
            "board": "test",
            "product": "default",
            "variant": "release",
            "flash_tool": "upgrade_tool",
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            gen = FlashGenerator()
            gen.generate(config, Path(tmpdir))
            content = (Path(tmpdir) / "flash.sh").read_text()
            assert "flash_bootloader()" in content
            assert "flash_kernel()" in content
            assert "flash_rootfs()" in content
            assert "flash_all()" in content
