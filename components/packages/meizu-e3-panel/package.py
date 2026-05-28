"""meizu-e3-panel 硬件特性包清单。

魅族 E3 39pin MIPI-DSI 屏（显示 + 触摸 + 背光）。同一块屏在不同载板上 panel
驱动与背光驱动选择不同：

- radxa-rock5b：Rockchip BSP ``simple-panel-dsi`` 驱屏；板载 MP3302 boost LED
  驱动，背光走内核内建 ``pwm-backlight`` —— **不**使用 ``sgm37604a``，board
  opt-in 时只取 ``sec_ts``（见 components/board/radxa-rock5b/config.py）。
- radxa-cubie-a7a：Allwinner BSP ``allwinner,panel-dsi`` 驱屏；E3 模组自带
  SGM37604A I2C 背光，启用 ``sgm37604a`` OOT 驱动。
- radxa-dragon-q6a：mainline drm/msm 无通用 DSI panel driver（QCLINUX BSP
  6.6.90 的 ``drivers/gpu/drm/panel/`` 91 个驱动一型一驱），故由本包提供
  OOT ``panel_meizu_e3`` 驱屏（``compatible = "meizu,e3-panel"``）；背光仍
  走 ``sgm37604a`` I2C 路径（板载 SY7203 boost 因 EDP_BLPWM 不被引用而保持
  disabled，与屏自带 SGM37604A 电气并联但功能互斥）。

component 类型由构建引擎 (builder/packages.py) 按 ``type`` 分发到既有流水线：
- ``oot-driver``：make M= 对内核源树编译 → strip → 装入 lib/modules/.../updates/
- ``devicetree``：cpp+dtc 编译该 board 对应 .dtso → .dtbo → boot 分区
  （U-Boot 平台经 extlinux fdtoverlays 运行时叠加；grub-with-dtb 平台 Q6A
  经构建期 ``fdtoverlay`` 预合并到 base dtb，见 [[build-time-dtb-overlay-merge]]）
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
            # 魅族 E3 mainline drm_panel 风格 OOT 驱动，供没有通用 DSI panel
            # driver 的 mainline drm 栈（典型如 QCS6490 QCLINUX BSP drm/msm）
            # 消费；compatible = "meizu,e3-panel"。rock5b/a7a 编出但因 DT 不
            # 引用此 compatible 而不加载。
            "type": "oot-driver",
            "name": "panel_meizu_e3",
            "dir": "driver/panel_meizu_e3",
            "ko_pattern": ["panel_meizu_e3.ko"],
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
                # radxa-dragon-q6a（QCS6490/mainline drm/msm）：mainline DSI 栈，
                # panel 由本包 OOT panel_meizu_e3 驱动；构建期 fdtoverlay 预合并
                # 到 base dtb（GRUB 不支持运行时 overlay）。
                "radxa-dragon-q6a": "device-tree/qcom-qcs6490-radxa-dragon-q6a-meizu-e3-panel.dtso",
            },
        },
    ],
}
