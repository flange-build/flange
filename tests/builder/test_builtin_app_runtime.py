"""内置 App 的真实描述必须与发布安装树、运行记录保持一致。"""

import shutil

import pytest

from builder.paths import PROJECT_ROOT
from tests.builder.app_support import builder


@pytest.mark.parametrize("arch", ["aarch64", "armhf"])
def test_recoveryctl安装与运行使用同一管理工具路径(tmp_path, arch):
    source = tmp_path / "recoveryctl"
    shutil.copytree(PROJECT_ROOT / "components/app/recoveryctl", source)
    engine = builder(tmp_path, apps={"recoveryctl": source}, arch=arch)

    result = engine.build_one("recoveryctl").root()

    assert result.executable == "/usr/sbin/recoveryctl"
    installed = result.install_dir / result.executable.lstrip("/")
    assert installed.read_bytes() == (source / "bin/recoveryctl").read_bytes()
    assert installed.stat().st_mode & 0o111
    assert not (result.install_dir / "usr/bin/recoveryctl").exists()
    assert len(result.runtime_debs) == 1
    assert result.validate()
    assert engine.build_one("recoveryctl").root().reused
