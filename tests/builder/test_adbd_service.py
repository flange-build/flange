"""adbd systemd 服务配置测试。"""

from pathlib import Path


SERVICE = Path("components/app/adbd/systemd/usbdevice.service")
SCRIPT = Path("components/app/adbd/scripts/usbdevice")
ROOT_BASHRC = Path("components/rootfs/overlay/root/.bashrc")


def test_adbd_service_exports_runtime_environment():
    """adbd 服务必须导出 shell 所需的运行环境。"""

    lines = SERVICE.read_text().splitlines()
    assert "Environment=TERM=xterm" in lines
    assert "Environment=XDG_RUNTIME_DIR=/run/user/1000" in lines


def test_adbd_shell_uses_linux_tmpdir():
    """adbd 交互 shell 必须覆盖其内建的 Android 临时目录。"""

    assert "export TMPDIR=/tmp" in ROOT_BASHRC.read_text().splitlines()


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
