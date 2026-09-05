"""AmlogicBootBuilder 单元测试。

测试聚焦：
- DTB_VENDOR_DIR 是 dtbs/amlogic（与 rockchip dtbs/rockchip 对齐但 vendor 不同）
- compile 流程将 kernel Image + DTB 拷到 staging/extlinux 与 staging/dtbs/amlogic
- extlinux.conf APPEND 含 ``console=ttyAML0`` 与 PARTLABEL=rootfs
- recovery.enabled=True 时生成 recovery.conf，含 PARTLABEL=recovery 与
  flange.mode=recovery
- mke2fs 命令行参数构造正确
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.builder.context import component_context

from builder.platforms.amlogic.boot import AmlogicBootBuilder


class FakeDocker:
    """记录 docker 命令，免运行 truncate / mke2fs。"""

    def __init__(self):
        self.commands: list[list[str]] = []

    def run(self, cmd: list[str], **kwargs):
        self.commands.append(list(cmd))


class FakeCache:
    def __init__(self, target_dir: Path):
        self.target_dir = target_dir


def _config(recovery_enabled=False):
    return {
        "platform": "amlogic",
        "soc": "s905d3",
        "board": "test-vim3l",
        "kernel": {"device_tree": {
            "directory": "amlogic", "name": "meson-sm1-khadas-vim3l",
        }},
        "boot": {**{
            "kernel_args": "earlycon console=ttyAML0,115200n8 loglevel=7",
        }, "overlays": {
            "intree": [], "vendor": [], "board": [], "package": [],
            "enabled": [],
        }},
        "recovery": {"enabled": recovery_enabled},
        "partitions": {
            "entries": [
                {"name": "boot", "size": "0x20000", "type": "ext4"},
                {"name": "rootfs", "size": "0x100000", "type": "ext4"},
            ],
        },
    }


def _prepare_kernel_target(target_dir: Path) -> str:
    kernel_dir = target_dir / "kernel"
    kernel_dir.mkdir(parents=True)
    (kernel_dir / "Image").write_bytes(b"image")
    dtb_name = "meson-sm1-khadas-vim3l.dtb"
    (kernel_dir / dtb_name).write_bytes(b"dtb")
    return dtb_name


def test_dtb_vendor_dir_is_amlogic():
    """关键差异点：DTB 存放目录是 dtbs/amlogic（不是 rockchip）。"""
    assert AmlogicBootBuilder.DTB_VENDOR_DIR == "dtbs/amlogic"


def test_compile_writes_extlinux_and_dtb_to_amlogic_subdir(tmp_path):
    """compile 把 Image 放到 staging/extlinux/，DTB 放到 staging/dtbs/amlogic/。"""
    target_dir = tmp_path / "target"
    _prepare_kernel_target(target_dir)

    builder = AmlogicBootBuilder(docker=FakeDocker(), source=None)
    builder.cache = FakeCache(target_dir)
    builder.context = component_context(tmp_path, _config(), target_dir=target_dir)
    builder.compile(None, _config())

    work_dir = builder._work_dir
    staging = work_dir / "staging"
    assert (staging / "extlinux" / "Image").is_file()
    assert (staging / "dtbs" / "amlogic" / "meson-sm1-khadas-vim3l.dtb").is_file()
    assert (staging / "extlinux" / "extlinux.conf").is_file()


def test_extlinux_conf_contains_amlogic_paths_and_console(tmp_path):
    """extlinux.conf APPEND 含 ttyAML0 console + PARTLABEL=rootfs；
    fdt 路径走 /dtbs/amlogic/。"""
    target_dir = tmp_path / "target"
    _prepare_kernel_target(target_dir)

    builder = AmlogicBootBuilder(docker=FakeDocker(), source=None)
    builder.cache = FakeCache(target_dir)
    builder.context = component_context(tmp_path, _config(), target_dir=target_dir)
    builder.compile(None, _config())

    conf = (builder._work_dir / "staging" / "extlinux"
            / "extlinux.conf").read_text()
    assert "console=ttyAML0,115200n8" in conf
    assert "root=PARTLABEL=rootfs" in conf
    assert "/dtbs/amlogic/meson-sm1-khadas-vim3l.dtb" in conf


def test_recovery_conf_emitted_when_enabled(tmp_path):
    """recovery.enabled=True 时生成 recovery.conf；含 flange.mode=recovery。"""
    target_dir = tmp_path / "target"
    _prepare_kernel_target(target_dir)

    builder = AmlogicBootBuilder(docker=FakeDocker(), source=None)
    builder.cache = FakeCache(target_dir)
    builder.context = component_context(tmp_path, _config(), target_dir=target_dir)
    builder.compile(None, _config(recovery_enabled=True))

    rec = (builder._work_dir / "staging" / "extlinux"
           / "recovery.conf").read_text()
    assert "root=PARTLABEL=recovery" in rec
    assert "flange.mode=recovery" in rec


def test_recovery_conf_absent_when_disabled(tmp_path):
    target_dir = tmp_path / "target"
    _prepare_kernel_target(target_dir)

    builder = AmlogicBootBuilder(docker=FakeDocker(), source=None)
    builder.cache = FakeCache(target_dir)
    builder.context = component_context(tmp_path, _config(), target_dir=target_dir)
    builder.compile(None, _config(recovery_enabled=False))

    assert not (builder._work_dir / "staging" / "extlinux"
                / "recovery.conf").exists()


def test_mke2fs_command_uses_boot_label(tmp_path):
    """mke2fs 必须用 -L boot；fstab LABEL=boot 依赖此 label。"""
    target_dir = tmp_path / "target"
    _prepare_kernel_target(target_dir)

    docker = FakeDocker()
    builder = AmlogicBootBuilder(docker=docker, source=None)
    builder.cache = FakeCache(target_dir)
    builder.context = component_context(tmp_path, _config(), target_dir=target_dir)
    builder.compile(None, _config())

    mke2fs_calls = [c for c in docker.commands if c and c[0] == "mke2fs"]
    assert len(mke2fs_calls) == 1
    cmd = mke2fs_calls[0]
    assert "-L" in cmd and cmd[cmd.index("-L") + 1] == "boot"


def test_collect_returns_boot_img(tmp_path):
    target_dir = tmp_path / "target"
    _prepare_kernel_target(target_dir)

    builder = AmlogicBootBuilder(docker=FakeDocker(), source=None)
    builder.cache = FakeCache(target_dir)
    builder.context = component_context(tmp_path, _config(), target_dir=target_dir)
    builder.compile(None, _config())

    out = builder.collect(None, _config())
    assert "boot" in out
    assert out["boot"].name == "boot.img"


def test_compile_raises_when_kernel_image_missing(tmp_path):
    """kernel Image 缺失时给出含路径的明确错误。"""
    target_dir = tmp_path / "target"
    target_dir.mkdir()  # 故意不建 kernel/Image

    builder = AmlogicBootBuilder(docker=FakeDocker(), source=None)
    builder.cache = FakeCache(target_dir)
    builder.context = component_context(tmp_path, _config(), target_dir=target_dir)

    with pytest.raises(FileNotFoundError, match="kernel Image"):
        builder.compile(None, _config())
