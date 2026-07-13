"""RK3506 CPU2 RT-Thread UART4 + RPMsg app 内容契约测试。"""

from pathlib import Path

from builder.app_spec import load_spec
from builder.platforms.rockchip.amp import RockchipAmpBuilder


DEMO = Path("components/app/rk3506_amp_uart4_rtt_demo")


def test_demo_metadata_selects_armhf_rk3506_scons_overlay():
    spec = load_spec(DEMO)

    assert spec.app.name == "rk3506_amp_uart4_rtt_demo"
    assert spec.app.type == "amp"
    assert spec.app.arch == ["armhf"]
    assert spec.build.system == "scons"
    assert spec.build.options["bsp"] == "rk3506-32"
    assert (DEMO / "applications/SConscript").is_file()


def test_demo_kconfig_is_single_core_uart4_rpmsg_with_msh():
    fragment = (DEMO / ".config").read_text()

    assert "# CONFIG_RT_USING_SMP is not set" in fragment
    assert 'CONFIG_RT_CONSOLE_DEVICE_NAME="uart4"' in fragment
    assert "CONFIG_RT_USING_UART4=y" in fragment
    assert "CONFIG_RT_USING_RPMSG_LITE=y" in fragment
    assert "CONFIG_RT_USING_LINUX_RPMSG=y" in fragment
    assert "CONFIG_RT_USING_WITH_LINUX=y" in fragment
    assert "CONFIG_RT_USING_MSH=y" in fragment


def test_uart4_overlay_locks_rm_io27_28_and_1500000_8n1_contract():
    source = (DEMO / "applications/board_uart4.c").read_text()
    serial_header = Path(
        "components/amp/rockchip/rt-thread/components/drivers/"
        "include/drivers/serial.h"
    ).read_text()

    assert "GPIO_BANK1, GPIO_PIN_C2, RMIO_UART4_TX" in source
    assert "GPIO_BANK1, GPIO_PIN_C3, RMIO_UART4_RX" in source
    assert ".baud_rate = UART_BR_1500000" in source
    assert "DATA_BITS_8" in serial_header
    assert "STOP_BITS_1" in serial_header
    assert "PARITY_NONE" in serial_header


def test_rpmsg_demo_consumes_generated_rk3506_profile_and_echoes_rx_length():
    source = (DEMO / "applications/main.c").read_text()

    assert '#include "flange_amp_runtime.h"' in source
    assert "FLANGE_AMP_LINK_ID" in source
    assert "FLANGE_AMP_EPT_ADDR" in source
    assert "FLANGE_AMP_EPT_NAME" in source
    assert "FLANGE_AMP_MAILBOX_IRQ" not in source
    assert "rpmsg_lite_wait_for_link_up(instance, RL_BLOCK)" in source
    assert "rpmsg_ns_announce(" in source
    assert "&rx_len" in source
    assert "source, rx, rx_len, RL_BLOCK" in source
    assert "HAL_GIC_Init" not in source
    assert "MBOX0_CH3_A2B_IRQn" not in source


def test_generated_rk3506_profile_has_vendor_endpoint_and_no_rk3568_workaround(
    tmp_path,
):
    runtime = {
        "link_id": 0x02,
        "mailbox_irq": 176,
        "endpoint_address": 0x3003,
        "endpoint_name": "rpmsg-ap3-ch0",
        "gic_profile": "rk3506-stock-mailbox2",
    }

    header = RockchipAmpBuilder._write_runtime_header(tmp_path, runtime)
    text = header.read_text()

    assert "FLANGE_AMP_LINK_ID 0x2U" in text
    assert "FLANGE_AMP_EPT_ADDR 0x3003U" in text
    assert 'FLANGE_AMP_EPT_NAME "rpmsg-ap3-ch0"' in text
    assert "FLANGE_AMP_MAILBOX_IRQ" not in text
    assert "FLANGE_AMP_NEEDS_RK3568_GIC_WORKAROUND" not in text
