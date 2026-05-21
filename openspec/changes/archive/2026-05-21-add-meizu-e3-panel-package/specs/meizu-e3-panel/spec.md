## ADDED Requirements

### Requirement: 包结构与内容

`meizu-e3-panel` 包 MUST 位于 `components/packages/meizu-e3-panel/`，并 MUST 含子目录 `driver/` 与 `device-tree/`。`driver/` MUST 提供两个 `oot-driver`：`sec_ts`（三星 SEC 触摸驱动，含其固件）与 `sgm37604a`（SGM37604A I2C 背光驱动）。`device-tree/` MUST 提供按 board 区分的 `.dtso` overlay。每个 `oot-driver` 子目录 MUST 自带可独立 `make M=` 编译的 `Makefile`（OOT 形态，`obj-m`）。

#### Scenario: 包目录齐备

- **WHEN** 检视 `components/packages/meizu-e3-panel/`
- **THEN** 存在 `package.py`、`driver/sec_ts/`、`driver/sgm37604a/`、`device-tree/`
- **AND** `package.py` 的 `components` 声明 `sec_ts`、`sgm37604a` 两个 `oot-driver` 与一个 `devicetree`

#### Scenario: 驱动可独立 OOT 编译

- **WHEN** 对 `driver/sgm37604a` 执行 `make M=<dir> KSRC=<kernel_src>` 风格的 OOT 编译
- **THEN** 产出 `sgm37604a.ko`（不依赖修改内核 in-tree 的 Kconfig/Makefile）

### Requirement: radxa-rock5b overlay 接线

`device-tree/rk3588-rock-5b-meizu-e3-panel.dtso` MUST 按 radxa-rock5b 原理图 v1.423 接线生成 overlay，且 MUST 满足：

- DSI 走 `dsi1`（DPHY1，4 lane），经 VP3 路由（`route_dsi1` 连 `vp3_out_dsi1`，启用 `dsi1_in_vp3`）。
- panel 与 dsi1 之间 MUST 建立 OF-graph 端点（dsi1 `port@1` ↔ panel `port@0`）—— rk3588 BSP `dw-mipi-dsi2` 用 `drm_of_find_panel_or_bridge(np, port=1)` 经 OF-graph 找 panel，缺端点会 `FDT_ERR`/`-19 Failed to find panel or bridge`。
- 触摸 `sec_ts@0x48` 挂 `i2c6`（追加节点，MUST NOT 移除既有 `hym8563@0x51`）；irq 接 `gpio0 RK_PD3`；reset（TP_RST_L）接 `gpio0 RK_PC6`，因 sec_ts 驱动不管理 reset，MUST 用 gpio-hog 输出高解复位。
- 屏复位接 `gpio2 RK_PC1`（LCD_RESET）。
- LCD 供电 MUST 由 GPIO 使能的 regulator-fixed 提供：使能脚 `gpio1 RK_PC4`（LCD_PWREN_H），`regulator-always-on` + `boot-on`，panel `vdd-supply` 引用之；`vccio-supply` 引用 `vcc_1v8_s0`。
- 新增的根级节点（regulator 等）MUST 包进显式 `fragment { target-path="/"; __overlay__ {...} }`，以兼容本板 U-Boot 2017.09 libfdt 的 `overlay_symbol_update`（详见 [[extlinux-dtb-overlays]] 与 design 决策）。

#### Scenario: DSI 路由与 OF-graph 正确

- **WHEN** 编译并加载 `rk3588-rock-5b-meizu-e3-panel.dtbo`
- **THEN** `&dsi1` 被使能并通过 VP3 路由到 panel，panel 声明 4 条 data lane
- **AND** dsi1 `port@1` 端点与 panel `port@0` 端点互连，`dw-mipi-dsi2` 能找到 panel（无 `-19`）

#### Scenario: 触摸节点追加且不破坏既有总线

- **WHEN** overlay 应用到 rock5b
- **THEN** `i2c6` 上出现 `sec_ts@0x48`，irq-gpio = `<&gpio0 RK_PD3>`，TP_RST（`gpio0 RK_PC6`）经 gpio-hog 解复位
- **AND** 既有 `hym8563@0x51` RTC 节点保持不变

#### Scenario: LCD 供电使能

- **WHEN** overlay 应用到 rock5b
- **THEN** 存在 GPIO 使能的 `regulator-fixed`（`gpio1 RK_PC4`，always-on/boot-on），panel `vdd-supply` 引用之
- **AND** 开机时 LCD_3V3 上电，panel 与触摸均能正常 probe

### Requirement: radxa-rock5b 背光走 sgm37604a I2C

魅族 E3 屏自带 SGM37604A I2C 背光芯片，rock5b 背光 MUST 使用 `sgm37604a` OOT 驱动，MUST NOT 使用 `pwm-backlight`/板载 MP3302。overlay MUST 在 `i2c6` 上声明 `backlight@36`（`compatible = "sgmicro,sgm37604a"`），panel `backlight` 引用之；使能脚接 `gpio0 RK_PA0`（GPIO0-A0）。亮度参数 MUST 设为实机可见档位（`led-channels` 开 4 路、`max-current` 取 40mA 档、`default-brightness-level` 取约半量程而非接近 0）。

#### Scenario: 背光由 sgm37604a I2C 驱动

- **WHEN** overlay 应用到 rock5b 且 `sgm37604a` 模块加载
- **THEN** `i2c6` 上 `backlight@36` 绑定 sgm37604a，`/sys/class/backlight/sgm37604a` 出现
- **AND** overlay 中不出现 `pwm-backlight`/`pwm2` 背光节点

#### Scenario: 默认亮度可见

- **WHEN** 系统开机
- **THEN** 背光默认亮度处于可见档位（非接近 0 的极暗值），可经 `/sys/class/backlight/sgm37604a/brightness` 调节

### Requirement: 所需内核内建项与 OOT 驱动

启用本包点亮 rock5b 屏所依赖的内核功能——rockchip drm 的 `simple-panel-dsi`（`CONFIG_DRM_PANEL_SIMPLE`）、`dw-mipi-dsi2`（`CONFIG_ROCKCHIP_DW_MIPI_DSI2`）、combo dcphy（`CONFIG_PHY_ROCKCHIP_SAMSUNG_DCPHY`）——MUST 在 rock5b 内核中可用（已内建或经 defconfig fragment 补齐）。背光与触摸 MUST 由包内 `sgm37604a` / `sec_ts` 两个 OOT 驱动提供（board opt-in 选中），安装到 `lib/modules/.../updates/` 并随 DT 节点自动加载。

#### Scenario: panel 驱动可用

- **WHEN** 构建 rock5b 内核
- **THEN** `CONFIG_DRM_PANEL_SIMPLE` / `CONFIG_ROCKCHIP_DW_MIPI_DSI2` 已启用
- **AND** rockchip drm panel-simple-dsi 可绑定 `simple-panel-dsi` 兼容节点

#### Scenario: 背光/触摸 OOT 驱动随节点加载

- **WHEN** board opt-in 选中 `sec_ts` 与 `sgm37604a`，系统开机
- **THEN** 两个 `.ko` 安装到 `lib/modules/<release>/updates/`
- **AND** DT 出现 `sec,sec_ts` / `sgmicro,sgm37604a` 节点时对应模块按 of alias 自动加载并 probe
