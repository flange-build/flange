"""硬件特性包 oot-driver 在工作目录编译：包目录产物不改变 kernel 任务输入身份。"""

import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

from builder.component_plan import create_component_plan
from builder.kernel_base import KernelBuilder
from builder.packages import expand_hardware_packages
from builder.source import SourceManager
from builder.workspace import Target, WorkspaceContext

_PACKAGE = """
PACKAGE = {
    "name": "demo-driver",
    "components": [
        {"name": "touch", "type": "oot-driver", "dir": "driver/touch",
         "ko_pattern": ["touch.ko"]},
    ],
}
"""


class FakeDocker:
    """真实执行文件操作，模拟 kbuild 把产物写进 M= 目录。"""

    def __init__(self):
        self.make_dirs: list[Path] = []

    def run(self, cmd, cwd=None, capture=False, **_):
        if cmd[0] == "make":
            build_dir = Path(next(a for a in cmd if a.startswith("M="))[2:])
            assert Path(cwd) == build_dir
            self.make_dirs.append(build_dir)
            for name in ("touch.o", ".touch.o.cmd", "touch.mod.c", "Module.symvers", "touch.ko"):
                (build_dir / name).write_text("built")
            return SimpleNamespace(stdout="")
        if cmd[0] == "cat":
            return SimpleNamespace(stdout="6.1.0-test\n")
        if cmd[0].endswith("strip"):
            shutil.copy(cmd[-1], cmd[-2])
            return SimpleNamespace(stdout="")
        if cmd[0] == "depmod":
            return SimpleNamespace(stdout="")
        subprocess.run(cmd, cwd=cwd, check=True)
        return SimpleNamespace(stdout="")


class DemoKernelBuilder(KernelBuilder):
    ARCH = "arm64"

    def configure(self, src_dir, config):
        raise NotImplementedError

    def compile(self, src_dir, config):
        raise NotImplementedError

    def collect(self, src_dir, config):
        raise NotImplementedError


def _setup(tmp_path: Path):
    package = tmp_path / "components" / "packages" / "demo-driver"
    driver = package / "driver" / "touch"
    driver.mkdir(parents=True)
    (package / "package.py").write_text(_PACKAGE)
    (driver / "touch.c").write_text("/* touch */\n")
    (driver / "Makefile").write_text("obj-m += touch.o\n")
    ctx = WorkspaceContext(
        tmp_path, tmp_path, tmp_path / ".build", Target("board", "default", "release")
    )
    config = {
        "board": "board", "platform": "rockchip", "soc": "rk3566",
        "architecture": {"kernel": "arm64", "userspace": "aarch64", "bootloader": "arm64"},
        "kernel": {"device_tree": {"directory": "", "name": "board"}},
        "rootfs": {"packages": []}, "bootloader": {}, "sources": {},
        "packages": ["demo-driver"],
    }
    expand_hardware_packages(config, project_root=tmp_path)
    builder = DemoKernelBuilder(FakeDocker(), source=None)
    builder.context = ctx
    return ctx, config, builder, driver


def _fingerprint(config, ctx) -> str:
    plan = create_component_plan("kernel", config, ctx, SourceManager(context=ctx))
    assert any(spec.name.startswith("driver:") for spec in plan.inputs)
    return plan.fingerprint({name: "artifact-id" for name in plan.dependencies}).digest


def test_包驱动在工作目录编译_kernel输入身份不变(tmp_path):
    ctx, config, builder, driver = _setup(tmp_path)
    kernel_src = tmp_path / "linux"
    kernel_src.mkdir()
    before = _fingerprint(config, ctx)

    builder._compile_oot_modules(kernel_src, config, jobs=1)

    build_dir = builder.docker.make_dirs[0]
    assert build_dir.is_relative_to(ctx.build_root / "work" / ctx.target.key)
    assert (build_dir / "touch.ko").is_file()
    assert sorted(p.name for p in driver.iterdir()) == ["Makefile", "touch.c"]
    assert _fingerprint(config, ctx) == before

    staging = tmp_path / "staging"
    builder._install_oot_modules(kernel_src, config, staging)
    assert (staging / "lib/modules/6.1.0-test/updates/touch.ko").is_file()


def test_重复编译从源目录全新拷贝(tmp_path):
    ctx, config, builder, driver = _setup(tmp_path)
    kernel_src = tmp_path / "linux"
    kernel_src.mkdir()
    builder._compile_oot_modules(kernel_src, config, jobs=1)
    build_dir = builder.docker.make_dirs[0]
    (build_dir / "stale.o").write_text("old")
    (driver / "touch.c").write_text("/* touch v2 */\n")

    builder._compile_oot_modules(kernel_src, config, jobs=1)

    assert not (build_dir / "stale.o").exists()
    assert (build_dir / "touch.c").read_text() == "/* touch v2 */\n"


def test_原地写入产物会改变kernel输入身份(tmp_path):
    """反证：驱动树整树计入输入，故编译必须离开包目录。"""
    ctx, config, _, driver = _setup(tmp_path)
    before = _fingerprint(config, ctx)
    (driver / "touch.ko").write_text("built")
    assert _fingerprint(config, ctx) != before
