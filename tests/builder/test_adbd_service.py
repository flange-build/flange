"""adbd systemd 服务配置测试。"""

from pathlib import Path


def test_adbd_service_exports_term_xterm():
    """adbd 服务必须导出 TERM=xterm，保证 adb shell 具备终端类型。"""
    service = Path("components/app/adbd/systemd/usbdevice.service")

    assert "Environment=TERM=xterm" in service.read_text().splitlines()
