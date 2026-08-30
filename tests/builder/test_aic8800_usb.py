"""AIC8800 USB Wi-Fi 适配测试。"""

from pathlib import Path
from unittest.mock import MagicMock

from builder.cache import DEPENDENCY_GRAPH
from builder.config.registry import resolve_config
from builder.engine import _topo_sort
from builder.platforms.allwinnera733.kernel import AllwinnerA733KernelBuilder
from builder.platforms.allwinnera733.rootfs import AllwinnerA733RootfsBuilder


class RecordingDocker:
    """记录 rootfs 构建阶段发出的特权 Docker 命令。"""

    def __init__(self):
        self.privileged_commands: list[list[str]] = []

    def run_privileged(self, cmd: list[str]):
        self.privileged_commands.append(cmd)


def test_aic8800_fragment位于radxa_custom之后且case_fix之前():
    """AIC8800 覆盖必须晚于 Radxa 配置，早于最终兼容性修正。"""
    config = resolve_config("radxa-cubie-a7z", "default", "release")
    defconfigs = config["kernel"]["defconfig"]

    assert "aic8800_wlan.config" in defconfigs
    assert defconfigs.index("radxa_custom.config") < defconfigs.index(
        "aic8800_wlan.config"
    )
    assert defconfigs.index("aic8800_wlan.config") < defconfigs.index(
        "case_insensitive_fix.config"
    )


def test_aic8800_fragment启用usb模块(tmp_path):
    """生成的 fragment 应启用 USB 驱动并关闭 SDIO 模式。"""
    configs_dir = tmp_path / "arch" / "arm64" / "configs"
    configs_dir.mkdir(parents=True)
    builder = AllwinnerA733KernelBuilder(docker=MagicMock(), source=MagicMock())

    builder._write_aic8800_wlan_override(tmp_path)

    content = (configs_dir / "aic8800_wlan.config").read_text()
    expected_lines = [
        "CONFIG_AIC_WLAN_SUPPORT=y",
        "CONFIG_AIC8800_USB=y",
        "# CONFIG_AIC8800_SDIO is not set",
        "CONFIG_AIC_LOADFW_SUPPORT=m",
        "CONFIG_AIC8800_WLAN_SUPPORT=m",
        "# CONFIG_AIC_BTUSB_SUPPORT is not set",
    ]
    for line in expected_lines:
        assert line in content


def test_aic8800_usb_makefile固件路径指向radxa固件目录(tmp_path):
    """USB Wi-Fi 子模块硬编码的固件路径应被修正到 Radxa USB 固件目录。"""
    makefile = (
        tmp_path
        / "drivers"
        / "net"
        / "wireless"
        / "aic8800"
        / "usb"
        / "aic8800_fdrv"
        / "Makefile"
    )
    makefile.parent.mkdir(parents=True)
    makefile.write_text(
        'CONFIG_AIC_FW_PATH = "/vendor/etc/firmware"\n'
        '# CONFIG_AIC_FW_PATH = "/vendor/etc/firmware"\n'
    )
    builder = AllwinnerA733KernelBuilder(docker=MagicMock(), source=MagicMock())

    builder._write_aic8800_usb_firmware_path_override(tmp_path)

    lines = makefile.read_text().splitlines()
    assert 'CONFIG_AIC_FW_PATH = "/lib/firmware/aic8800_fw/USB"' in lines
    assert '# CONFIG_AIC_FW_PATH = "/vendor/etc/firmware"' in lines
    assert not any(
        line == 'CONFIG_AIC_FW_PATH = "/vendor/etc/firmware"'
        for line in lines
    )


def test_allwinnera733_rootfs安装模块和usb诊断工具():
    """rootfs 默认包必须包含模块工具、lsusb、ifconfig 和 Wi-Fi supplicant。"""
    config = resolve_config("radxa-cubie-a7z", "default", "release")
    packages = config["rootfs"]["packages"]

    assert "kmod" in packages
    assert "usbutils" in packages
    assert "net-tools" in packages
    assert "wpasupplicant" in packages


def test_radxa_cubie_a7z不保留无消费者wifi开关():
    config = resolve_config("radxa-cubie-a7z", "default", "release")

    assert "wifi" not in config


def test_radxa_cubie_a7z依赖radxa_aic8800_usb固件():
    """A7Z rootfs 应从 Radxa aic8800 仓库安装 D80 USB 固件。"""
    config = resolve_config("radxa-cubie-a7z", "default", "release")
    extra_firmware = config["rootfs"]["extra_firmware"]

    radxa_entries = [
        fw for fw in extra_firmware
        if fw["name"] == "radxa-aic8800"
    ]

    assert len(radxa_entries) == 2
    source = config["sources"][radxa_entries[0]["source"]["name"]]
    assert source == {
        "url": "https://github.com/radxa-pkg/aic8800.git",
        "commit": "7f42b22913b462ab6c658dfc075bae1dbfe9a71a",
    }
    assert {
        fw["source"]["subpath"] for fw in radxa_entries
    } == {
        "src/USB/driver_fw/fw/aic8800D80",
        "src/USB/driver_fw/fw",
    }
    assert all(
        fw["dest"] == "lib/firmware/aic8800_fw/USB"
        for fw in radxa_entries
    )

    flat_entry = next(
        fw for fw in radxa_entries
        if fw["source"]["subpath"].endswith("aic8800D80")
    )
    nested_entry = next(
        fw for fw in radxa_entries
        if fw["source"]["subpath"] == "src/USB/driver_fw/fw"
    )

    assert "fmacfw_8800d80_u02.bin" in flat_entry["files"]
    assert "fw_patch_8800d80_u02_ext0.bin" in flat_entry["files"]
    assert "aic8800D80/aic_userconfig_8800d80.txt" in nested_entry["files"]


def test_radxa_cubie_a7z_overlay声明usb模块加载顺序():
    """板级 overlay 应先加载 firmware helper，再加载 Wi-Fi 驱动。"""
    overlay = Path("components/board/radxa-cubie-a7z/overlay")
    modules_load = overlay / "etc" / "modules-load.d" / "aic8800.conf"
    modprobe = overlay / "etc" / "modprobe.d" / "aic8800.conf"

    modules = [
        line.strip()
        for line in modules_load.read_text().splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]

    assert modules == ["aic_load_fw", "aic8800_fdrv"]
    assert (
        "options aic_load_fw aic_fw_path=/lib/firmware/aic8800_fw/USB"
        in modprobe.read_text()
    )


def test_rootfs安装kernel_modules到lib_modules(monkeypatch, tmp_path):
    """rootfs 阶段应拷贝 kernel modules_install 产物到 /lib/modules。"""
    monkeypatch.chdir(tmp_path)
    modules_src = (
        tmp_path
        / ".build"
        / "target"
        / "radxa-cubie-a7z"
        / "default"
        / "release"
        / "kernel"
        / "modules"
        / "lib"
        / "modules"
    )
    (modules_src / "5.15.147+" / "kernel" / "drivers" / "net").mkdir(
        parents=True
    )
    rootfs_dir = tmp_path / "rootfs"
    docker = RecordingDocker()
    builder = AllwinnerA733RootfsBuilder(docker=docker, source=MagicMock())
    # 产物目录的锚点是 engine 注入的 cache，不是 cwd —— 否则只有在仓库根
    # 启动时才对。
    cache = MagicMock()
    cache.target_dir = (
        tmp_path / ".build/target/radxa-cubie-a7z/default/release")
    builder.cache = cache

    builder._install_kernel_modules(
        rootfs_dir,
        {
            "board": "radxa-cubie-a7z",
            "product": "default",
            "variant": "release",
        },
    )

    assert docker.privileged_commands == [
        [
            "cp", "-a",
            f"{cache.target_dir}/kernel/modules/lib/modules/.",
            str(rootfs_dir / "lib" / "modules"),
        ]
    ]


def test_rootfs依赖kernel以获取模块产物():
    """rootfs 必须依赖 kernel，确保模块先安装到 target 目录。"""
    order = _topo_sort(DEPENDENCY_GRAPH, "rootfs")

    assert "kernel" in DEPENDENCY_GRAPH["rootfs"]
    assert order.index("kernel") < order.index("rootfs")
