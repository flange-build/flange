# meizu-e3-panel Specification

## Purpose
`meizu-e3-panel` 硬件特性包：以同一块魅族 E3 39pin MIPI-DSI 屏（s6d6ft0 触显模组 + SGM37604A I2C 背光）为对象，提供「显示 + 触摸 + 背光」的跨 SoC 复用能力——`sec_ts` / `sgm37604a` 两个 OOT 驱动两板共享，panel overlay 按 SoC 显示栈分别编写：`radxa-rock5b`（RK3588 / Rockchip DRM）与 `radxa-cubie-a7a`（Allwinner A733 / sunxi）。board 经 opt-in + product 条件键按需注入，不影响裸机产物。
## Requirements
### Requirement: 包结构与内容

`meizu-e3-panel` 包 MUST 位于 `components/packages/meizu-e3-panel/`，并 MUST 含子目录 `driver/` 与 `device-tree/`。`driver/` MUST 提供两个 `oot-driver`：`sec_ts`（三星 SEC 触摸驱动，含其固件）与 `sgm37604a`（SGM37604A I2C 背光驱动）。`device-tree/` MUST 提供按 board 区分的 `.dtso` overlay，且 `package.py` 的 `panel` component `overlays` 映射 MUST 同时包含 `radxa-rock5b` 与 `radxa-cubie-a7a` 两个 board 键。每个 `oot-driver` 子目录 MUST 自带可独立 `make M=` 编译的 `Makefile`（OOT 形态，`obj-m`）。

#### Scenario: 包目录齐备

- **WHEN** 检视 `components/packages/meizu-e3-panel/`
- **THEN** 存在 `package.py`、`driver/sec_ts/`、`driver/sgm37604a/`、`device-tree/`
- **AND** `package.py` 的 `components` 声明 `sec_ts`、`sgm37604a` 两个 `oot-driver` 与一个 `devicetree`

#### Scenario: 驱动可独立 OOT 编译

- **WHEN** 对 `driver/sgm37604a` 执行 `make M=<dir> KSRC=<kernel_src>` 风格的 OOT 编译
- **THEN** 产出 `sgm37604a.ko`（不依赖修改内核 in-tree 的 Kconfig/Makefile）

#### Scenario: overlays 映射含两块实板

- **WHEN** 检视 `package.py` 的 `panel` component `overlays` 映射
- **THEN** 含键 `"radxa-rock5b"` 指向 `device-tree/rk3588-rock-5b-meizu-e3-panel.dtso`
- **AND** 含键 `"radxa-cubie-a7a"` 指向 `device-tree/sun60i-a733-cubie-a7a-meizu-e3-panel.dtso`
- **AND** `device-tree/` 下两个 `.dtso` 文件均存在

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


### Requirement: radxa-cubie-a7a overlay 接线

`device-tree/sun60i-a733-cubie-a7a-meizu-e3-panel.dtso` MUST 按 Allwinner sunxi 显示栈编写（**不**复用 rock5b 的 Rockchip DRM overlay），按 radxa-cubie-a7a 原理图 v1.10 的 LCD FPC（J10）接线生成，且 MUST 满足：

- 显示链路 MUST 使能 `&dsi0combophy`、`&dlcd0`、`&dsi0`（4-lane，`pinctrl` 用 `dsi0_4lane_pins_a`/`dsi0_4lane_pins_b`，`pinctrl-names = "active","sleep"`）。
- 真实 panel 节点 MUST 用 `compatible = "allwinner,panel-dsi"`，并经 board.dts 既有 `panel: panel@0`（`allwinner,virtual-panel`）的 OF-graph 中转：virtual-panel 的 `port@1` 端点 MUST 与真实 panel 节点的 `port` 端点互连。
- DSI 模式属性 MUST 使用 `<dt-bindings/display/sunxi-lcd.h>` 常量（`dsi,flags`、`dsi,format`、`dsi,lanes = <4>`），MUST NOT 使用 Rockchip 的 `<dt-bindings/display/drm_mipi_dsi.h>`。`dsi,flags` MUST 为**非 burst** `MIPI_DSI_MODE_VIDEO`（实测 burst 在 A733 出细密竖条纹+抖动；高通原厂写 burst_mode 但 Allwinner burst 实现不等价）。
- `panel-init-sequence` / `panel-exit-sequence` MUST 沿用魅族 E3 的 DCS 字节序列（与 rock5b 同格式 `[data_type delay payload_length payload...]`：init 为 sleep-out `05 78 01 11` + display-on `05 0A 01 29`）；`display-timings` MUST 用 E3 原厂高通权威值 **1080×2160 @ 60Hz、htotal=1317（hfp229/hbp4/hsync4）/ vtotal=2176（vfp8/vbp6/vsync2）/ pixel-clock≈171.95MHz**（抄 rock5b 的 157MHz/htotal1211 是斜纹根因）。
- 屏复位 MUST 接 `&pio PD 21`（LCD-RST），`reset-num`/`reset-delay-ms` 由 panel 节点声明（驱动管理复位时序）。
- 电源 MUST 由 `power0-supply = <&reg_dc1sw1>`（VCC33-LCD，3.3V）与 `power1-supply = <&reg_bldo2>`（VCC18-LCD，1.8V）提供，`power-num = <2>`。
- 触摸 `sec_ts@0x48` 与背光 `backlight@0x36` MUST 挂 `&twi2`（PD16/PD17，`function="twi2"`），`twi_drv_used` MUST 为 **`<0>`（engine 模式）**：drv 模式（`<1>`）扛不住 `sec_ts` 运行时 `read_event` 的高频背靠背 write-then-read，约 0.5s 进 `TWI BUS error 0x18/0x20` 卡死；engine 模式逐字节中断 + 经典 NACK/总线恢复，与 rock5b Rockchip i2c6 行为一致。
- 触摸节点 `compatible = "sec,sec_ts"`，`sec,irq_gpio = <&pio PD 18 ...>`（TP-INT，驱动内部 `gpio_to_irq`），`sec,max_coords = <1080>, <2160>`；复位脚 `&pio PD 19`（TP-RST），因 sec_ts 驱动不管理 reset，MUST 用 `regulator-fixed`（`gpio = <&pio PD 19>`、`enable-active-high`、`always-on`、`boot-on`）在注册时拉高解复位——MUST NOT 用 `&pio` gpio-hog（sunxi pinctrl 按 pinmux group 解析 gpio-hog 会致主 pinctrl probe 挂掉、连带 MMC 失引脚找不到 rootfs）。
- 背光节点 `compatible = "sgmicro,sgm37604a"`，使能脚 `&pio PD 23`（LCD_light_EN），panel `backlight` phandle MUST 引用之；亮度参数（`led-channels`/`max-current`/`default-brightness-level`）MUST 取实机可见档位（沿用 rock5b 调好的 `default-brightness-level = <2048>` 等）。
- MUST NOT 使用 `pwm-backlight`（E3 屏自带 SGM37604A I2C 背光，不走 8hd 模板的 PD22/PWM0-4）。

#### Scenario: Allwinner DSI0 栈与 OF-graph 正确

- **WHEN** 编译并加载 `sun60i-a733-cubie-a7a-meizu-e3-panel.dtbo`
- **THEN** `&dsi0combophy` / `&dlcd0` / `&dsi0` 被使能，panel 声明 4 条 data lane
- **AND** board.dts 的 `allwinner,virtual-panel` `port@1` 端点与 `allwinner,panel-dsi` 节点的 `port` 端点互连
- **AND** overlay 中不出现 Rockchip 的 `&dsi1`/`route_dsi1`/`simple-panel-dsi`/`rockchip,pins`

#### Scenario: 触摸与背光挂 twi2

- **WHEN** overlay 应用到 radxa-cubie-a7a
- **THEN** `&twi2`（PD16/PD17，`twi_drv_used = <0>` engine 模式）上出现 `sec_ts@0x48`（irq-gpio = `<&pio PD 18>`）与 `backlight@0x36`（`sgmicro,sgm37604a`，enable = `<&pio PD 23>`）
- **AND** TP-RST（`&pio PD 19`）经 `regulator-fixed`（always-on/boot-on）拉高解复位，overlay 中不出现 `gpio-hog`
- **AND** panel `backlight` phandle 引用 `backlight@0x36`，overlay 中不出现 `pwm-backlight`

#### Scenario: 电源轨与复位

- **WHEN** overlay 应用到 radxa-cubie-a7a
- **THEN** panel 节点 `power0-supply = <&reg_dc1sw1>`、`power1-supply = <&reg_bldo2>`、`power-num = <2>`
- **AND** 屏复位脚为 `&pio PD 21`，开机时 panel 与触摸均能正常 probe

### Requirement: radxa-cubie-a7a 启用 meizu-e3-bringup product

`components/board/radxa-cubie-a7a/config.py` MUST 声明 `products: ["default", "meizu-e3-bringup"]`，并 MUST 通过条件键仅在 `meizu-e3-bringup` product 注入屏适配：`"+packages:meizu-e3-bringup"` MUST 含 `{"name": "meizu-e3-panel", "drivers": ["sec_ts", "sgm37604a"]}`，`boot."+default_overlays:meizu-e3-bringup"` MUST 含 `"sun60i-a733-cubie-a7a-meizu-e3-panel.dtbo"`。`default` product MUST NOT 携带上述包内容与 panel overlay（维持 HDMI 直出裸机），其产物 MUST 与本变更前 byte-identical。

#### Scenario: bringup product 点屏

- **WHEN** lunch `radxa-cubie-a7a-meizu-e3-bringup-{debug,release}` 并构建
- **THEN** `meizu-e3-panel` 包的 `sec_ts` 与 `sgm37604a` 两个 OOT 驱动被编译并装入 `lib/modules/<release>/updates/`
- **AND** `sun60i-a733-cubie-a7a-meizu-e3-panel.dtbo` 被编译、纳入 boot 打包集合，并在 extlinux `fdtoverlays` 默认应用

#### Scenario: default product 不回归

- **WHEN** lunch `radxa-cubie-a7a-default-{debug,release}` 并构建
- **THEN** 不编译 `sec_ts`/`sgm37604a`，不打 panel overlay
- **AND** 产物与本变更前 byte-identical

### Requirement: radxa-cubie-a7a 所需内核内建项

启用本包点亮 radxa-cubie-a7a 屏所依赖的 Allwinner BSP 内核功能——`allwinner,panel-dsi` 通用 DSI panel 驱动（`bsp/drivers/drm/panel/panel-dsi.c`）、sunxi DSI 控制器、`dlcd0` 显示通道与 `dsi0combophy`——MUST 在 a7a 内核（A733 BSP `linux-a733`）中可用（已内建或经 defconfig fragment 补齐）。背光与触摸 MUST 由包内 `sgm37604a` / `sec_ts` 两个 OOT 驱动提供（board opt-in 选中），安装到 `lib/modules/.../updates/` 并随 DT 节点自动加载。

#### Scenario: allwinner,panel-dsi 驱动可用

- **WHEN** 构建 radxa-cubie-a7a（meizu-e3-bringup product）内核
- **THEN** A733 BSP 的 `allwinner,panel-dsi` 驱动、sunxi DSI、`dlcd0`、`dsi0combophy` 内建可用
- **AND** 可绑定 overlay 中的 `allwinner,panel-dsi` 兼容节点并执行其 `panel-init-sequence`

#### Scenario: 背光/触摸 OOT 驱动随节点加载

- **WHEN** board opt-in 选中 `sec_ts` 与 `sgm37604a`，系统开机
- **THEN** 两个 `.ko` 安装到 `lib/modules/<release>/updates/`
- **AND** DT 出现 `sec,sec_ts` / `sgmicro,sgm37604a` 节点时对应模块按 of alias 自动加载并 probe

### Requirement: sec_ts / sgm37604a 跨内核兼容

`sec_ts` 与 `sgm37604a` 是 Android 系 vendor 驱动，隐式依赖 Rockchip 6.1 BSP 内核 API。为在 A733 主线系 5.15 内核编译，包 MUST 以**版本守卫**吸收跨内核 API 差异，且 MUST NOT 改变既有 board（rock5b 6.1）的代码路径与功能行为，MUST NOT 修改内核源（坚持 OOT 路线）：

- `<linux/wakelock.h>`：6.1 之前已从主线移除（被 wakeup_source 取代），Rockchip BSP 自带 Android 兼容头，A733 5.15 无。包 MUST 提供 `driver/sec_ts/sec_ts_wakelock.h` 兼容垫片，用 `__has_include(<linux/wakelock.h>)` 分流——有则包含原生头，无则把 `struct wake_lock` / `wake_lock_init` / `wake_lock_timeout` 映射到现代 `wakeup_source`（`wakeup_source_register` / `__pm_wakeup_event`）。`sec_ts_main.c` / `sec_ts_selftest.c` MUST 改为包含该垫片而非直接包含 `<linux/wakelock.h>`。
- i2c_driver `.remove` 回调：内核 6.1 起返回 `void`、此前返回 `int`。`sec_ts` 与 `sgm37604a` 的 remove 函数签名与返回值 MUST 以 `LINUX_VERSION_CODE >= KERNEL_VERSION(6, 1, 0)` 守卫分流。

#### Scenario: A733 (linux-5.15) 上干净编译

- **WHEN** 对 `sec_ts` 与 `sgm37604a` 在 A733 BSP `linux-a733`（5.15）下执行 `make M=` OOT 编译
- **THEN** 两驱动均编译通过产出 `.ko`（wakelock 垫片回退到 wakeup_source、remove 取 `int` 分支）
- **AND** 不修改内核源、不依赖内核提供 `<linux/wakelock.h>`

#### Scenario: rock5b (6.1) 行为不变

- **WHEN** 在 Rockchip 6.1 BSP 下编译 `sec_ts` / `sgm37604a`
- **THEN** `__has_include` 命中原生 `<linux/wakelock.h>`、remove 取 `void` 分支
- **AND** 编译产物功能与本变更前等价（垫片不介入既有路径）

### Requirement: radxa-cubie-a7a 触摸 bring-up 处理（a7a 专属，rock5b 不受影响）

包 MUST 在 a7a 上对 `sec_ts` 额外做两处 a7a 专属处理（DT 按板分流，rock5b 源码与编译条件分支零改动；engine 模式另见「overlay 接线」要求的 `twi_drv_used=<0>`）：

- **跳过 on-probe 自动刷固件**：`sec_ts_fwupdate_work` 默认（`CONFIG_FW_UPDATE_ON_PROBE`）无条件发 `SEC_TS_CMD_SW_RESET` + 强刷内置固件；本板触摸无 HW reset 通路（`sec_ts_power()` 空壳、RESETB 静态高），软复位后芯片无法重新引导 → 对 0x48 永久 NACK 卡死（芯片出厂已带可用固件 `device_id=0xAC=ID_ON_FW`，无需重刷）。包 MUST 提供 DT 布尔属性 `sec,skip-fw-update-on-probe`（驱动 `plat_data->skip_fwup_on_probe`）；a7a overlay 的 `sec_ts@48` MUST 置位（跳过 SW_RESET+强刷、直接 `read_information`），rock5b overlay MUST NOT 置位（走原路径）。`CONFIG_FW_UPDATE_ON_PROBE` MUST 保持定义（MUST NOT 全局禁用，否则破坏 rock5b）。
- **`sec_ts_remove` 资源释放**：MUST 补 `gpio_free(plat_data->gpio)`（对称 `sec_ts_parse_dt` 的 `gpio_request_one`），否则 rmmod 后 IRQ GPIO 残留、重 probe -EINVAL。

#### Scenario: a7a 跳过刷固件后触摸可用

- **WHEN** a7a（meizu-e3-bringup）开机，`sec_ts` probe + `sec_ts_fwupdate_work` 运行
- **THEN** 因 `sec,skip-fw-update-on-probe` 跳过 SW_RESET+强刷，芯片保持存活（`read_information` 读到 `device_id=0xAC`、Tx/Rx、分辨率 1080×2160）
- **AND** `evtest` 触摸出真坐标、多点 tracking 正常（0x48 无持续 NACK）

#### Scenario: rock5b 触摸路径不回归

- **WHEN** rock5b（不置 `sec,skip-fw-update-on-probe`）编译运行 `sec_ts`
- **THEN** 走原 `CONFIG_FW_UPDATE_ON_PROBE` + SW_RESET + 完整 fw flash 路径，源码与编译条件分支零改动

**已知非阻塞限制**：a7a idle 时 INT(PD18) 被芯片侧持续拉低、`sec_ts` level 中断空涨 ~1850/s（触摸靠 `read_event` 轮询工作、功能正常）。经核实非 SoC 引脚配置问题（PD18 GPIO 模式 / level 触发 / 上拉均正常）；根因在芯片固件（boot status=0x20 watchdog）或屏模组硬件，加内部上拉、补 SW_RESET 引导握手均无效（已排除），无芯片 datasheet 难根治，接受为已知限制。
