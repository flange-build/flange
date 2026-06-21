"""AmlogicKernelBuilder 单元测试 — 验证 mainline 6.12 路径与命令构造。

测试聚焦：
- configure 默认走 ``defconfig`` 单 step；list 形态依次合并
- compile 的 make targets 包含 Image / DT / modules，dts_dir=amlogic
- collect 返回 image / dtb / modules 三键，路径走 arch/arm64/boot/dts/amlogic/
- KCFLAGS=-Wno-error 仍然透传
"""

from __future__ import annotations

from pathlib import Path

import pytest

from builder.platforms.amlogic.kernel import AmlogicKernelBuilder


class RecordingAmlogicKernelBuilder(AmlogicKernelBuilder):
    """记录 make 调用，避免真正编译。"""

    def __init__(self):
        super().__init__(docker=None, source=None)
        self.make_calls: list[tuple[list[str], dict]] = []

    def make(self, src_dir: Path, targets: list, **kwargs):
        self.make_calls.append((list(targets), dict(kwargs)))


@pytest.fixture
def builder():
    return RecordingAmlogicKernelBuilder()


def _config(defconfig="defconfig", dts_dir="amlogic", overlays=None):
    return {
        "kernel": {
            "defconfig": defconfig,
            "dts": "meson-sm1-khadas-vim3l",
            "dts_dir": dts_dir,
        },
        "boot": {
            "dtb_overlays": overlays or [],
            "vendor_overlays": [],
            "board_overlays": [],
            "default_overlays": [],
        },
    }


def test_instantiate(builder):
    assert builder.component == "kernel"
    assert builder.ARCH == "arm64"
    # CROSS 继承 base ComponentBuilder 全平台默认 gcc-10（见 builder/base.py）
    assert builder.CROSS == "/opt/aarch64-gcc10/bin/aarch64-linux-"


def test_configure_single_defconfig_calls_make_once(builder, tmp_path,
                                                     monkeypatch):
    """configure 走单字符串 defconfig 时只 make 一次。"""
    src = tmp_path / "linux"
    (src / "arch" / "arm64" / "configs").mkdir(parents=True)
    # 屏蔽 case_insensitive_fix 的 fragment 写入（依赖文件系统探针）
    monkeypatch.setattr(AmlogicKernelBuilder, "_write_case_insensitive_fix",
                        lambda self, src_dir: None)

    builder.configure(src, _config(defconfig="defconfig"))

    assert builder.make_calls == [(["defconfig"],
                                   {"arch": "arm64",
                                    "cross": "/opt/aarch64-gcc10/bin/aarch64-linux-"})]


def test_configure_list_defconfig_merges_in_order(builder, tmp_path,
                                                   monkeypatch):
    """list 形态 defconfig 按序逐个 make。"""
    src = tmp_path / "linux"
    (src / "arch" / "arm64" / "configs").mkdir(parents=True)
    monkeypatch.setattr(AmlogicKernelBuilder, "_write_case_insensitive_fix",
                        lambda self, src_dir: None)

    builder.configure(src, _config(defconfig=["defconfig",
                                              "case_insensitive_fix.config"]))

    assert [c[0] for c in builder.make_calls] == [
        ["defconfig"],
        ["case_insensitive_fix.config"],
    ]


def test_compile_targets_include_image_dtb_modules(builder, tmp_path,
                                                    monkeypatch):
    """compile 的 make targets 含 Image、amlogic/<dts>.dtb、modules，
    KCFLAGS=-Wno-error 透传。"""
    src = tmp_path / "linux"
    src.mkdir()  # _modules_staging 在 src 下；src 必须先存在
    # 屏蔽 OOT 模块 / staging 清理 / modules_install 内部细节
    monkeypatch.setattr(AmlogicKernelBuilder, "_compile_oot_modules",
                        lambda self, src_dir, config, jobs: None)
    monkeypatch.setattr(AmlogicKernelBuilder, "_install_oot_modules",
                        lambda self, src_dir, config, staging: None)
    monkeypatch.setattr(AmlogicKernelBuilder, "_clean_modules_staging",
                        lambda self, staging: None)

    builder.compile(src, _config())

    # 第 0 个 make 调用是主编译；第 1 个是 modules_install
    main_targets, main_kwargs = builder.make_calls[0]
    assert "Image" in main_targets
    assert "amlogic/meson-sm1-khadas-vim3l.dtb" in main_targets
    assert "modules" in main_targets
    assert "KCFLAGS=-Wno-error" in main_kwargs["extra"]


def test_collect_returns_amlogic_dts_paths(builder, tmp_path):
    """collect 输出 image / dtb / modules，dtb 路径在 arch/arm64/boot/dts/amlogic/。"""
    src = tmp_path / "linux"
    outputs = builder.collect(src, _config())

    assert outputs["image"] == src / "arch/arm64/boot/Image"
    assert outputs["dtb"] == (src / "arch/arm64/boot/dts/amlogic"
                              / "meson-sm1-khadas-vim3l.dtb")
    assert outputs["modules"] == src / "_modules_staging"
    # 无 overlay 时不应出现 dtbos 键
    assert "dtbos" not in outputs
