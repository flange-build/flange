"""UNO Q 的固件、MCU、Bridge 与完整 Arduino 用户态。"""

PACKAGE = {
    "name": "arduino-unoq-runtime",
    "description": "UNO Q Ubuntu 固件与 Arduino 运行时",
    "components": [{"type": "vendor", "name": "flange-arduino-unoq-runtime", "dir": "."},
                   {"type": "vendor", "name": "flange-arduino-unoq-usb", "dir": "usb"}],
}
