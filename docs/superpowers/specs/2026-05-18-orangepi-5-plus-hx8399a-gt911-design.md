# OrangePi 5 Plus — HX8399-A 1080×1920 DSI 屏 + GT911 触摸适配设计

- **板**：orangepi-5-plus（RK3588，argon BSP linux-6.1-stan-rkr5.1）
- **屏**：HX8399-A driver IC，1080×1920 portrait，4-lane MIPI DSI（来源：用户提供 `LCD初始化代码.c`）
- **触摸**：Goodix GT911，5-point 电容触摸（来源：用户提供 `GT911_Config_20240308_111925-PP.cfg`）
- **接线**：板载 30-pin MIPI DSI FPC 连接器 + 自制小板，引脚映射按 vendor `rk3588-orangepi-5-plus-lcd.dtsi`

## 目标

把 HX8399-A 1080×1920 DSI 面板与 GT911 5-point 触摸接到 orangepi-5-plus 30-pin
DSI FPC，启动即点亮、touch 出 5 点事件、HDMI 输出不受影响。**实现路径以 board
overlay + firmware blob 为主，零内核 patch，零 driver 新增**（与 wiki 中
orangepi-cm4 DSI 屏适配撤回 change 的四层踩坑教训对应，规避复发）。

## 非目标

- 不实现 HDMI/DSI 双屏同步显示策略调整
- 不实现亮度策略（首版背光走 base dtsi `&backlight` 默认 PWM）
- 不调整 panel 旋转 / 多分辨率切换
- 不为同板第二款 DSI 屏预留 abstraction

## 硬件接线（依据：vendor BSP `rk3588-orangepi-5-plus-lcd.dtsi`）

| 信号 | RK3588 资源 |
|------|-------------|
| DSI 控制器 | `&dsi1`（4-lane，VOP3 → `dsi1_in_vp3`） |
| Panel reset | `GPIO2_C1` active-low |
| Panel VCC_LCD enable | `GPIO1_D2` active-high |
| pinctrl | `&lcd_rst_gpio` |
| 背光 | `&backlight`（base dtsi 已存在 PWM-backlight） |
| 触摸 I2C | `i2c7` @ `0x14` |
| 触摸 INT | `GPIO2_B2` 上升沿（与 cfg byte 6 = `0x35` bit[0]=1 一致） |
| 触摸 RST | `GPIO2_B5` active-high |

## 实现路径

**采用 board overlay**（dtso → dtbo → extlinux fdtoverlays）。理由：

- 与 rock5b mali-valhall-compat / rock5c-lite ST7789VM LCD 完全同模式
- 不引入内核 patch / driver 新增
- 默认应用即可点屏；rollback 走改 `/boot/extlinux/extlinux.conf` 或重刷镜像

**否决路径**：

- 改 board base.dts（需 board 私有 kernel patch 增 dts + 改 Makefile dtb-y，与项目其他板不一致）
- 写新 panel driver `panel-hx8399a.c`（被 `simple-panel-dsi` + `panel-init-sequence` 替代）

## Driver 选择

| 子系统 | Driver | 选用理由 |
|--------|--------|----------|
| Panel | BSP `drivers/gpu/drm/panel/panel-simple.c`，匹配 `compatible = "simple-panel-dsi"` | 已支持 `panel-init-sequence`（格式与 LCD 厂 `.c` 文件 1:1 对应）；已在默认 defconfig 编入；零 patch |
| Touch | mainline `drivers/input/touchscreen/goodix.c`，匹配 `compatible = "goodix,gt911"` | 自带 `request_firmware("goodix_911_cfg.bin")` 路径；`rockchip_linux_defconfig` 已 `CONFIG_TOUCHSCREEN_GOODIX=y`；与 vendor `gt9xx`（compatible `"goodix,gt9xx"`）字符串不重叠不冲突 |
| Backlight | base dtsi `&backlight`（PWM-backlight） | 复用，不动 |

## 文件 layout

```
components/board/orangepi-5-plus/
├── config.py                                                # 改：加 boot.board_overlays / default_overlays
├── dtso/
│   └── rk3588-orangepi-5-plus-hx8399a-gt911.dtso            # 新增
├── firmware/
│   └── touch/
│       └── goodix_911_cfg.cfg                               # 新增：原 ASCII，186 hex token，仅 review 用
└── overlay/
    └── lib/
        └── firmware/
            └── goodix_911_cfg.bin                           # 新增：186B 二进制，部署用
```

> `.bin` 由人手用 `python -c` 转一次性 commit、不自动生成（参考 wiki rock5c-lite
> `st7789vm-240x240.txt` 模式但选择直接落 binary）。
>
> **实施期精化**：原设计草稿试图通过 `rootfs.+extra_firmware` 加 `source="board"`
> 部署 cfg blob，但 builder/source.py:ensure_extra_firmware 仅支持
> `repo / kernel / bootloader / oot:<name>` 四类 source。改走 board
> `overlay/usr/lib/firmware/` 目录（**走 `usr/lib` 不走 `lib`**：ubuntu-base
> rootfs 已 usrmerge，根 `/lib` 是 symlink → `/usr/lib`；`cp -a` 不能覆盖
> non-directory）——`builder/rootfs.py:42-50 _install_overlays`
> 已有 `cp -a` 机制把整棵 `components/board/<board>/overlay/` 拷贝到 rootfs。
> 零 builder 改动；与 board 自有 `overlay/etc/hostname` 同模式。

## dtso 内容

```dts
/dts-v1/;
/plugin/;

#include <dt-bindings/gpio/gpio.h>
#include <dt-bindings/pinctrl/rockchip.h>
#include <dt-bindings/interrupt-controller/irq.h>
#include <dt-bindings/display/drm_mipi_dsi.h>

/ {
    compatible = "rockchip,rk3588";

    metadata {
        title = "HX8399-A 1080x1920 MIPI-DSI panel + GT911 capacitive touch on 30-pin DSI FPC";
        compatible = "xunlong,orangepi-5-plus";
        category = "display";
        exclusive = "&dsi1", "&i2c7";
        description = "Drive DSI1 with HX8399-A 4-lane 1080x1920 portrait panel; GT911 5-point touch on i2c7 @0x14.";
    };
};

&dsi1            { status = "okay"; };
&dsi1_in_vp3     { status = "okay"; };
&route_dsi1      { status = "okay"; connect = <&vp3_out_dsi1>; };

&dsi1_panel {
    status = "okay";
    /* 覆盖 base dtsi 钉死的 "innolux,afj101-ba2131"。 */
    compatible = "simple-panel-dsi";

    reset-gpios  = <&gpio2 RK_PC1 GPIO_ACTIVE_LOW>;
    enable-gpios = <&gpio1 RK_PD2 GPIO_ACTIVE_HIGH>;
    pinctrl-names = "default";
    pinctrl-0 = <&lcd_rst_gpio>;
    backlight = <&backlight>;

    /* MIPI_DSI_MODE_EOT_PACKET：见 §风险 R1，实施时按 BSP 头文件实际宏定义选 (a)/(b) */
    dsi,flags  = <(MIPI_DSI_MODE_VIDEO | MIPI_DSI_MODE_VIDEO_BURST | MIPI_DSI_MODE_LPM)>;
    dsi,format = <MIPI_DSI_FMT_RGB888>;
    dsi,lanes  = <4>;

    panel-init-sequence = [
        /* 1.  EXTC password           */ 39 00 04  B9 FF 83 99
        /* 2.  MIPI control, 4-lane    */ 15 00 02  BA 43
        /* 3.  Reserved D2             */ 15 00 02  D2 44
        /* 4.  Power control B1        */ 39 00 0D  B1 00 7C 34 34 44 09 22 22 71 F1 B2 4A
        /* 5.  Display control B2      */ 39 00 0B  B2 00 80 00 7F 05 07 23 4D 21 01
        /* 6.  Timing control B4 (41B) */ 39 00 29  B4 00 FF 02 40 02 40 00 00 06 00 01 02 00 0F 01 02 05 20 00 04 44 02 40 02 40 00 00 06 00 01 02 00 0F 01 02 05 00 00 04 44
        /* 7.  GIP1 (D3) + 5ms wait    */ 39 05 20  D3 00 01 00 00 00 06 00 00 10 04 00 04 00 00 00 00 00 00 00 00 00 00 01 05 05 07 00 00 00 05 08
        /* 8.  GIP2 (D5) + 5ms         */ 39 05 21  D5 18 18 19 19 18 18 21 20 01 00 07 06 05 04 03 02 18 18 18 18 18 18 30 30 31 31 32 32 18 18 18 18
        /* 9.  GIP3 (D6) + 5ms         */ 39 05 21  D6 18 18 19 19 40 40 20 21 06 07 00 01 02 03 04 05 40 40 40 40 40 40 30 30 31 31 32 32 40 40 40 40
        /* 10. GIP4 (D8) 49 bytes      */ 39 00 31  D8 A2 AA 02 A0 A2 A8 02 A0 B0 00 00 00 B0 00 00 00 B0 00 00 00 B0 00 00 00 E2 AA 03 F0 E2 AA 03 F0 00 00 00 00 00 00 00 00 E2 AA 03 F0 E2 AA 03 F0
        /* 11. VCOM (B6)               */ 39 00 03  B6 29 29
        /* 12. Gamma (E0) 43 bytes     */ 39 00 2B  E0 01 06 06 2A 2F 3E 0F 3A 05 09 0F 13 15 14 15 12 18 07 16 07 14 01 06 06 2A 2F 3E 0F 3A 05 09 0F 13 15 14 15 12 18 07 16 07 14
        /* 13. Display inversion ON    */ 05 00 01  21
        /* 14. MADCTL = 0x02           */ 15 00 02  36 02
        /* 15. SLPOUT  + 255ms         */ 05 FF 01  11
        /* 16. DISPON  + 255ms         */ 05 FF 01  29
    ];

    disp_timings: display-timings {
        native-mode = <&dsi1_timing0>;
        dsi1_timing0: timing0 {
            clock-frequency = <148500000>;
            hactive  = <1080>;
            vactive  = <1920>;
            hback-porch  = <50>;   hfront-porch = <100>;  hsync-len = <30>;
            vback-porch  = <14>;   vfront-porch = <8>;    vsync-len = <2>;
            hsync-active = <0>;    vsync-active = <0>;    de-active = <1>;
            pixelclk-active = <0>;
        };
    };
};

&i2c7 {
    status = "okay";

    touchscreen@14 {
        compatible = "goodix,gt911";       /* 命中 mainline goodix.c；vendor gt9xx 不抢 */
        reg = <0x14>;
        interrupt-parent = <&gpio2>;
        interrupts = <RK_PB2 IRQ_TYPE_EDGE_RISING>;
        irq-gpios   = <&gpio2 RK_PB2 GPIO_ACTIVE_HIGH>;
        reset-gpios = <&gpio2 RK_PB5 GPIO_ACTIVE_HIGH>;
        touchscreen-size-x = <1080>;
        touchscreen-size-y = <1920>;
        status = "okay";
    };
};
```

`panel-init-sequence` 翻译规则（来自 BSP `panel_simple_parse_cmd_seq`）：

- 每条命令头 = `[ data_type, delay_ms, payload_length ]` 3 字节
- `data_type` 对应 `.c` 文件中的 `.PacketHeader`（0x39=DCS Long Write、0x15=DCS Short Write Param、0x05=DCS Short Write No Param）
- `delay_ms` 对应 `.wait` 字段（255ms 上限自然容纳 HX8399-A 的 SLPOUT 后 ≥120ms 要求）
- `payload_length` 对应 `.dlen` 字段（包括命令首字节）
- 16 条命令总字节 = `3 * 16 + Σ payload_length = 48 + 271 = 319`（实施时跑校验）

## GT911 cfg blob

186B raw cfg（GT911 寄存器 `0x8047`–`0x80FE` + 末尾 2B `checksum/Config_Fresh`），与 mainline `goodix.c` 期望的 `request_firmware()` payload 格式完全一致。

- Firmware 文件名：`goodix_911_cfg.bin`（mainline `goodix.c:1402` 命名规则：`goodix_<id>_cfg.bin`，GT911 chip 上电后报 `id = "911"`）
- 装载路径：`/lib/firmware/goodix_911_cfg.bin`
- 下发逻辑：driver 启动时比对 chip flash 内 cfg version vs host cfg version（byte 0 = `0x47`）；host > chip 时下发覆盖

## `config.py` 增量（在既有 RTL8852BE 块之上追加）

```python
"boot": {
    "board_overlays": [
        "rk3588-orangepi-5-plus-hx8399a-gt911.dtbo",
    ],
    "default_overlays": [
        "rk3588-orangepi-5-plus-hx8399a-gt911.dtbo",
    ],
},
```

GT911 cfg blob **不**走 `rootfs.+extra_firmware`——blob 直接放在
`components/board/orangepi-5-plus/overlay/usr/lib/firmware/goodix_911_cfg.bin`，
由 `builder/rootfs.py:_install_overlays` 现成 `cp -a` 机制把整棵 board
overlay 目录拷贝到 rootfs；零 builder 改动，与 board 自有 `overlay/etc/hostname`
同模式。`extra_firmware` 框架（`repo / kernel / bootloader / oot:<name>` 四类
source）不适用此场景——它是 vendor 仓库/外部源 firmware 部署接口，不是
board-local blob 接口。

## 风险与对策

| # | 风险 | 对策 |
|---|------|------|
| R1 | `MIPI_DSI_MODE_EOT_PACKET` 旧名宏可能在 argon BSP 6.1 头文件被移除 | 实施前 grep BSP `include/dt-bindings/display/drm_mipi_dsi.h`；若旧名缺失，dtso flag 不加该位（语义上即"发 EOT"，与 mainline 6.x 默认行为一致），不引入 board 私有 binding patch |
| R2 | dw-mipi-dsi-rockchip defer cleanup NULL deref（orangepi-cm4 适配踩过） | RK3588 用 dsi2-rockchip 控制器，代码路径与 RK3566 不同；本案 dts 起始即把 panel 挂上不触发 defer。实施第一次烧机如见 `mipi_dsi_detach+0x14` NULL deref 指纹，补 cherry-pick 上游 `7977c539e9b1` 等价 patch |
| R3 | `panel-simple-dsi` driver 要求 `payload_length` 与实际 payload 字节数严格匹配 | 实施时跑校验脚本：累加 3 + N 计 16 条，对比总字节数 = 319 |
| R4 | display-timings 凭经验值；HX8399-A 实际 porch 由 panel 厂铜板决定 | 首版用本文档列出的 60Hz 推荐值。实机若花屏/无同步：依次调 porch → clock-frequency。如 panel 厂家有 datasheet typical timing，实施前补到 dtso 注释 |
| R5 | GT911 cfg version `0x47`：driver 比对 chip 内 cfg version；chip 内已 ≥0x47 时下发被跳过 | GT911 协议固有行为。若实机触摸不灵或坐标偏，用 `i2cset` 强写 chip cfg version → `0x00` 强制重发 |

## 回归预期

**不动**：

- RTL8852BE WiFi/BT 链路（dts 节点完全不重叠）
- HDMI0 (VOP0) / HDMI1 (VOP1) 输出（VOP3 → DSI1 独立 video port）
- eMMC / SD / USB / PCIe / RTL8125 NIC

**潜在影响**：

- VOP3 上电使整机功耗 +约 200mW（可接受）

## 验收 checklist

- [ ] `flange build` 通过；boot 分区含 `dtbs/rockchip/overlay/rk3588-orangepi-5-plus-hx8399a-gt911.dtbo`
- [ ] `extlinux.conf` 含该 overlay 的 `fdtoverlays`
- [ ] rootfs `/lib/firmware/goodix_911_cfg.bin` 存在且大小 = 186
- [ ] `dmesg | grep -i panel-simple` 见 probe 成功，无 `failed to parse init sequence`
- [ ] `dmesg | grep -i Goodix` 见 `firmware loaded` 与 `New device registered`，无 `Failed to invoke firmware loader`
- [ ] `/dev/dri/cardN` 出 1080×1920 connector；`modetest` 显示 mode 含 1080x1920@60
- [ ] `evtest` 触摸事件出 5 点，坐标 ∈ [0,1080] × [0,1920]
- [ ] HDMI 同步输出不受影响（双显验证）

## wiki 教训对照

| wiki 教训（orangepi-cm4 撤回 change） | 本案对应 |
|---|---|
| dtso 根级裸节点 → `FDT_ERR_BADOVERLAY` | 全部 `&label{}` fragment；根级 `/{}` 仅含 metadata 不新增节点 |
| 错抄 RPi 7" panel template 与硬件不符 | 不抄；从硬件实际 = HX8399-A 出发，simple-panel-dsi + init-sequence |
| `CONFIG_DRM_CHIPONE_ICN6211` 未启 | 本案无 bridge IC，不涉及 |
| mainline ICN6211 强制 `enable-gpios` | 本案 panel-simple enable-gpios 实接 GPIO1_D2，不缺信号 |
| BSP DSI defer cleanup NULL deref | R2 列项跟进 |
