"""导出包含包名与版本的清单，同时供镜像内排障与构建产物审计。"""

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
