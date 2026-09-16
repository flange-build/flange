"""ROCK 5B 厂商 Mali-G610 用户态驱动包。"""

PACKAGE = {
    "name": "rockchip-mali-g610",
    "description": "Mali-G610 g24p0 厂商 GPU runtime",
    "components": [
        {"type": "vendor", "name": "flange-mali-g610", "dir": "runtime"},
    ],
}
