"""SourceManager.ensure_extra_deb / ensure_extra_firmware 单元测试。

extra_deb 覆盖三条主要路径：
  1. 缓存命中（本地已存在且 sha256 匹配）
  2. 首次下载（wget → 校验 → rename）
  3. sha256 校验失败（清理 partial 并抛异常）

extra_firmware 覆盖 source='local' 分支（其他 source 类型走仓库/复用，
单独验证意义不大；'local' 涉及 board 目录解析与错误路径，重点覆盖）。
"""

import hashlib
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from builder.source import SourceManager


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def manager(tmp_path: Path) -> SourceManager:
    return SourceManager(sources_dir=tmp_path / "sources")


def _make_wget_writer(content: bytes):
    """构造一个伪 wget：把 content 写入 -O 指定的文件。"""

    def fake_run(cmd, **kwargs):
        # cmd: ["wget", "-q", "--show-progress", "-O", <partial>, <url>]
        out_idx = cmd.index("-O") + 1
        Path(cmd[out_idx]).write_bytes(content)

        class _R:
            returncode = 0

        return _R()

    return fake_run


class TestEnsureExtraDeb:
    def test_命中本地缓存时不下载(self, manager: SourceManager):
        """本地 deb 已存在且 sha256 匹配时，不应触发 wget。"""
        content = b"already cached deb"
        cfg = {
            "url": "https://example.com/foo_1.0_arm64.deb",
            "sha256": _sha256(content),
        }
        # 预先放好缓存文件
        deb_path = manager.sources_dir / "extra-debs" / "foo" / "foo_1.0_arm64.deb"
        deb_path.parent.mkdir(parents=True)
        deb_path.write_bytes(content)

        with patch("builder.source.subprocess.run") as mock_run:
            result = manager.ensure_extra_deb("foo", cfg)

        mock_run.assert_not_called()
        assert result == deb_path

    def test_首次下载校验通过后落地(self, manager: SourceManager):
        """首次下载：wget 写 .download → sha256 通过 → rename 到目标。"""
        content = b"freshly downloaded deb"
        cfg = {
            "url": "https://example.com/bar_2.0_arm64.deb",
            "sha256": _sha256(content),
        }

        with patch(
            "builder.source.subprocess.run",
            side_effect=_make_wget_writer(content),
        ):
            result = manager.ensure_extra_deb("bar", cfg)

        assert result.read_bytes() == content
        assert result.name == "bar_2.0_arm64.deb"
        # .download 临时文件不应残留
        assert not result.with_suffix(result.suffix + ".download").exists()

    def test_sha256不匹配时清理并抛异常(self, manager: SourceManager):
        """下载的内容与声明的 sha256 不符时，应删除 partial 并抛 RuntimeError。"""
        cfg = {
            "url": "https://example.com/bad_3.0_arm64.deb",
            "sha256": _sha256(b"expected content"),
        }

        with patch(
            "builder.source.subprocess.run",
            side_effect=_make_wget_writer(b"tampered content"),
        ):
            with pytest.raises(RuntimeError, match="sha256 校验失败"):
                manager.ensure_extra_deb("bad", cfg)

        deb_dir = manager.sources_dir / "extra-debs" / "bad"
        # 目标文件不应存在；.download 残留也应被清理
        assert list(deb_dir.iterdir()) == []

    def test_自定义filename覆盖URL基名(self, manager: SourceManager):
        """cfg.filename 指定时，本地文件名以 cfg.filename 为准。"""
        content = b"renamed deb"
        cfg = {
            "url": "https://cdn.example.com/some-cdn-key/abc123",
            "sha256": _sha256(content),
            "filename": "real-name_4.0_arm64.deb",
        }

        with patch(
            "builder.source.subprocess.run",
            side_effect=_make_wget_writer(content),
        ):
            result = manager.ensure_extra_deb("renamed", cfg)

        assert result.name == "real-name_4.0_arm64.deb"

    def test_wget失败时清理partial(self, manager: SourceManager):
        """wget 进程失败时，应清理残留的 .download 文件。"""
        cfg = {
            "url": "https://example.com/will-fail.deb",
            "sha256": _sha256(b"anything"),
        }

        def fake_run(cmd, **kwargs):
            out_idx = cmd.index("-O") + 1
            # 模拟 wget 写了一半就失败
            Path(cmd[out_idx]).write_bytes(b"partial junk")
            raise subprocess.CalledProcessError(1, cmd)

        with patch("builder.source.subprocess.run", side_effect=fake_run):
            with pytest.raises(subprocess.CalledProcessError):
                manager.ensure_extra_deb("flaky", cfg)

        deb_dir = manager.sources_dir / "extra-debs" / "flaky"
        assert list(deb_dir.iterdir()) == []


class TestEnsureExtraFirmwareLocal:
    """ensure_extra_firmware(source='local')：解析 components/board/<board>/
    <src_dir>，返回该目录。零网络、零 clone；只做路径解析与存在性校验。"""

    @pytest.fixture
    def fake_board_tree(self, tmp_path: Path):
        """构造一个最小的板目录：components/board/fake-board/firmware/touch/。"""
        board_root = tmp_path / "components" / "board" / "fake-board"
        fw_dir = board_root / "firmware" / "touch"
        fw_dir.mkdir(parents=True)
        (fw_dir / "blob.bin").write_bytes(b"\x01\x02\x03")
        return tmp_path

    def test_返回板内_src_dir_路径(self, fake_board_tree: Path):
        manager = SourceManager(
            sources_dir=fake_board_tree / ".build/sources",
            project_root=fake_board_tree,
        )
        cfg = {
            "name": "fake-fw",
            "source": "local",
            "src_dir": "firmware/touch",
            "files": ["blob.bin"],
            "dest": "lib/firmware",
        }
        config = {"board": "fake-board"}
        fw_dir = manager.ensure_extra_firmware("fake-fw", cfg, config=config)
        assert fw_dir == (fake_board_tree / "components/board/fake-board"
                          / "firmware/touch").resolve()
        assert (fw_dir / "blob.bin").read_bytes() == b"\x01\x02\x03"

    def test_缺_src_dir_抛异常(self, fake_board_tree: Path):
        manager = SourceManager(
            sources_dir=fake_board_tree / ".build/sources",
            project_root=fake_board_tree,
        )
        cfg = {"source": "local", "files": ["x"], "dest": "y"}
        with pytest.raises(ValueError, match="src_dir"):
            manager.ensure_extra_firmware(
                "no-src-dir", cfg, config={"board": "fake-board"})

    def test_缺_config_board_抛异常(self, fake_board_tree: Path):
        manager = SourceManager(
            sources_dir=fake_board_tree / ".build/sources",
            project_root=fake_board_tree,
        )
        cfg = {"source": "local", "src_dir": "firmware/touch"}
        # config=None
        with pytest.raises(ValueError, match="board"):
            manager.ensure_extra_firmware("no-cfg", cfg)
        # config 缺 board
        with pytest.raises(ValueError, match="board"):
            manager.ensure_extra_firmware("no-board", cfg, config={})

    def test_src_dir_目录不存在抛(self, fake_board_tree: Path):
        manager = SourceManager(
            sources_dir=fake_board_tree / ".build/sources",
            project_root=fake_board_tree,
        )
        cfg = {"source": "local", "src_dir": "firmware/nonexistent"}
        with pytest.raises(FileNotFoundError):
            manager.ensure_extra_firmware(
                "missing", cfg, config={"board": "fake-board"})

    def test_不支持的_source_类型抛(self, fake_board_tree: Path):
        manager = SourceManager(
            sources_dir=fake_board_tree / ".build/sources",
            project_root=fake_board_tree,
        )
        cfg = {"source": "ftp", "src_dir": "firmware/touch"}
        with pytest.raises(ValueError, match="不支持的 source 类型"):
            manager.ensure_extra_firmware(
                "weird", cfg, config={"board": "fake-board"})
