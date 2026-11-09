"""linux-headers deb：kernel 打包、产物契约、包集合联动与 rootfs 安装。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from builder.base import ComponentBuilder
from builder.component_plan import output_contract
from builder.config.jsonnet import _expand_package_sets
from builder.docker import BuildError
from builder.platforms.amlogic.kernel import AmlogicKernelBuilder
from builder.platforms.rockchip.rootfs import RockchipRootfsBuilder
from tests.builder.context import component_context


def _config(enabled: bool) -> dict:
    return {
        "board": "zero3w",
        "platform": "rockchip",
        "architecture": {"userspace": "aarch64", "kernel": "arm64", "bootloader": "arm64"},
        "kernel": {
            "headers_package": enabled,
            "device_tree": {"directory": "rockchip", "name": "rk3566-radxa-zero3w"},
        },
        "boot": {"overlays": {"intree": [], "vendor": [], "board": [], "package": [],
                              "enabled": []}},
    }


def _kernel_builder(tmp_path: Path) -> AmlogicKernelBuilder:
    docker = MagicMock()
    docker.run.return_value = SimpleNamespace(stdout="6.1.84-rk_Test\n")
    builder = AmlogicKernelBuilder(docker, None)
    builder.context = component_context(tmp_path, {"board": "zero3w"})
    return builder


def test_package_headers生成control与维护脚本(tmp_path):
    builder = _kernel_builder(tmp_path)
    out = builder._package_headers(tmp_path / "src", _config(True))

    stage, dpkg = builder.docker.run.call_args_list[1:]
    pkg = Path(dpkg.args[0][-2])
    assert stage.args[0][-2:] == [str(pkg / "usr/src/linux-headers-6.1.84-rk_Test"), "arm64"]
    assert dpkg.args[0][-1] == str(out / "linux-headers-6.1.84-rk-test_6.1.84-rk+Test_arm64.deb")

    control = (pkg / "DEBIAN/control").read_text()
    assert "Package: linux-headers-6.1.84-rk-test\n" in control
    assert "Architecture: arm64\n" in control
    assert "Depends: make, gcc," in control
    postinst = pkg / "DEBIAN/postinst"
    assert postinst.stat().st_mode & 0o777 == 0o755
    assert "cd /usr/src/linux-headers-6.1.84-rk_Test" in postinst.read_text()
    assert "M=scripts/mod" in postinst.read_text()
    link = pkg / "lib/modules/6.1.84-rk_Test/build"
    assert str(link.readlink()) == "/usr/src/linux-headers-6.1.84-rk_Test"


@pytest.mark.parametrize("enabled", [True, False])
def test_build按开关追加headers产物(tmp_path, enabled):
    builder = _kernel_builder(tmp_path)

    def fake_build(self, config):
        self.src_dir = tmp_path / "src"
        return {"image": "Image"}

    with (
        patch.object(ComponentBuilder, "build", fake_build),
        patch.object(builder, "_package_headers", return_value=tmp_path / "headers") as package,
    ):
        outputs = builder.build(_config(enabled))
    assert ("headers" in outputs) is enabled
    assert package.called is enabled


@pytest.mark.parametrize("enabled", [True, False])
def test_产物契约声明headers(tmp_path, enabled):
    context = component_context(tmp_path, {"board": "zero3w"})
    names = {spec.name for spec in output_contract("kernel", _config(enabled), context)}
    assert ("headers" in names) is enabled


@pytest.mark.parametrize("enabled", [True, False])
def test_headers开关自动选入kernel_devel包集合(enabled):
    config = {
        "kernel": {"headers_package": enabled},
        "rootfs": {
            "package_set": ["base"],
            "package_sets": {"base": ["bash"], "kernel_devel": ["gcc", "make"]},
        },
    }
    _expand_package_sets(config)
    assert config["rootfs"]["packages"] == (["bash", "gcc", "make"] if enabled else ["bash"])


def _rootfs_builder(tmp_path: Path) -> RockchipRootfsBuilder:
    builder = RockchipRootfsBuilder(MagicMock(), MagicMock())
    builder.context = component_context(tmp_path, {"board": "zero3w"})
    return builder


def test_rootfs关闭时不安装headers(tmp_path):
    builder = _rootfs_builder(tmp_path)
    with patch("builder.rootfs.ChrootContext") as chroot:
        builder._install_kernel_headers(tmp_path / "rootfs", _config(False))
    chroot.assert_not_called()


def test_rootfs开启但产物缺失时报错(tmp_path):
    builder = _rootfs_builder(tmp_path)
    with pytest.raises(BuildError, match="headers 产物缺失"):
        builder._install_kernel_headers(tmp_path / "rootfs", _config(True))


def test_rootfs开启时dpkg安装headers(tmp_path):
    builder = _rootfs_builder(tmp_path)
    headers = builder.context.target_dir / "kernel" / "headers"
    headers.mkdir(parents=True)
    (headers / "linux-headers-6.1_6.1_arm64.deb").write_bytes(b"deb")
    rootfs = tmp_path / "rootfs"
    with patch("builder.rootfs.ChrootContext") as chroot:
        builder._install_kernel_headers(rootfs, _config(True))
    run = chroot.return_value.__enter__.return_value.run
    assert run.call_args.args[0] == [
        "dpkg", "-i", "/tmp/flange-kernel-headers/linux-headers-6.1_6.1_arm64.deb",
    ]
    assert not (rootfs / "tmp/flange-kernel-headers").exists()
