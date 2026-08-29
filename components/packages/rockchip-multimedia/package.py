"""Rockchip MPP、RGA 与 GStreamer 硬件加速软件包集合。"""

PACKAGE = {
    "name": "rockchip-multimedia",
    "description": "Rockchip 多媒体硬件加速 runtime",
    "components": [
        {
            "type": "vendor",
            "name": "rockchip-multimedia-build",
            "dir": "build",
        },
        {
            "type": "vendor",
            "name": "flange-rockchip-multimedia",
            "dir": "config",
        },
    ],
}
