"""Arduino UNO Q (Qualcomm QRB2210 / QCM2290) 板级配置 -- 第三层继承

flange 第二块 Qualcomm 板。platform=qualcommqrb2210 / soc=qrb2210。
启动 ABL→U-Boot→extlinux(sysboot)，刷写走 EDL/qdl；详见平台/SoC config。
代号 Imola（Arduino UnoQ）；dts 已上游进 mainline Linux 7.0
（arch/arm64/boot/dts/qcom/qrb2210-arduino-imola.dts）。

Wi-Fi 为板载 ath10k（mainline 驱动 + linux-firmware），无需 OOT 模块/额外固件。
"""

BOARD = {
    "board": "arduino-uno-q",
    "soc": "qrb2210",
    "platform": "qualcommqrb2210",
    "kernel": {
        # mainline dtb（arch/arm64/boot/dts/qcom/qrb2210-arduino-imola.dts）
        "dtb": "qrb2210-arduino-imola",
    },
}
