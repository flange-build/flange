"""Orange Pi CM4 RT-Thread AMP Swift I2C demo 静态接线测试。"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEMO = ROOT / "components/app/rk3568_amp_uart7_rtt_demo"


def test_swift_package_splits_shell_and_i2c_targets():
    package = (DEMO / "Package.swift").read_text()

    assert 'name: "RtThreadShell"' in package
    assert 'name: "RtThreadI2C"' in package
    assert 'name: "AmpLogic"' in package
    assert 'dependencies: ["RtThreadI2C", "RtThreadShell"]' in package


def test_swift_i2c_command_registered_by_c_bridge():
    bridge = (DEMO / "applications/swift_rtthread_bridge.c").read_text()
    header = (DEMO / "include/swift_bridge.h").read_text()

    assert "MSH_CMD_EXPORT(swift_i2c" in bridge
    assert "swift_i2c_command(argc, argv)" in bridge
    assert "int32_t swift_i2c_command(int32_t argc, char **argv);" in header
    assert "rtt_shell_" not in bridge
    assert "rtt_i2c_" not in bridge
    assert "rt_i2c_transfer" not in bridge
    assert "rtt_shell_" not in header
    assert "rtt_i2c_" not in header


def test_swift_targets_bind_rtthread_symbols_directly():
    shell = (DEMO / "Sources/RtThreadShell/Shell.swift").read_text()
    i2c = (DEMO / "Sources/RtThreadI2C/I2C.swift").read_text()
    app_yaml = (DEMO / "app.yaml").read_text()

    assert '@_silgen_name("rt_kputs")' in shell
    assert '@_silgen_name("rt_i2c_bus_device_find")' in i2c
    assert '@_silgen_name("rt_i2c_transfer")' in i2c
    assert "rtt_shell_" not in app_yaml
    assert "rtt_i2c_" not in app_yaml
    assert "- rt_kputs" in app_yaml
    assert "- rt_i2c_bus_device_find" in app_yaml
    assert "- rt_i2c_transfer" in app_yaml


def test_swift_i2c_command_uses_typed_throws_for_error_flow():
    logic = (DEMO / "Sources/AmpLogic/AmpLogic.swift").read_text()

    assert "throws(CommandFailure)" in logic
    assert "private enum CommandFailure: Error" in logic
    assert "writeFailure(error)" in logic


def test_swift_i2c_demo_enables_i2c0_fragment():
    config = (DEMO / ".config").read_text()

    assert 'CONFIG_RT_CONSOLE_DEVICE_NAME="uart7"' in config
    assert "CONFIG_RT_USING_I2C=y" in config
    assert "CONFIG_RT_USING_I2C0=y" in config
    assert "CONFIG_RT_USING_UART7=y" in config


def test_swift_i2c_command_usage_documented():
    doc = (ROOT / "components/board/orangepi-cm4/docs/amp.md").read_text()

    assert "swift_i2c <i2cN|N> <addr> w <byte...>" in doc
    assert "swift_i2c <i2cN|N> <addr> r <len>" in doc
    assert "swift_i2c <i2cN|N> <addr> wr <byte...> -- <len>" in doc
