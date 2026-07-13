"""adbd systemd 服务配置测试。"""

from pathlib import Path


SERVICE = Path("components/app/adbd/systemd/usbdevice.service")
SCRIPT = Path("components/app/adbd/scripts/usbdevice")


def test_adbd_service_exports_term_xterm():
    """adbd 服务必须导出 TERM=xterm，保证 adb shell 具备终端类型。"""

    assert "Environment=TERM=xterm" in SERVICE.read_text().splitlines()


def test_adbd_service_waits_for_modules_and_configfs():
    """gadget 服务必须在模块加载与 ConfigFS 挂载之后启动。"""
    lines = SERVICE.read_text(encoding="utf-8").splitlines()
    after = next(line for line in lines if line.startswith("After="))

    assert "Requires=sys-kernel-config.mount" in lines
    assert set(after.removeprefix("After=").split()) == {
        "systemd-modules-load.service",
        "sys-kernel-config.mount",
        "local-fs.target",
    }


def test_usbdevice_self_heals_modular_gadget_framework():
    """ConfigFS 存在但 gadget framework 未注册时应自愈并明确报错。"""
    text = SCRIPT.read_text(encoding="utf-8")

    assert "modprobe usb_f_fs" in text
    assert "USB gadget ConfigFS 未注册" in text
    assert "command -v fuser" in text
    assert "ffs_users=$(usb_fuser_users /dev/usb-ffs/adb)" in text
    assert "底层 controller 未 ready（dwc3/fusb302" not in text
