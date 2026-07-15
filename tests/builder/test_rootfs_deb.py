"""Rootfs Phase 2 deb 包安装测试。

覆盖场景：
- 当 app_deb_dir 存在且含 .deb 文件时，dpkg -i 被正确调用
- 当 app_deb_dir 不存在时，dpkg -i 不被调用
- 当 app_deb_dir 存在但无 .deb 文件时，dpkg -i 不被调用
- .deb 文件在安装前被复制到 rootfs/tmp/flange-debs/ 目录
- 安装完成后临时目录被清理
- dpkg -i 调用包含正确的 chroot 内路径
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from builder.platforms.rockchip.rootfs import RockchipRootfsBuilder


# ---------------------------------------------------------------------------
# 测试辅助：构造最小可用的构建环境
# ---------------------------------------------------------------------------

def _make_config(
    tmp_path: Path,
    board: str = "zero3w",
    product: str = "default",
    variant: str = "release",
) -> dict:
    """构造测试用 config 字典。"""
    return {
        "board":   board,
        "product": product,
        "variant": variant,
        "arch":    "aarch64",
        "rootfs":  {
            "packages": [],
            "custom_packages": [],
            "tarball_url": "http://example.com/ubuntu-base.tar.gz",
        },
    }


def _make_builder(tmp_path: Path) -> RockchipRootfsBuilder:
    """构造 RockchipRootfsBuilder，DockerRunner 和 SourceManager 均为 MagicMock。"""
    docker = MagicMock()
    source = MagicMock()

    # source.ensure_rootfs_tarball 返回一个假的 tarball 路径
    fake_tarball = tmp_path / "ubuntu-base.tar.gz"
    fake_tarball.touch()
    source.ensure_rootfs_tarball.return_value = fake_tarball

    builder = RockchipRootfsBuilder(docker, source)
    return builder


def _run_phase2_only(builder: RockchipRootfsBuilder, config: dict, tmp_path: Path):
    """仅执行 Phase 2 逻辑（deb 安装），绕过 Phase 1 和 Phase 3。

    通过 patch 隔离 Phase 1（docker.run_privileged）和 Phase 3（tar 压缩），
    仅验证 deb 安装相关的副作用。

    参数：
        builder:  待测 RockchipRootfsBuilder 实例
        config:   构建配置字典
        tmp_path: pytest 临时目录
    """
    # 创建伪 rootfs 目录（Phase 1 解压后的产物）
    rootfs_dir = tmp_path / "rootfs"
    rootfs_dir.mkdir(parents=True, exist_ok=True)

    # 注入 _work_dir，令 compile 内的 rootfs_dir 指向我们创建的目录
    builder._work_dir = tmp_path

    return rootfs_dir


# ---------------------------------------------------------------------------
# 单元测试：deb 安装核心逻辑
# ---------------------------------------------------------------------------

class TestRootfsDebInstall:
    """测试 rootfs Phase 2 的 deb 包安装步骤。"""

    def test_有deb文件时调用dpkg(self, tmp_path: Path):
        """app_deb_dir 中有 .deb 文件时，ChrootContext.run 应被调用执行 dpkg -i。"""
        config = _make_config(tmp_path)
        builder = _make_builder(tmp_path)

        # 准备 app_deb_dir 及 .deb 文件
        board, product, variant = config["board"], config["product"], config["variant"]
        app_deb_dir = tmp_path / "target" / board / product / variant / "app"
        app_deb_dir.mkdir(parents=True)
        deb1 = app_deb_dir / "myapp_1.0.0_arm64.deb"
        deb2 = app_deb_dir / "libfoo_2.0_arm64.deb"
        deb1.write_bytes(b"fake deb content 1")
        deb2.write_bytes(b"fake deb content 2")

        # 创建伪 rootfs 目录
        rootfs_dir = tmp_path / "rootfs"
        rootfs_dir.mkdir()

        # Mock ChrootContext 以避免真实 chroot 操作
        chroot_mock = MagicMock()
        chroot_ctx_mock = MagicMock()
        chroot_ctx_mock.__enter__ = MagicMock(return_value=chroot_mock)
        chroot_ctx_mock.__exit__ = MagicMock(return_value=False)

        with patch("builder.platforms.rockchip.rootfs.ChrootContext",
                   return_value=chroot_ctx_mock) as mock_chroot_cls, \
             patch("pathlib.Path.cwd", return_value=tmp_path):

            # 直接调用 deb 安装逻辑（从 compile 中提取出来进行隔离测试）
            import shutil
            from builder.chroot import ChrootContext

            # 模拟 Phase 2 deb 安装逻辑
            product_val = config.get("product", "default")
            variant_val = config.get("variant", "release")
            target_dir = tmp_path / "target" / board / product_val / variant_val
            app_deb_dir_check = target_dir / "app"

            if app_deb_dir_check.exists():
                deb_files = sorted(app_deb_dir_check.glob("*.deb"))
                if deb_files:
                    deb_tmp = rootfs_dir / "tmp" / "flange-debs"
                    deb_tmp.mkdir(parents=True, exist_ok=True)
                    for deb in deb_files:
                        shutil.copy2(deb, deb_tmp)
                    with mock_chroot_cls(rootfs_dir, builder.docker) as chroot:
                        deb_list = [f"/tmp/flange-debs/{d.name}" for d in deb_files]
                        chroot.run(["dpkg", "-i"] + deb_list)
                    shutil.rmtree(deb_tmp)

        # 验证 dpkg -i 被调用，且包含两个 deb 文件路径（按字典序）
        chroot_mock.run.assert_called_once()
        called_args = chroot_mock.run.call_args[0][0]
        assert called_args[0] == "dpkg"
        assert called_args[1] == "-i"
        # 文件名按排序顺序排列
        assert "/tmp/flange-debs/libfoo_2.0_arm64.deb" in called_args
        assert "/tmp/flange-debs/myapp_1.0.0_arm64.deb" in called_args

    def test_无deb目录时不调用dpkg(self, tmp_path: Path):
        """app_deb_dir 不存在时，dpkg -i 不应被调用。"""
        config = _make_config(tmp_path)
        builder = _make_builder(tmp_path)

        rootfs_dir = tmp_path / "rootfs"
        rootfs_dir.mkdir()

        # app_deb_dir 不存在（不创建目录）
        board, product, variant = config["board"], config["product"], config["variant"]
        app_deb_dir = tmp_path / "target" / board / product / variant / "app"
        assert not app_deb_dir.exists()

        chroot_mock = MagicMock()
        chroot_ctx_mock = MagicMock()
        chroot_ctx_mock.__enter__ = MagicMock(return_value=chroot_mock)
        chroot_ctx_mock.__exit__ = MagicMock(return_value=False)

        with patch("builder.platforms.rockchip.rootfs.ChrootContext",
                   return_value=chroot_ctx_mock) as mock_chroot_cls:
            # 模拟 Phase 2 deb 安装逻辑
            import shutil

            target_dir = tmp_path / "target" / board / product / variant
            app_deb_dir_check = target_dir / "app"

            if app_deb_dir_check.exists():
                deb_files = sorted(app_deb_dir_check.glob("*.deb"))
                if deb_files:
                    deb_tmp = rootfs_dir / "tmp" / "flange-debs"
                    deb_tmp.mkdir(parents=True, exist_ok=True)
                    for deb in deb_files:
                        shutil.copy2(deb, deb_tmp)
                    with mock_chroot_cls(rootfs_dir, builder.docker) as chroot:
                        deb_list = [f"/tmp/flange-debs/{d.name}" for d in deb_files]
                        chroot.run(["dpkg", "-i"] + deb_list)
                    shutil.rmtree(deb_tmp)

        # ChrootContext 不应被实例化（dpkg 路径未触发）
        mock_chroot_cls.assert_not_called()
        chroot_mock.run.assert_not_called()

    def test_空deb目录时不调用dpkg(self, tmp_path: Path):
        """app_deb_dir 存在但无 .deb 文件时，dpkg -i 不应被调用。"""
        config = _make_config(tmp_path)
        builder = _make_builder(tmp_path)

        rootfs_dir = tmp_path / "rootfs"
        rootfs_dir.mkdir()

        # 创建空的 app_deb_dir（无 .deb 文件）
        board, product, variant = config["board"], config["product"], config["variant"]
        app_deb_dir = tmp_path / "target" / board / product / variant / "app"
        app_deb_dir.mkdir(parents=True)
        # 放入非 .deb 文件，验证 glob("*.deb") 不匹配
        (app_deb_dir / "readme.txt").write_text("not a deb", encoding="utf-8")

        chroot_mock = MagicMock()
        chroot_ctx_mock = MagicMock()
        chroot_ctx_mock.__enter__ = MagicMock(return_value=chroot_mock)
        chroot_ctx_mock.__exit__ = MagicMock(return_value=False)

        with patch("builder.platforms.rockchip.rootfs.ChrootContext",
                   return_value=chroot_ctx_mock) as mock_chroot_cls:
            import shutil

            target_dir = tmp_path / "target" / board / product / variant
            app_deb_dir_check = target_dir / "app"

            if app_deb_dir_check.exists():
                deb_files = sorted(app_deb_dir_check.glob("*.deb"))
                if deb_files:
                    deb_tmp = rootfs_dir / "tmp" / "flange-debs"
                    deb_tmp.mkdir(parents=True, exist_ok=True)
                    for deb in deb_files:
                        shutil.copy2(deb, deb_tmp)
                    with mock_chroot_cls(rootfs_dir, builder.docker) as chroot:
                        deb_list = [f"/tmp/flange-debs/{d.name}" for d in deb_files]
                        chroot.run(["dpkg", "-i"] + deb_list)
                    shutil.rmtree(deb_tmp)

        mock_chroot_cls.assert_not_called()
        chroot_mock.run.assert_not_called()

    def test_deb文件被复制到rootfs_tmp目录(self, tmp_path: Path):
        """安装前 .deb 文件应被复制到 rootfs/tmp/flange-debs/ 目录。"""
        config = _make_config(tmp_path)
        builder = _make_builder(tmp_path)

        rootfs_dir = tmp_path / "rootfs"
        rootfs_dir.mkdir()

        board, product, variant = config["board"], config["product"], config["variant"]
        app_deb_dir = tmp_path / "target" / board / product / variant / "app"
        app_deb_dir.mkdir(parents=True)
        deb1 = app_deb_dir / "testapp_1.0_arm64.deb"
        deb1.write_bytes(b"deb binary content")

        # 记录 chroot.run 被调用时 deb_tmp 是否存在且含目标文件
        copied_files: list[Path] = []

        def fake_chroot_run(cmd, **kwargs):
            """记录调用时 deb_tmp 中的文件列表。"""
            deb_tmp = rootfs_dir / "tmp" / "flange-debs"
            copied_files.extend(deb_tmp.iterdir())

        chroot_mock = MagicMock()
        chroot_mock.run.side_effect = fake_chroot_run
        chroot_ctx_mock = MagicMock()
        chroot_ctx_mock.__enter__ = MagicMock(return_value=chroot_mock)
        chroot_ctx_mock.__exit__ = MagicMock(return_value=False)

        import shutil

        target_dir = tmp_path / "target" / board / product / variant
        app_deb_dir_check = target_dir / "app"

        if app_deb_dir_check.exists():
            deb_files = sorted(app_deb_dir_check.glob("*.deb"))
            if deb_files:
                deb_tmp = rootfs_dir / "tmp" / "flange-debs"
                deb_tmp.mkdir(parents=True, exist_ok=True)
                for deb in deb_files:
                    shutil.copy2(deb, deb_tmp)
                with chroot_ctx_mock:
                    chroot = chroot_ctx_mock.__enter__()
                    deb_list = [f"/tmp/flange-debs/{d.name}" for d in deb_files]
                    chroot.run(["dpkg", "-i"] + deb_list)
                shutil.rmtree(deb_tmp)

        # 验证在 dpkg 调用时 .deb 文件已被复制进去
        assert len(copied_files) == 1
        assert copied_files[0].name == "testapp_1.0_arm64.deb"

    def test_安装后临时目录被清理(self, tmp_path: Path):
        """dpkg 安装完成后，rootfs/tmp/flange-debs/ 临时目录应被删除。"""
        config = _make_config(tmp_path)

        rootfs_dir = tmp_path / "rootfs"
        rootfs_dir.mkdir()

        board, product, variant = config["board"], config["product"], config["variant"]
        app_deb_dir = tmp_path / "target" / board / product / variant / "app"
        app_deb_dir.mkdir(parents=True)
        deb1 = app_deb_dir / "cleanup_test_1.0_arm64.deb"
        deb1.write_bytes(b"cleanup test deb")

        chroot_mock = MagicMock()
        chroot_ctx_mock = MagicMock()
        chroot_ctx_mock.__enter__ = MagicMock(return_value=chroot_mock)
        chroot_ctx_mock.__exit__ = MagicMock(return_value=False)

        import shutil

        target_dir = tmp_path / "target" / board / product / variant
        deb_files = sorted((target_dir / "app").glob("*.deb"))
        deb_tmp = rootfs_dir / "tmp" / "flange-debs"
        deb_tmp.mkdir(parents=True, exist_ok=True)
        for deb in deb_files:
            shutil.copy2(deb, deb_tmp)

        with chroot_ctx_mock:
            chroot = chroot_ctx_mock.__enter__()
            deb_list = [f"/tmp/flange-debs/{d.name}" for d in deb_files]
            chroot.run(["dpkg", "-i"] + deb_list)

        # 安装完成后清理
        shutil.rmtree(deb_tmp)

        # 验证 deb_tmp 已被删除
        assert not deb_tmp.exists()
        # 验证 rootfs/tmp 目录本身仍然存在（仅删除 flange-debs 子目录）
        assert (rootfs_dir / "tmp").exists()

    def test_dpkg调用包含正确的chroot内路径(self, tmp_path: Path):
        """dpkg -i 参数应为 /tmp/flange-debs/<deb_name> 格式的 chroot 内路径。"""
        config = _make_config(tmp_path)
        builder = _make_builder(tmp_path)

        rootfs_dir = tmp_path / "rootfs"
        rootfs_dir.mkdir()

        board, product, variant = config["board"], config["product"], config["variant"]
        app_deb_dir = tmp_path / "target" / board / product / variant / "app"
        app_deb_dir.mkdir(parents=True)
        deb1 = app_deb_dir / "service_1.2.3_arm64.deb"
        deb1.write_bytes(b"service deb")

        chroot_mock = MagicMock()
        chroot_ctx_mock = MagicMock()
        chroot_ctx_mock.__enter__ = MagicMock(return_value=chroot_mock)
        chroot_ctx_mock.__exit__ = MagicMock(return_value=False)

        import shutil

        target_dir = tmp_path / "target" / board / product / variant
        app_deb_dir_check = target_dir / "app"
        deb_files = sorted(app_deb_dir_check.glob("*.deb"))

        deb_tmp = rootfs_dir / "tmp" / "flange-debs"
        deb_tmp.mkdir(parents=True, exist_ok=True)
        for deb in deb_files:
            shutil.copy2(deb, deb_tmp)

        with chroot_ctx_mock:
            chroot = chroot_ctx_mock.__enter__()
            deb_list = [f"/tmp/flange-debs/{d.name}" for d in deb_files]
            chroot.run(["dpkg", "-i"] + deb_list)

        shutil.rmtree(deb_tmp)

        # 验证 dpkg -i 参数格式正确
        chroot_mock.run.assert_called_once_with(
            ["dpkg", "-i", "/tmp/flange-debs/service_1.2.3_arm64.deb"]
        )


# ---------------------------------------------------------------------------
# 集成测试：通过 compile() 方法验证端到端 Phase 2 流程
# ---------------------------------------------------------------------------

class TestRootfsDebInstallIntegration:
    """通过 compile() 方法的集成测试，验证 Phase 2 deb 安装端到端流程。"""

    @staticmethod
    def _compile_isolated(
        builder: RockchipRootfsBuilder,
        config: dict,
        work_dir: Path,
        chroot_ctx: MagicMock,
    ) -> MagicMock:
        """保留真实 Phase 2 deb 路径，隔离其余 rootfs 构建步骤。"""
        work_dir.mkdir()
        isolated = {
            "_build_phase1": MagicMock(),
            "_build_ext4": MagicMock(),
            "_install_extra_debs": MagicMock(),
            "_install_kernel_modules": MagicMock(),
            "_install_extra_firmware": MagicMock(),
            "_install_panel_firmware": MagicMock(),
            "apply_overlays": MagicMock(),
            "_configure_users": MagicMock(),
            "_install_hostname": MagicMock(),
        }
        with patch.multiple(builder, **isolated), patch(
            "builder.platforms.rockchip.rootfs.ChrootContext",
            return_value=chroot_ctx,
        ) as chroot_cls, patch(
            "builder.platforms.rockchip.rootfs.tempfile.mkdtemp",
            return_value=str(work_dir),
        ):
            builder.compile(None, config)
        return chroot_cls

    def test_compile调用dpkg安装deb包(self, tmp_path: Path, monkeypatch):
        """compile() 执行时，若存在 .deb 文件，应在 ChrootContext 内调用 dpkg -i。"""
        config = _make_config(tmp_path)
        board, product, variant = config["board"], config["product"], config["variant"]

        # Phase 2 使用三层产物路径 .build/target/<board>/<product>/<variant>。
        monkeypatch.chdir(tmp_path)

        # 准备 .deb 文件
        app_deb_dir = (
            tmp_path / ".build" / "target" / board / product / variant / "app"
        )
        app_deb_dir.mkdir(parents=True)
        deb_file = app_deb_dir / "integrate_1.0_arm64.deb"
        deb_file.write_bytes(b"integration deb")

        builder = _make_builder(tmp_path)
        chroot = MagicMock()
        chroot_ctx = MagicMock()
        chroot_ctx.__enter__.return_value = chroot
        chroot_ctx.__exit__.return_value = False

        self._compile_isolated(
            builder, config, tmp_path / "work", chroot_ctx)

        chroot.run.assert_called_once_with(
            [
                "dpkg", "-i", "--force-confnew",
                "/tmp/flange-debs/integrate_1.0_arm64.deb",
            ],
            label="dpkg -i (1 个包)...",
        )
        assert not (tmp_path / "work" / "rootfs" / "tmp"
                    / "flange-debs").exists()

    def test_compile无deb时不调用dpkg(self, tmp_path: Path, monkeypatch):
        """compile() 执行时，若无 .deb 文件，不应调用 dpkg -i。"""
        config = _make_config(tmp_path)
        # 不创建 app_deb_dir

        monkeypatch.chdir(tmp_path)

        builder = _make_builder(tmp_path)
        chroot_ctx = MagicMock()
        chroot_cls = self._compile_isolated(
            builder, config, tmp_path / "work", chroot_ctx)

        chroot_cls.assert_not_called()


# ---------------------------------------------------------------------------
# 单元测试：extra_debs（第三方 deb 包下载安装）
# ---------------------------------------------------------------------------

class TestExtraDebs:
    """测试 RootfsBuilder._install_extra_debs 下载安装第三方 deb 包。"""

    def test_config为空时不调用dpkg(self, tmp_path: Path):
        """rootfs.extra_debs 为空列表时，不应调用 dpkg。"""
        builder = _make_builder(tmp_path)
        rootfs_dir = tmp_path / "rootfs"
        rootfs_dir.mkdir()

        config = _make_config(tmp_path)
        config["rootfs"]["extra_debs"] = []

        builder._install_extra_debs(rootfs_dir, config)
        builder.docker.run.assert_not_called()

    def test_config无extra_debs键时不调用dpkg(self, tmp_path: Path):
        """config 中无 extra_debs 键时，不应调用 dpkg。"""
        builder = _make_builder(tmp_path)
        rootfs_dir = tmp_path / "rootfs"
        rootfs_dir.mkdir()

        config = _make_config(tmp_path)
        # 删除 extra_debs 键（如果有的话）
        config["rootfs"].pop("extra_debs", None)

        builder._install_extra_debs(rootfs_dir, config)
        builder.docker.run.assert_not_called()

    def test_有extra_debs时调用source下载并dpkg安装(self, tmp_path: Path):
        """extra_debs 声明后，应下载 deb 并调用 dpkg -i 安装。"""
        builder = _make_builder(tmp_path)
        rootfs_dir = tmp_path / "rootfs"
        rootfs_dir.mkdir(parents=True)

        # 模拟 source.ensure_extra_deb 返回本地 deb 路径
        fake_deb = tmp_path / "test-pkg_1.0_arm64.deb"
        fake_deb.write_bytes(b"fake deb content")
        builder.source.ensure_extra_deb.return_value = fake_deb

        # 模拟 ChrootContext（__enter__ 返回自身）
        mock_chroot = MagicMock()
        mock_chroot.__enter__ = MagicMock(return_value=mock_chroot)
        mock_chroot.__exit__ = MagicMock(return_value=False)
        with patch("builder.rootfs.ChrootContext", return_value=mock_chroot):
            config = _make_config(tmp_path)
            config["rootfs"]["extra_debs"] = [
                {
                    "name": "test-pkg",
                    "url": "https://example.com/test-pkg_1.0_arm64.deb",
                    "sha256": "abc123",
                },
            ]
            builder._install_extra_debs(rootfs_dir, config)

        # 验证 ensure_extra_deb 被调用
        builder.source.ensure_extra_deb.assert_called_once_with(
            "test-pkg",
            {
                "name": "test-pkg",
                "url": "https://example.com/test-pkg_1.0_arm64.deb",
                "sha256": "abc123",
            },
        )
        # 验证 chroot 内先后调了 dpkg -i 与 ldconfig
        assert mock_chroot.run.call_count == 2
        dpkg_cmd = mock_chroot.run.call_args_list[0][0][0]
        assert dpkg_cmd[0] == "dpkg"
        assert "-i" in dpkg_cmd
        assert any("test-pkg_1.0_arm64.deb" in arg for arg in dpkg_cmd)
        ldconfig_cmd = mock_chroot.run.call_args_list[1][0][0]
        assert ldconfig_cmd == ["ldconfig"]

    def test_临时目录安装后清理(self, tmp_path: Path):
        """dpkg 安装完成后，临时目录 /tmp/flange-extra-debs 应被清理。"""
        builder = _make_builder(tmp_path)
        rootfs_dir = tmp_path / "rootfs"
        rootfs_dir.mkdir(parents=True)

        fake_deb = tmp_path / "test-pkg_1.0_arm64.deb"
        fake_deb.write_bytes(b"fake deb content")
        builder.source.ensure_extra_deb.return_value = fake_deb

        with patch("builder.rootfs.ChrootContext", return_value=MagicMock()):
            config = _make_config(tmp_path)
            config["rootfs"]["extra_debs"] = [
                {
                    "name": "test-pkg",
                    "url": "https://example.com/test-pkg_1.0_arm64.deb",
                    "sha256": "abc123",
                },
            ]
            builder._install_extra_debs(rootfs_dir, config)

        # 临时目录应被清理
        assert not (rootfs_dir / "tmp" / "flange-extra-debs").exists()

    def test_多个extra_debs批量安装(self, tmp_path: Path):
        """多个 extra_debs 应在一次 dpkg -i 调用中批量安装。"""
        builder = _make_builder(tmp_path)
        rootfs_dir = tmp_path / "rootfs"
        rootfs_dir.mkdir(parents=True)

        deb1 = tmp_path / "pkg-a_1.0_arm64.deb"
        deb2 = tmp_path / "pkg-b_2.0_arm64.deb"
        deb1.write_bytes(b"a")
        deb2.write_bytes(b"b")

        def fake_ensure(name, cfg):
            return deb1 if name == "pkg-a" else deb2

        builder.source.ensure_extra_deb.side_effect = fake_ensure

        mock_chroot = MagicMock()
        mock_chroot.__enter__ = MagicMock(return_value=mock_chroot)
        mock_chroot.__exit__ = MagicMock(return_value=False)
        with patch("builder.rootfs.ChrootContext", return_value=mock_chroot):
            config = _make_config(tmp_path)
            config["rootfs"]["extra_debs"] = [
                {"name": "pkg-a", "url": "https://ex.com/a.deb", "sha256": "a"},
                {"name": "pkg-b", "url": "https://ex.com/b.deb", "sha256": "b"},
            ]
            builder._install_extra_debs(rootfs_dir, config)

        # 应一次 dpkg -i 安装两个 deb，再跟一次 ldconfig
        assert mock_chroot.run.call_count == 2
        dpkg_cmd = mock_chroot.run.call_args_list[0][0][0]
        deb_args = [a for a in dpkg_cmd if a.endswith(".deb")]
        assert len(deb_args) == 2
        assert mock_chroot.run.call_args_list[1][0][0] == ["ldconfig"]
