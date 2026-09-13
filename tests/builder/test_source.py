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


class TestCanonicalSources:
    def test_local与remote互斥(self, manager: SourceManager):
        config = {
            "kernel": {"source": {"name": "linux"}},
            "sources": {
                "linux": {
                    "local_path": "/tmp/linux",
                    "url": "https://example.com/linux.git",
                },
            },
        }

        with patch.object(manager, "_ensure_repo") as ensure_repo, \
                pytest.raises(ValueError, match="必须且只能"):
            manager.ensure("kernel", config)

        ensure_repo.assert_not_called()

    def test多个组件共享同一checkout(self, manager: SourceManager):
        config = {
            "sources": {
                "vendor": {
                    "url": "https://example.com/vendor.git",
                    "commit": "abc",
                },
            },
            "kernel": {"source": {"name": "vendor", "subpath": "kernel"}},
            "bootloader": {
                "source": {"name": "vendor", "subpath": "u-boot"},
            },
        }

        with patch.object(manager, "_ensure_repo") as ensure_repo:
            kernel = manager.ensure("kernel", config)
            bootloader = manager.ensure("bootloader", config)

        assert kernel.parent == bootloader.parent
        assert kernel.name == "kernel"
        assert bootloader.name == "u-boot"
        assert {call.args[0] for call in ensure_repo.call_args_list} == {
            kernel.parent,
        }

    def testrevision变化隔离工作树(self, manager: SourceManager):
        config = {
            "sources": {
                "linux": {
                    "url": "https://example.com/linux.git",
                    "commit": "commit-a",
                },
            },
            "kernel": {"source": {"name": "linux"}},
        }

        with patch.object(manager, "_ensure_repo"):
            first = manager.ensure("kernel", config)
            config["sources"]["linux"]["commit"] = "commit-b"
            second = manager.ensure("kernel", config)

        assert first != second
        assert first.parent == second.parent

    def testlocal_source追加subpath且不clone(
            self, manager: SourceManager, tmp_path: Path):
        config = {
            "sources": {"linux": {"local_path": str(tmp_path / "vendor")}},
            "kernel": {"source": {"name": "linux", "subpath": "src"}},
        }

        with patch.object(manager, "_ensure_repo") as ensure_repo:
            result = manager.ensure("kernel", config)

        assert result == tmp_path / "vendor" / "src"
        ensure_repo.assert_not_called()

    def test_source_path只解析远端路径不同步(self, manager: SourceManager):
        config = {
            "sources": {
                "linux": {
                    "url": "https://example.com/linux.git",
                    "commit": "abc",
                },
            },
            "kernel": {"source": {"name": "linux", "subpath": "src"}},
        }

        with patch.object(manager, "_ensure_repo") as ensure_repo:
            result = manager.source_path("kernel", config)

        expected = (
            manager.sources_dir / "repos"
            / manager.source_identity(config["sources"]["linux"])
            / "src"
        )
        assert result == expected
        ensure_repo.assert_not_called()

    def testoot与固件复用canonical_source(self, manager: SourceManager):
        config = {
            "sources": {
                "vendor": {
                    "url": "https://example.com/vendor.git",
                    "commit": "abc",
                },
            },
        }

        with patch.object(manager, "_ensure_repo") as ensure_repo:
            oot = manager.ensure_oot_source(
                "wifi", {"source": {"name": "vendor", "subpath": "driver"}},
                config=config,
            )
            firmware = manager.ensure_extra_firmware(
                "wifi-fw",
                {"source": {"name": "vendor", "subpath": "firmware"}},
                config=config,
            )

        assert oot.parent == firmware.parent
        assert oot.name == "driver"
        assert firmware.name == "firmware"
        assert {call.args[0] for call in ensure_repo.call_args_list} == {
            oot.parent,
        }


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
        deb_path = (
            manager.sources_dir / "downloads" / "extra-debs"
            / cfg["sha256"] / "foo_1.0_arm64.deb"
        )
        deb_path.parent.mkdir(parents=True)
        deb_path.write_bytes(content)
        # 模拟旧版本以 mkstemp 默认 0600 落盘的缓存
        deb_path.chmod(0o600)

        with patch("builder.source.subprocess.run") as mock_run:
            result = manager.ensure_extra_deb("foo", cfg)

        mock_run.assert_not_called()
        assert result == deb_path
        # 命中缓存时应顺手放宽权限，否则宿主机非 root 用户读不到
        assert result.stat().st_mode & 0o777 == 0o644

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
        # 容器内以 root 落盘，必须对宿主机非 root 用户可读（mkstemp 默认 0600）
        assert result.stat().st_mode & 0o777 == 0o644
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

        deb_dir = (
            manager.sources_dir / "downloads" / "extra-debs" / cfg["sha256"]
        )
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

        deb_dir = (
            manager.sources_dir / "downloads" / "extra-debs" / cfg["sha256"]
        )
        assert list(deb_dir.iterdir()) == []


class TestEnsureRootfsTarball:
    def test_下载通过摘要后原子落地(self, manager: SourceManager):
        content = b"ubuntu-base"
        config = {
            "rootfs": {
                "url": "https://example.com/ubuntu-base.tar.gz",
                "sha256": _sha256(content),
            }
        }

        with patch(
            "builder.source.subprocess.run",
            side_effect=_make_wget_writer(content),
        ):
            result = manager.ensure_rootfs_tarball(config)

        assert result.read_bytes() == content
        assert not result.with_suffix(result.suffix + ".download").exists()

    def test_摘要不匹配时拒绝并清理临时文件(self, manager: SourceManager):
        config = {
            "rootfs": {
                "url": "https://example.com/ubuntu-base.tar.gz",
                "sha256": _sha256(b"expected"),
            }
        }

        with patch(
            "builder.source.subprocess.run",
            side_effect=_make_wget_writer(b"tampered"),
        ):
            with pytest.raises(RuntimeError, match="sha256 校验失败"):
                manager.ensure_rootfs_tarball(config)

        cache = (
            manager.sources_dir / "downloads" / "rootfs"
            / config["rootfs"]["sha256"]
        )
        assert not any(cache.iterdir())

    def test_缺少可信摘要时拒绝下载(self, manager: SourceManager):
        config = {
            "rootfs": {"url": "https://example.com/ubuntu-base.tar.gz"}
        }

        with patch("builder.source.subprocess.run") as run:
            with pytest.raises(ValueError, match="rootfs.sha256"):
                manager.ensure_rootfs_tarball(config)

        run.assert_not_called()


class TestEnsureExtraFirmwareLocal:
    """额外 firmware 通过统一 source 引用本地目录。"""

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
        cfg = {"source": {"name": "fake-fw"}}
        config = {
            "sources": {
                "fake-fw": {
                    "local_path": "components/board/fake-board/firmware/touch",
                },
            },
        }
        fw_dir = manager.ensure_extra_firmware("fake-fw", cfg, config=config)
        assert fw_dir == (fake_board_tree / "components/board/fake-board"
                          / "firmware/touch")
        assert (fw_dir / "blob.bin").read_bytes() == b"\x01\x02\x03"

    def test_未知_source_引用抛异常(self, fake_board_tree: Path):
        manager = SourceManager(
            sources_dir=fake_board_tree / ".build/sources",
            project_root=fake_board_tree,
        )
        with pytest.raises(ValueError, match="未知 source"):
            manager.ensure_extra_firmware(
                "missing", {"source": {"name": "missing"}},
                config={"sources": {}})


def test_extra_firmware_download复用公共校验入口(
        manager: SourceManager, tmp_path: Path):
    artifact = tmp_path / "firmware.bin"
    with patch.object(
            manager, "ensure_download", return_value=artifact) as download:
        result = manager.ensure_extra_firmware(
            "demo", {
                "url": "https://example.com/firmware.bin",
                "sha256": "a" * 64,
            })

    assert result == artifact.parent
    download.assert_called_once()


def test_fetch_checkout_discards_previous_build_patches(tmp_path: Path):
    """切换锁定 commit 前必须清理上次构建留在 tracked 文件中的 patch。"""
    origin = tmp_path / "origin"
    work = tmp_path / "work"
    origin.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=origin, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"],
                   cwd=origin, check=True)
    subprocess.run(["git", "config", "user.name", "Test"],
                   cwd=origin, check=True)
    tracked = origin / "tracked.txt"
    tracked.write_text("one\n")
    subprocess.run(["git", "add", "tracked.txt"], cwd=origin, check=True)
    subprocess.run(["git", "commit", "-qm", "one"], cwd=origin, check=True)
    first = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=origin, check=True,
        capture_output=True, text=True).stdout.strip()
    tracked.write_text("two\n")
    subprocess.run(["git", "commit", "-qam", "two"], cwd=origin, check=True)
    second = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=origin, check=True,
        capture_output=True, text=True).stdout.strip()

    subprocess.run(["git", "clone", "-q", str(origin), str(work)], check=True)
    subprocess.run(["git", "checkout", "-q", first], cwd=work, check=True)
    (work / "tracked.txt").write_text("上次构建的 patch\n")

    SourceManager(tmp_path / "sources")._fetch_checkout(work, second)

    assert (work / "tracked.txt").read_text() == "two\n"
    assert subprocess.run(
        ["git", "status", "--porcelain"], cwd=work, check=True,
        capture_output=True, text=True).stdout == ""


def test_fetch_reset_branch_skips_mixed_reset_when_head_is_unchanged(
        manager: SourceManager, tmp_path: Path):
    """远端 HEAD 未变化时不得使整个源码树的时间戳失效。"""
    repo = tmp_path / "repo"
    repo.mkdir()
    with patch.object(manager, "_rev_parse", return_value="same"), \
            patch.object(manager, "_rev_parse_ref", return_value="same"), \
            patch("builder.source.subprocess.run") as run:
        run.return_value.returncode = 0
        manager._fetch_reset_branch(repo, "linux-7.0.11")

    commands = [call.args[0] for call in run.call_args_list]
    assert not any(command[:2] == ["git", "reset"] for command in commands)
    assert ["git", "diff-index", "--quiet", "HEAD", "--"] in commands
    assert ["git", "checkout", "-f", "."] not in commands
    assert ["git", "clean", "-fd"] in commands


def test_fetch_reset_branch_does_not_scan_worktree_during_cache_preflight(
        manager: SourceManager, tmp_path: Path):
    """缓存预检只同步 commit，不扫描大源码树。"""
    repo = tmp_path / "repo"
    repo.mkdir()
    manager._preparing_cache_inputs = True
    completed = subprocess.CompletedProcess(
        [], 0, stdout="same\trefs/heads/linux-7.0.11\n")
    with patch.object(manager, "_rev_parse", return_value="same"), \
            patch.object(manager, "_rev_parse_ref", return_value="same"), \
            patch("builder.source.subprocess.run",
                  return_value=completed) as run:
        prepared = manager._fetch_reset_branch(repo, "linux-7.0.11")

    commands = [call.args[0] for call in run.call_args_list]
    assert prepared is False
    assert not any(command[1] == "fetch" for command in commands)
    assert not any(command[1] in {"diff-index", "reset", "checkout", "clean"}
                   for command in commands)


def test_fetch_reset_branch_prefers_hard_reset_when_head_changes(
        manager: SourceManager, tmp_path: Path):
    """远端 HEAD 更新时只让 Git 重写实际变化文件。"""
    repo = tmp_path / "repo"
    repo.mkdir()
    completed = subprocess.CompletedProcess([], 0)
    with patch.object(manager, "_rev_parse", return_value="old"), \
            patch.object(manager, "_rev_parse_ref", return_value="new"), \
            patch("builder.source.subprocess.run",
                  return_value=completed) as run:
        manager._fetch_reset_branch(repo, "linux-7.0.11")

    commands = [call.args[0] for call in run.call_args_list]
    assert ["git", "reset", "--hard", "origin/linux-7.0.11"] in commands
    assert not any("--mixed" in command for command in commands)


def test_fetch_reset_branch_falls_back_when_hard_reset_fails(
        manager: SourceManager, tmp_path: Path):
    """大小写冲突使 hard reset 失败时保留兼容路径。"""
    repo = tmp_path / "repo"
    repo.mkdir()

    def run_git(command, **_kwargs):
        failed = command[:3] == ["git", "reset", "--hard"]
        return subprocess.CompletedProcess(command, int(failed))

    with patch.object(manager, "_rev_parse", return_value="old"), \
            patch.object(manager, "_rev_parse_ref", return_value="new"), \
            patch("builder.source.subprocess.run", side_effect=run_git) as run:
        manager._fetch_reset_branch(repo, "linux-7.0.11")

    commands = [call.args[0] for call in run.call_args_list]
    assert ["git", "reset", "--mixed", "--no-refresh",
            "origin/linux-7.0.11"] in commands
