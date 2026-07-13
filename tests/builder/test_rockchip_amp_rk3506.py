"""RK3506/RK3568 AMP FIT、DTS closure 与 runtime profile 测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from builder.config.registry import resolve_config
from builder.platforms.rockchip.amp import RockchipAmpBuilder


RK3506_ITS = Path(
    "components/amp/rockchip/rt-thread/bsp/rockchip/"
    "rk3506-32/Image/amp_linux.its"
)
RK3568_ITS = Path(
    "components/amp/rockchip/rt-thread/bsp/rockchip/"
    "rk3568-32/Image/amp_linux.its"
)
RK3568_HAL_ITS = Path(
    "components/amp/rockchip/hal/project/rk3568/Image/amp_linux.its"
)


def _memory() -> dict:
    return {
        "cpu": 2,
        "cpu_base": 0x03E00000,
        "dram_size": 0x00100000,
        "sram_base": 0xFFF80000,
        "sram_size": 0x0000C000,
        "shmem_base": 0x03B00000,
        "shmem_size": 0x00100000,
        "rpmsg_base": 0x03C00000,
        "rpmsg_size": 0x00200000,
    }


def _runtime() -> dict:
    return {
        "amp_mpidr": 0xF02,
        "linux_mpidr": 0xF00,
        "linux_arch": "arm",
        "linux_load": 0x00900000,
        "cpu_delete": "cpu@f02",
        "link_id": 0x02,
        "mailboxes": ["mailbox0", "mailbox2"],
        "mailbox_irq": 176,
        "endpoint_address": 0x3003,
        "endpoint_name": "rpmsg-ap3-ch0",
        "gic_profile": "rk3506-stock-mailbox2",
        "firmware_reserved_in_dts": True,
        "fit_requires_sram": True,
    }


def test_rk3506_fit_renderer_only_changes_amp2_node():
    original = RK3506_ITS.read_text()

    rendered = RockchipAmpBuilder._render_fit_its(
        original, 2, _memory(), _runtime(), "firmware2.bin")

    amp_start, amp_end = RockchipAmpBuilder._fit_node_span(rendered, "amp2")
    amp2 = rendered[amp_start:amp_end]
    linux_start, linux_end = RockchipAmpBuilder._fit_node_span(
        rendered, "linux")
    linux = rendered[linux_start:linux_end]
    assert 'data = /incbin/("firmware2.bin");' in amp2
    assert "load = <0x3e00000>;" in amp2
    assert "size = <0x100000>;" in amp2
    assert "srambase = <0xfff80000>;" in amp2
    assert "sramsize = <0xc000>;" in amp2
    assert "load         = <0x00900000>" in linux
    assert "0x3e00000" not in linux


def test_fit_renderer_fails_when_target_cpu_node_is_missing():
    with pytest.raises(ValueError, match="amp3.*实际 0"):
        RockchipAmpBuilder._render_fit_its(
            RK3506_ITS.read_text(), 3, _memory(), _runtime(), "rtt3.bin")


def test_rk3506_fit_static_structure_matches_runtime_profile():
    rendered = RockchipAmpBuilder._render_fit_its(
        RK3506_ITS.read_text(), 2, _memory(), _runtime(), "rtt2.bin")

    # _render_fit_its 内部已执行完整 assert；再锁定用户可观察的核心结构。
    assert 'loadables = "amp2";' in rendered
    assert 'arch         = "arm"' in rendered
    assert "cpu          = <0xf02>" in rendered
    assert "cpu          = <0xf00>" in rendered
    assert "load         = <0x00900000>" in rendered


def test_rk3506_rtthread_bsp_mapping_exists():
    builder = RockchipAmpBuilder(docker=None, source=None)
    bsp = builder._rtt_bsp_dir("rk3506")

    assert bsp.as_posix().endswith("rk3506-32")
    assert (bsp / "SConstruct").is_file()


def test_runtime_header_only_contains_app_consumed_profile_fields(tmp_path):
    header = RockchipAmpBuilder._write_runtime_header(tmp_path, _runtime())
    text = header.read_text()

    assert "FLANGE_AMP_LINK_ID 0x2U" in text
    assert "FLANGE_AMP_EPT_ADDR 0x3003U" in text
    assert 'FLANGE_AMP_EPT_NAME "rpmsg-ap3-ch0"' in text
    assert "FLANGE_AMP_MAILBOX_IRQ" not in text
    assert "FLANGE_AMP_NEEDS_RK3568_GIC_WORKAROUND" not in text
    assert "222" not in text


def test_rk3568_runtime_profile_keeps_existing_workaround_and_fit():
    config = resolve_config("tspi-rk3566", "amp-rtt", "release")
    runtime = config["amp"]["runtime"]
    memory = config["amp"]["memory"]

    rendered = RockchipAmpBuilder._render_fit_its(
        RK3568_ITS.read_text(), 3, memory, runtime, "rtt3.bin")

    assert runtime["link_id"] == 0x10
    assert runtime["mailbox_irq"] == 222
    assert runtime["gic_profile"] == "rk3568-incremental-intid222"
    assert "load = <0x7000000>;" in rendered
    assert 'loadables = "amp3";' in rendered

    hal_rendered = RockchipAmpBuilder._render_fit_its(
        RK3568_HAL_ITS.read_text(), 3, memory, runtime, "hal3.bin")
    linux_start, linux_end = RockchipAmpBuilder._fit_node_span(
        hal_rendered, "linux")
    # RK3568 HAL 模板的 Linux load/load_c 不属于 amp3，必须原样保留。
    linux = hal_rendered[linux_start:linux_end]
    assert "load         = <0x03880000>" in linux
    assert "load_c       = <0x04080000>" in linux


def _synthetic_dts_tree(tmp_path: Path) -> tuple[Path, str]:
    kernel = tmp_path / "kernel"
    dts_root = kernel / "arch/arm/boot/dts"
    dts_root.mkdir(parents=True)
    (dts_root / "rk3506-amp.dtsi").write_text(
        "/ {\n"
        "  cpus { /delete-node/ cpu@f02; };\n"
        "  rockchip-amp { amp-irqs = <176>; };\n"
        "  rpmsg@3c00000 {\n"
        "    mboxes = <&mailbox0 0 &mailbox2 0>;\n"
        "    rockchip,link-id = <0x02>;\n"
        "    reg = <0x3c00000 0x20000>;\n"
        "  };\n"
        "};\n"
        "&reserved_memory {\n"
        "  shmem@3b00000 { reg = <0x03b00000 0x100000>; };\n"
        "  rpmsg@3c00000 { reg = <0x03c00000 0x100000>; };\n"
        "  rpmsg-dma@3d00000 { reg = <0x03d00000 0x100000>; };\n"
        "  amp@3e00000 { reg = <0x03e00000 0x100000>; no-map; };\n"
        "  mcu@fff80000 { reg = <0xfff80000 0xc000>; };\n"
        "};\n"
    )
    dts_name = "rk3506b-test-amp"
    (dts_root / f"{dts_name}.dts").write_text(
        '/dts-v1/;\n#include "rk3506-amp.dtsi"\n')
    return kernel, dts_name


def _dts_config(tmp_path: Path) -> dict:
    kernel, dts = _synthetic_dts_tree(tmp_path)
    return {
        "board": "test",
        "kernel": {
            "local_path": str(kernel),
            "arch": "arm",
            "dts_dir": "",
            "dts": dts,
        },
        "amp": {
            "soc_project": "rk3506",
            "memory": _memory(),
            "runtime": _runtime(),
        },
    }


def test_arm32_dts_include_closure_matches_memory_and_runtime(tmp_path):
    builder = RockchipAmpBuilder(docker=None, source=None)

    builder._assert_dts_consistency(_dts_config(tmp_path))


def test_arm32_dts_missing_firmware_reservation_is_rejected(tmp_path):
    config = _dts_config(tmp_path)
    dtsi = Path(config["kernel"]["local_path"]) / (
        "arch/arm/boot/dts/rk3506-amp.dtsi"
    )
    dtsi.write_text(
        dtsi.read_text().replace(
            "  amp@3e00000 { reg = <0x03e00000 0x100000>; no-map; };\n",
            "",
        )
    )
    builder = RockchipAmpBuilder(docker=None, source=None)

    with pytest.raises(ValueError, match="firmware"):
        builder._assert_dts_consistency(config)


def test_arm32_dts_link_id_mismatch_is_rejected(tmp_path):
    config = _dts_config(tmp_path)
    config["amp"]["runtime"]["link_id"] = 0x10
    builder = RockchipAmpBuilder(docker=None, source=None)

    with pytest.raises(ValueError, match="link-id"):
        builder._assert_dts_consistency(config)
