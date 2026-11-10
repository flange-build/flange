"""rootfs 包清单导出。

**为什么需要它**：今天只有 ubuntu-base tarball 被 sha256 钉住，之后 apt 装进
去的数百个包一个版本都没钉。同一个 git commit 隔一个月构建，镜像内容不同，而
`flange build` 报"无变更、跳过" —— 缓存在这里主动说谎。

钉版本会让开发期跟随上游修复变得困难，所以先做**事后可审计**：清单同时写进
镜像与产物目录，两次构建的差异用 diff 就能看出来。这个测试锁的是"这一步不会
在后续重构里被静默丢掉"。
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from builder.rootfs import RootfsBuilder
from tests.builder.context import component_context


def _builder(tmp_path: Path) -> RootfsBuilder:
    builder = RootfsBuilder(MagicMock(), MagicMock())
    cache = MagicMock()
    cache.target_dir = tmp_path / "target"
    builder.cache = cache
    builder.output = None
    builder.context = component_context(tmp_path, target_dir=cache.target_dir)
    builder._work_dir = builder.work_dir()
    return builder


def test_导出的清单同时落到镜像内和产物目录(tmp_path: Path):
    rootfs = tmp_path / "rootfs"
    rootfs.mkdir()
    builder = _builder(tmp_path)

    def fake_run(command, **kwargs):
        # 模拟 chroot 内 dpkg-query 的重定向输出
        (rootfs / "etc/flange/packages.manifest").write_text(
            "bash\t5.2-2ubuntu1\nsystemd\t255.4-1ubuntu8\n"
        )
        return MagicMock()

    with patch("builder.rootfs.ChrootContext") as chroot_cls:
        chroot_cls.return_value.__enter__.return_value.run.side_effect = fake_run
        builder._export_package_manifest(rootfs)

    in_image = rootfs / "etc/flange/packages.manifest"
    builder._output = builder._work_dir / "rootfs.img"
    in_target = builder.collect(None, {})["packages"]
    assert in_image.is_file(), "镜像内要有清单，供现场排查"
    assert in_target.is_file(), "收集契约必须返回清单，由引擎与镜像一同原子发布"
    assert in_target.read_text() == in_image.read_text()


def test_清单按包名排序且带版本(tmp_path: Path):
    """无序清单 diff 出来全是噪声，等于没有可审计性。"""
    rootfs = tmp_path / "rootfs"
    rootfs.mkdir()
    builder = _builder(tmp_path)

    captured: list[list[str]] = []

    with patch("builder.rootfs.ChrootContext") as chroot_cls:
        runner = chroot_cls.return_value.__enter__.return_value
        runner.run.side_effect = lambda cmd, **kw: captured.append(cmd)
        builder._export_package_manifest(rootfs)

    assert captured, "必须真的在 chroot 内执行 dpkg-query"
    script = " ".join(captured[0])
    assert "dpkg-query" in script
    assert "${binary:Package}" in script and "${Version}" in script
    assert "sort" in script, "不排序的清单 diff 全是噪声"


def test_phase2最后一步是导出清单():
    """清单必须在所有安装动作之后导出，否则漏掉 app deb 与 extra deb。"""
    import inspect

    source = inspect.getsource(RootfsBuilder._build_phase2)
    steps = [line.strip() for line in source.splitlines() if line.strip().startswith(("self._", "distro."))]
    assert steps[-1].startswith("distro.export_packages"), (
        f"_export_package_manifest 必须是 phase2 最后一步，实际最后是 {steps[-1]}"
    )
