"""meizu-e3-panel 硬件特性包清单。

魅族 E3 39pin MIPI-DSI 屏（显示 + 触摸 + 背光）。同一块屏在不同载板上背光
驱动方式不同：

- 使用 SGM37604A I2C 背光芯片的载板 → 启用 ``sgm37604a`` OOT 驱动。
- radxa-rock5b：板载 MP3302 boost LED 驱动，背光走内核内建 ``pwm-backlight``，
  **不**使用 ``sgm37604a``；board 在 opt-in 时只取 ``sec_ts``（见
  components/board/radxa-rock5b/config.py）。

component 类型由构建引擎 (builder/packages.py) 按 ``type`` 分发到既有流水线：
- ``oot-driver``：make M= 对内核源树编译 → strip → 装入 lib/modules/.../updates/
- ``devicetree``：cpp+dtc 编译该 board 对应 .dtso → .dtbo → boot 分区
"""

PACKAGE = {
    "name": "meizu-e3-panel",
    "description": "魅族 E3 39pin MIPI-DSI 屏（显示 + 触摸 + 背光）",
    "components": [
        {
            # 三星 SEC 触摸驱动（含固件 .i，直接 #include 编入 .ko）。
            "type": "oot-driver",
            "name": "sec_ts",
            "dir": "driver/sec_ts",
            "ko_pattern": ["sec_ts.ko"],
        },
        {
            # SGM37604A I2C 背光驱动。方案 A：随包保留，仅当某 board opt-in
            # 时显式选中才编译；rock5b 不选它。
            "type": "oot-driver",
            "name": "sgm37604a",
            "dir": "driver/sgm37604a",
            "ko_pattern": ["sgm37604a.ko"],
        },
        {
            # 按 board 区分的 panel overlay（dsi 路由 + 触摸节点 + 背光）。
            "type": "devicetree",
            "name": "panel",
            "overlays": {
                "radxa-rock5b": "device-tree/rk3588-rock-5b-meizu-e3-panel.dtso",
                # radxa-cubie-a7a（A733/sun60iw2p1）：同屏不同 SoC，按 Allwinner
                # sunxi 显示栈重写（allwinner,panel-dsi + dsi0 + virtual-panel
                # OF-graph 中转），见该 .dtso 顶部注释。
                "radxa-cubie-a7a": "device-tree/sun60i-a733-cubie-a7a-meizu-e3-panel.dtso",
            },
        },
    ],
}
