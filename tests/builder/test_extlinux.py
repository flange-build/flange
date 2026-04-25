"""extlinux.conf 渲染与默认项原子切换测试（§4.5 / §4.6）。"""

from __future__ import annotations

import pytest

from builder.extlinux import (
    LabelSpec,
    NORMAL_LABEL,
    RECOVERY_LABEL,
    get_default_label,
    render_extlinux,
    set_default_label,
)
from builder.platforms.allwinnera733.boot import AllwinnerA733BootBuilder
from builder.platforms.rockchip.boot import RockchipBootBuilder


# ── render_extlinux 渲染逻辑 ────────────────────────────────────


class TestRenderExtlinux:
    def test_single_label(self):
        spec = LabelSpec(
            name=NORMAL_LABEL, kernel="/Image", fdt="/dtb/foo.dtb",
            append="root=LABEL=rootfs",
        )
        text = render_extlinux(NORMAL_LABEL, [spec])
        assert text.startswith(f"DEFAULT {NORMAL_LABEL}\n")
        assert "label flange" in text
        assert "  kernel /Image" in text
        assert "  fdt /dtb/foo.dtb" in text
        assert "  append root=LABEL=rootfs" in text

    def test_dual_labels_normal_default(self):
        normal = LabelSpec(name=NORMAL_LABEL, kernel="/Image", append="root=LABEL=rootfs")
        recovery = LabelSpec(name=RECOVERY_LABEL, kernel="/Image", append="root=LABEL=recovery")
        text = render_extlinux(NORMAL_LABEL, [normal, recovery])
        assert text.split("\n")[0] == f"DEFAULT {NORMAL_LABEL}"
        assert "label flange" in text
        assert "label flange-recovery" in text

    def test_default_must_match_label(self):
        normal = LabelSpec(name=NORMAL_LABEL, kernel="/Image")
        with pytest.raises(ValueError, match="不在 labels"):
            render_extlinux("nonexistent", [normal])

    def test_devicetree_directive(self):
        spec = LabelSpec(name=NORMAL_LABEL, kernel="/Image",
                         fdt="/dtb/x.dtb", fdt_directive="devicetree")
        text = render_extlinux(NORMAL_LABEL, [spec])
        assert "  devicetree /dtb/x.dtb" in text
        assert "  fdt /" not in text

    def test_fdtoverlays(self):
        spec = LabelSpec(name=NORMAL_LABEL, kernel="/Image",
                         fdt="/dtb/x.dtb",
                         fdtoverlays=["/dtb/overlay/a.dtbo", "/dtb/overlay/b.dtbo"])
        text = render_extlinux(NORMAL_LABEL, [spec])
        assert "  fdtoverlays /dtb/overlay/a.dtbo /dtb/overlay/b.dtbo" in text


# ── set_default_label / get_default_label ──────────────────────


class TestDefaultLabelSwitching:
    """§4.6: normal -> recovery -> normal 可往返。"""

    def _dual(self) -> str:
        normal = LabelSpec(name=NORMAL_LABEL, kernel="/Image", append="root=LABEL=rootfs")
        recovery = LabelSpec(name=RECOVERY_LABEL, kernel="/Image", append="root=LABEL=recovery")
        return render_extlinux(NORMAL_LABEL, [normal, recovery])

    def test_round_trip(self):
        text = self._dual()
        assert get_default_label(text) == NORMAL_LABEL

        switched = set_default_label(text, RECOVERY_LABEL)
        assert get_default_label(switched) == RECOVERY_LABEL

        back = set_default_label(switched, NORMAL_LABEL)
        assert get_default_label(back) == NORMAL_LABEL

        # 往返后内容除了 DEFAULT 行外应保持原样
        assert back == text

    def test_target_must_exist_as_label(self):
        text = self._dual()
        with pytest.raises(ValueError, match="不在 extlinux"):
            set_default_label(text, "missing-label")

    def test_inserts_default_when_missing(self):
        # 模拟一份缺少 DEFAULT 的旧 extlinux.conf
        text = (
            "label flange\n"
            "  kernel /Image\n"
            "  append root=LABEL=rootfs\n"
        )
        assert get_default_label(text) is None
        switched = set_default_label(text, NORMAL_LABEL)
        assert switched.startswith(f"DEFAULT {NORMAL_LABEL}\n")
        assert "label flange" in switched

    def test_multiple_default_raises(self):
        text = (
            "DEFAULT flange\n"
            "DEFAULT flange-recovery\n"
            "label flange\n  kernel /Image\n"
            "label flange-recovery\n  kernel /Image\n"
        )
        with pytest.raises(ValueError, match="DEFAULT"):
            set_default_label(text, NORMAL_LABEL)


# ── 平台 boot builder 集成 ──────────────────────────────────────


def _rk3566_cfg(*, recovery_enabled: bool) -> dict:
    return {
        "platform": "rockchip", "soc": "rk3566", "board": "test",
        "kernel": {"dts": "rk3566-test"},
        "boot": {
            "kernel_args": "console=ttyS2,1500000 loglevel=7",
            "default_overlays": [],
        },
        "recovery": {"enabled": recovery_enabled},
    }


class TestRockchipBootExtlinux:
    """§4.1: Rockchip boot builder 启用 recovery 时生成双 label。"""

    def test_normal_only_when_recovery_disabled(self):
        builder = RockchipBootBuilder(docker=None, source=None)
        text = builder._build_extlinux_conf(_rk3566_cfg(recovery_enabled=False), "rk3566-test.dtb")
        assert "label flange" in text
        assert RECOVERY_LABEL not in text

    def test_dual_labels_when_recovery_enabled(self):
        builder = RockchipBootBuilder(docker=None, source=None)
        text = builder._build_extlinux_conf(_rk3566_cfg(recovery_enabled=True), "rk3566-test.dtb")
        assert f"label {NORMAL_LABEL}" in text
        assert f"label {RECOVERY_LABEL}" in text

    def test_default_points_to_normal(self):
        builder = RockchipBootBuilder(docker=None, source=None)
        text = builder._build_extlinux_conf(_rk3566_cfg(recovery_enabled=True), "rk3566-test.dtb")
        assert get_default_label(text) == NORMAL_LABEL

    def test_recovery_label_root_uses_recovery_partition(self):
        """§4.5: recovery label 的 root 必须指向 recovery 分区。"""
        builder = RockchipBootBuilder(docker=None, source=None)
        text = builder._build_extlinux_conf(_rk3566_cfg(recovery_enabled=True), "rk3566-test.dtb")
        # 找到 recovery 段
        assert "label flange-recovery" in text
        # recovery append 必须把 root 指向 recovery 分区。我们用 PARTLABEL=
        # （GPT partition name）而非 ext4 LABEL=，避免 kernel 启动早期
        # 文件系统 probe 失败导致 "Waiting for root device" 死等。
        recovery_section = text.split("label flange-recovery", 1)[1]
        assert "root=PARTLABEL=recovery" in recovery_section
        # recovery append 应携带 mode 标记，便于设备端 recoveryctl 识别当前模式
        assert "flange.mode=recovery" in recovery_section


def _a733_cfg(*, recovery_enabled: bool) -> dict:
    return {
        "platform": "allwinnera733", "soc": "a733", "board": "test",
        "kernel": {"dts": "sun60i-a733-test"},
        "boot": {"dtb_filename": "sunxi.dtb",
                 "kernel_args": "earlyprintk=sunxi-uart,0x2500000 console=ttyAS0,115200"},
        "recovery": {"enabled": recovery_enabled},
    }


class TestA733BootExtlinux:
    """§4.2: Allwinner A733 boot builder 同样支持双 label。"""

    def test_dual_labels_when_recovery_enabled(self):
        builder = AllwinnerA733BootBuilder(docker=None, source=None)
        text = builder._build_extlinux_conf(_a733_cfg(recovery_enabled=True), "sunxi.dtb")
        assert f"label {NORMAL_LABEL}" in text
        assert f"label {RECOVERY_LABEL}" in text

    def test_recovery_uses_devicetree_directive(self):
        """A733 使用 devicetree 而非 fdt 关键字。"""
        builder = AllwinnerA733BootBuilder(docker=None, source=None)
        text = builder._build_extlinux_conf(_a733_cfg(recovery_enabled=True), "sunxi.dtb")
        assert "  devicetree /extlinux/sunxi.dtb" in text
        assert "  fdt /" not in text

    def test_normal_only_when_disabled(self):
        builder = AllwinnerA733BootBuilder(docker=None, source=None)
        text = builder._build_extlinux_conf(_a733_cfg(recovery_enabled=False), "sunxi.dtb")
        assert RECOVERY_LABEL not in text
