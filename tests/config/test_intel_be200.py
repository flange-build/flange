"""intel-be200 硬件特性包：板卡无关性、backport 构建前准备脚本与蓝牙驱动测试。"""

import json
import os
import shutil
import subprocess
from pathlib import Path

import _jsonnet
import pytest

from builder.config.registry import discover_boards, resolve_config
from builder.paths import COMPONENTS_ROOT, PROJECT_ROOT


PACKAGE_ROOT = PROJECT_ROOT / "components/packages/intel-be200"
PREPARE = PACKAGE_ROOT / "scripts/prepare-backport.sh"
SHIM_GUARD = "#if LINUX_VERSION_IS_LESS(6,2,0)\nstatic inline int timer_delete(struct timer_list *timer)"
BACKPORT_TIMER_H = (
    "#ifndef _BACKPORT_TIMER_H\n"
    + SHIM_GUARD
    + "\n{\n\treturn del_timer(timer);\n}\n#endif\n#endif\n"
)


BT_KCONFIG = {
    "CONFIG_BT_HCIBTUSB": "m",
    "CONFIG_BT_HCIUART_INTEL": "n",
    "CONFIG_BT_HCIUART_AG6XX": "n",
}


def _package_on(platform: str) -> dict:
    """把包配置叠加到只含平台身份的最小配置上求值。"""
    snippet = (
        f"{{ platform: {json.dumps(platform)}, kernel: {{}}, rootfs: {{}}, sources: {{}} }}"
        " + (import 'packages/intel-be200/config.jsonnet')"
    )
    return json.loads(
        _jsonnet.evaluate_snippet("test", snippet, jpathdir=[str(COMPONENTS_ROOT)])
    )


def test_rockchip平台额外关闭WL_ROCKCHIP():
    config = _package_on("rockchip")["kernel"]["config"]
    assert config == {
        "CONFIG_CFG80211": "m",
        "CONFIG_MAC80211": "m",
        "CONFIG_IWLWIFI": "n",
        **BT_KCONFIG,
        "CONFIG_WL_ROCKCHIP": "n",
    }


@pytest.mark.parametrize("platform", ["qualcommqcs6490", "amlogic", "allwinnera733"])
def test_非rockchip平台不带平台专有Kconfig(platform):
    config = _package_on(platform)
    assert config["kernel"]["config"] == {
        "CONFIG_CFG80211": "m",
        "CONFIG_MAC80211": "m",
        "CONFIG_IWLWIFI": "n",
        **BT_KCONFIG,
    }
    module = config["kernel"]["oot_modules"][0]
    # 交叉编译参数全部来自平台模板变量，不写死架构。
    assert "ARCH={arch}" in module["make_args"]
    assert "CROSS_COMPILE={cross_compile}" in module["make_args"]


def test_固件按固定tag下载并校验():
    firmware = _package_on("rockchip")["rootfs"]["extra_firmware"]
    assert {entry["filename"] for entry in firmware} == {
        "iwlwifi-gl-c0-fm-c0-101.ucode",
        "iwlwifi-gl-c0-fm-c0.pnvm",
        "ibt-0291-0291.sfi",
        "ibt-0291-0291.ddc",
    }
    dests = {entry["filename"]: entry["dest"] for entry in firmware}
    assert dests["ibt-0291-0291.sfi"] == "lib/firmware/intel"
    for entry in firmware:
        assert entry["url"].endswith("?h=20261019")
        assert len(entry["sha256"]) == 64


def test_驱动补丁随包携带():
    patches = sorted((PACKAGE_ROOT / "scripts/patches").glob("*.patch"))
    assert [p.name for p in patches] == ["0001-iwlwifi-pcie-sync-rb-before-cpu-access.patch"]
    assert "dma_sync_single_for_cpu" in patches[0].read_text()


def test_启用包的板保留SoC层固件与配置():
    boards = discover_boards()
    config = resolve_config("embedfire-lubancat-5", "default", "debug", boards=boards)
    names = [entry["name"] for entry in config["rootfs"]["extra_firmware"]]
    assert names[0] == "mali-csf"
    assert "intel-be200" in config["packages"]
    assert config["kernel"]["config"]["CONFIG_WL_ROCKCHIP"] == "n"
    assert config["kernel"]["oot_sources"]["backport-iwlwifi"] == {
        "source": {"name": "backport-iwlwifi"}
    }


@pytest.fixture
def fake_tree(tmp_path):
    """构造最小内核树、backport 树，并用桩替换 make。"""
    kernel = tmp_path / "kernel"
    (kernel / "include/linux").mkdir(parents=True)
    (kernel / ".config").write_text("CONFIG_CFG80211=m\nCONFIG_MAC80211=m\n")
    (kernel / "include/linux/timer.h").write_text("/* 无 timer_delete */\n")
    backport = tmp_path / "backport"
    (backport / "backport-include/linux").mkdir(parents=True)
    (backport / "backport-include/linux/timer.h").write_text(BACKPORT_TIMER_H)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    make = bin_dir / "make"
    make.write_text(f"#!/bin/sh\necho \"$@\" > {tmp_path}/make-args\n")
    make.chmod(0o755)
    # 驱动补丁针对真实 backport 源码，由实际构建验证；这里只测脚本逻辑。
    scripts = tmp_path / "scripts"
    (scripts / "patches").mkdir(parents=True)
    shutil.copy(PREPARE, scripts / PREPARE.name)
    return kernel, backport, bin_dir


def _prepare(kernel, backport, bin_dir):
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"}
    return subprocess.run(
        ["bash", str(backport.parent / "scripts" / PREPARE.name), str(backport), str(kernel), "arm64", "aarch64-linux-gnu-"],
        env=env, capture_output=True, text=True,
    )


def test_内核未提供timer_delete时保留兼容层(fake_tree, tmp_path):
    kernel, backport, bin_dir = fake_tree
    result = _prepare(kernel, backport, bin_dir)
    assert result.returncode == 0, result.stderr
    assert SHIM_GUARD in (backport / "backport-include/linux/timer.h").read_text()
    assert "defconfig-iwlwifi-public" in (tmp_path / "make-args").read_text()


def test_内核已提供timer_delete时去掉兼容层且幂等(fake_tree):
    kernel, backport, bin_dir = fake_tree
    (kernel / "include/linux/timer.h").write_text(
        "extern int timer_delete(struct timer_list *timer);\n"
    )
    for _ in range(2):
        result = _prepare(kernel, backport, bin_dir)
        assert result.returncode == 0, result.stderr
    shim = (backport / "backport-include/linux/timer.h").read_text()
    assert SHIM_GUARD not in shim
    assert shim.count("#if 0 /* 目标内核已提供 timer_delete() */") == 1


@pytest.mark.parametrize("symbol", ["CFG80211", "MAC80211"])
def test_cfg80211内建时拒绝构建(fake_tree, symbol):
    kernel, backport, bin_dir = fake_tree
    (kernel / ".config").write_text(f"CONFIG_{symbol}=y\n")
    result = _prepare(kernel, backport, bin_dir)
    assert result.returncode == 1
    assert f"CONFIG_{symbol}=y" in result.stderr


BT_DRIVER = PACKAGE_ROOT / "driver/bt"


@pytest.fixture
def fake_bt(tmp_path):
    """构造含 btusb/btintel 的最小内核树，并复制蓝牙驱动目录。"""
    kernel = tmp_path / "kernel"
    (kernel / "drivers/bluetooth").mkdir(parents=True)
    (kernel / ".config").write_text("CONFIG_BT_HCIBTUSB=m\nCONFIG_BT_INTEL=m\n")
    for name in ("btusb.c", "btintel.c", "btintel.h"):
        (kernel / "drivers/bluetooth" / name).write_text(f"/* {name} */\n")
    driver = tmp_path / "bt"
    shutil.copytree(BT_DRIVER, driver, ignore=shutil.ignore_patterns(".gitignore"))
    return kernel, driver


def _bt_sources(kernel, driver):
    return subprocess.run(
        ["make", "-C", str(driver), "bt-sources", f"KSRC={kernel}", f"M={driver}"],
        capture_output=True, text=True,
    )


def test_蓝牙驱动随包编译btusb与btintel():
    config = resolve_config(
        "embedfire-lubancat-5", "default", "debug", boards=discover_boards()
    )
    modules = [m for m in config["kernel"]["oot_modules"] if m["dir"] == str(BT_DRIVER)]
    assert [Path(ko).name for ko in modules[0]["ko_pattern"]] == ["btusb.ko", "btintel.ko"]
    assert "bluez" in config["rootfs"]["packages"]
    patch = (BT_DRIVER / "0001-bluetooth-support-intel-gale-peak-8087-0036.patch").read_text()
    assert "USB_DEVICE(0x8087, 0x0036)" in patch
    assert patch.count("+\tcase 0x1c:") == 3


@pytest.mark.parametrize("symbol", ["BT_HCIBTUSB", "BT_INTEL"])
def test_蓝牙模块内建时拒绝构建(fake_bt, symbol):
    kernel, driver = fake_bt
    (kernel / ".config").write_text(
        "CONFIG_BT_HCIBTUSB=m\nCONFIG_BT_INTEL=m\n".replace(f"CONFIG_{symbol}=m", f"CONFIG_{symbol}=y")
    )
    result = _bt_sources(kernel, driver)
    assert result.returncode != 0
    assert f"CONFIG_{symbol}=m" in result.stderr


def test_内核已支持0036时不打补丁(fake_bt):
    kernel, driver = fake_bt
    native = "{ USB_DEVICE(0x8087, 0x0036), .driver_info = BTUSB_INTEL_COMBINED },\n"
    (kernel / "drivers/bluetooth/btusb.c").write_text(native)
    for _ in range(2):
        result = _bt_sources(kernel, driver)
        assert result.returncode == 0, result.stderr
    assert (driver / "btusb.c").read_text() == native
    assert (driver / "btintel.h").is_file()


AFFINITY = PACKAGE_ROOT / "runtime/bin/iwlwifi-irq-affinity"


def _fake_system(tmp_path, capacities):
    """构造假 /proc 与 /sys：3 个 iwlwifi 中断外加 1 个无关中断。"""
    proc = tmp_path / "proc"
    sys_cpu = tmp_path / "cpu"
    sys_cpu.mkdir()
    (sys_cpu / "online").write_text(f"0-{len(capacities) - 1}\n")
    for cpu, capacity in enumerate(capacities):
        (sys_cpu / f"cpu{cpu}").mkdir()
        if capacity is not None:
            (sys_cpu / f"cpu{cpu}/cpu_capacity").write_text(f"{capacity}\n")
    interrupts = ["           CPU0       CPU1"]
    for irq, name in [(130, "iwlwifi:default_queue"), (131, "iwlwifi:queue_1"),
                      (40, "eth0"), (132, "iwlwifi:queue_2")]:
        (proc / f"irq/{irq}").mkdir(parents=True)
        (proc / f"irq/{irq}/smp_affinity_list").write_text("0-7\n")
        interrupts.append(f" {irq}:   0   0   ITS-MSI 1 Edge      {name}")
    (proc / "interrupts").write_text("\n".join(interrupts) + "\n")
    env = {**os.environ, "PROC_ROOT": str(proc), "SYS_CPU_ROOT": str(sys_cpu)}
    result = subprocess.run(["bash", str(AFFINITY)], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return {
        irq: (proc / f"irq/{irq}/smp_affinity_list").read_text().strip()
        for irq in (130, 131, 132, 40)
    }


def test_大小核上iwlwifi中断轮流绑到大核(tmp_path):
    # RK3588：cpu0-3 A55(405)、cpu4-5 A76(1003)、cpu6-7 A76(1024)
    affinity = _fake_system(tmp_path, [405] * 4 + [1003, 1003, 1024, 1024])
    assert [affinity[irq] for irq in (130, 131, 132)] == ["4", "5", "6"]
    assert affinity[40] == "0-7"


def test_同构CPU无cpu_capacity时用全部在线核(tmp_path):
    affinity = _fake_system(tmp_path, [None, None])
    assert [affinity[irq] for irq in (130, 131, 132)] == ["0", "1", "0"]


def test_NetworkManager配置排在Ubuntu节能默认配置之后():
    conf = PACKAGE_ROOT / "runtime/NetworkManager/flange-intel-be200.conf"
    assert conf.name > "default-wifi-powersave-on.conf"
    text = conf.read_text()
    assert "match-device=driver:iwlwifi" in text
    assert "wifi.powersave=2" in text


def test_鲁班猫5启用运行时包与schedutil():
    boards = discover_boards()
    for board in ("embedfire-lubancat-5", "embedfire-lubancat-5-v2"):
        config = resolve_config(board, "default", "release", boards=boards)
        assert "flange-intel-be200" in config["rootfs"]["custom_packages"]
        assert config["kernel"]["config"]["CONFIG_CPU_FREQ_DEFAULT_GOV_SCHEDUTIL"] == "y"
    l3 = resolve_config("embedfire-lubancat-3", "default", "release", boards=boards)
    assert "CONFIG_CPU_FREQ_DEFAULT_GOV_SCHEDUTIL" not in l3["kernel"]["config"]
