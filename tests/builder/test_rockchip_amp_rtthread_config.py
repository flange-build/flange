"""Rockchip RT-Thread AMP 基线配置测试。"""

from pathlib import Path

from builder.component_plan import create_component_plan
from builder.source import SourceManager
from builder.workspace import Target, WorkspaceContext
from builder.platforms.rockchip.amp import RockchipAmpBuilder


ROOT = Path(__file__).resolve().parents[2]
BASE_CONFIG = ROOT / "components/platform/rockchip/amp/rt-thread.config"
UART7_APP_CONFIG = ROOT / "components/app/rk3568_amp_uart7_rtt_demo/.config"


def test_rtthread_amp_base_config_owns_common_options():
    """Linux 单核 AMP 公共选项应由 flange 基线统一维护。"""
    config = BASE_CONFIG.read_text()

    assert "# CONFIG_RT_USING_SMP is not set" in config
    assert "CONFIG_RT_USING_RPMSG_LITE=y" in config
    assert "CONFIG_RT_USING_LINUX_RPMSG=y" in config
    assert "CONFIG_RT_USING_WITH_LINUX=y" in config


def test_rtthread_app_config_only_keeps_app_differences():
    """app 配置不应重复声明 AMP 基线选项。"""
    config = UART7_APP_CONFIG.read_text()

    assert "CONFIG_RT_USING_SMP" not in config
    assert "CONFIG_RT_USING_RPMSG_LITE" not in config
    assert "CONFIG_RT_USING_LINUX_RPMSG" not in config
    assert "CONFIG_RT_USING_WITH_LINUX" not in config


def test_uart7_app_disables_conflicting_bsp_defaults():
    """UART7 app 必须关闭冲突的 GMAC1 和 Linux 保留的 UART2。"""
    config = UART7_APP_CONFIG.read_text()

    assert "# CONFIG_RT_USING_GMAC1 is not set" in config
    assert "# CONFIG_RT_USING_UART2 is not set" in config


def test_rtthread_config_merge_order_is_bsp_base_then_app(tmp_path):
    """app 差异配置应能覆盖 BSP 默认值和 flange AMP 基线。"""
    merged = tmp_path / ".config"
    base = tmp_path / "base.config"
    app = tmp_path / "app.config"
    merged.write_text("CONFIG_RT_USING_SMP=y\n# CONFIG_FEATURE is not set\n")
    base.write_text("# CONFIG_RT_USING_SMP is not set\nCONFIG_FEATURE=y\n")
    app.write_text("# CONFIG_FEATURE is not set\n")

    RockchipAmpBuilder._merge_kconfig_fragment(merged, base)
    RockchipAmpBuilder._merge_kconfig_fragment(merged, app)

    assert merged.read_text().splitlines() == [
        "# CONFIG_RT_USING_SMP is not set",
        "# CONFIG_FEATURE is not set",
    ]


def test_rtthread_amp_cache_includes_sdk_and_flange_base_config(tmp_path):
    """完整 SDK 和平台基线均由计划声明，不再依赖手工强制重建。"""
    context = WorkspaceContext(ROOT, tmp_path, tmp_path / '.build', Target('board', 'default', 'release'))
    plan = create_component_plan('amp', {'board': 'board', 'platform': 'rockchip',
        'amp': {'enabled': True}, 'kernel': {}}, context, SourceManager(context=context))
    assert plan.path('amp:sdk') == ROOT / 'components/amp'
    assert plan.path('amp:platform') == ROOT / 'components/platform/rockchip/amp'


def test_serial_open_notifies_rockchip_uart_clock_control():
    """serial open/close 应对称通知 Rockchip UART 驱动管理时钟。"""
    serial_path = (
        "components/amp/rockchip/rt-thread/components/drivers/serial/serial.c"
    )
    serial = (ROOT / serial_path).read_text()
    uart_path = "components/amp/rockchip/rt-thread/bsp/rockchip/common/drivers/drv_uart.c"
    uart = (ROOT / uart_path).read_text()

    assert "serial->ops->control(serial, RT_DEVICE_CTRL_OPEN, RT_NULL);" in serial
    assert "serial->ops->control(serial, RT_DEVICE_CTRL_CLOSE, RT_NULL);" in serial
    assert "case RT_DEVICE_CTRL_OPEN:" in uart
    assert "case RT_DEVICE_CTRL_CLOSE:" in uart
