## MODIFIED Requirements

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

## ADDED Requirements

### Requirement: radxa-cubie-a7a overlay 接线

`device-tree/sun60i-a733-cubie-a7a-meizu-e3-panel.dtso` MUST 按 Allwinner sunxi 显示栈编写（**不**复用 rock5b 的 Rockchip DRM overlay），按 radxa-cubie-a7a 原理图 v1.10 的 LCD FPC（J10）接线生成，且 MUST 满足：

- 显示链路 MUST 使能 `&dsi0combophy`、`&dlcd0`、`&dsi0`（4-lane，`pinctrl` 用 `dsi0_4lane_pins_a`/`dsi0_4lane_pins_b`，`pinctrl-names = "active","sleep"`）。
- 真实 panel 节点 MUST 用 `compatible = "allwinner,panel-dsi"`，并经 board.dts 既有 `panel: panel@0`（`allwinner,virtual-panel`）的 OF-graph 中转：virtual-panel 的 `port@1` 端点 MUST 与真实 panel 节点的 `port` 端点互连。
- DSI 模式属性 MUST 使用 `<dt-bindings/display/sunxi-lcd.h>` 常量（`dsi,flags`、`dsi,format`、`dsi,lanes = <4>`），MUST NOT 使用 Rockchip 的 `<dt-bindings/display/drm_mipi_dsi.h>`。
- `panel-init-sequence` / `panel-exit-sequence` MUST 沿用魅族 E3 的 DCS 字节序列（与 rock5b 同格式 `[data_type delay payload_length payload...]`：init 为 sleep-out `05 78 01 11` + display-on `05 0A 01 29`）；`display-timings` MUST 为 1080×2160 @ 157MHz。
- 屏复位 MUST 接 `&pio PD 21`（LCD-RST），`reset-num`/`reset-delay-ms` 由 panel 节点声明（驱动管理复位时序）。
- 电源 MUST 由 `power0-supply = <&reg_dc1sw1>`（VCC33-LCD，3.3V）与 `power1-supply = <&reg_bldo2>`（VCC18-LCD，1.8V）提供，`power-num = <2>`。
- 触摸 `sec_ts@0x48` 与背光 `backlight@0x36` MUST 挂 `&twi2`（PD16/PD17，`function="twi2"`），`twi_drv_used = <1>`。
- 触摸节点 `compatible = "sec,sec_ts"`，`sec,irq_gpio = <&pio PD 18 ...>`（TP-INT，驱动内部 `gpio_to_irq`），`sec,max_coords = <1080>, <2160>`；复位脚 `&pio PD 19`（TP-RST），因 sec_ts 驱动不管理 reset，MUST 用 `&pio` gpio-hog 输出高解复位。
- 背光节点 `compatible = "sgmicro,sgm37604a"`，使能脚 `&pio PD 23`（LCD_light_EN），panel `backlight` phandle MUST 引用之；亮度参数（`led-channels`/`max-current`/`default-brightness-level`）MUST 取实机可见档位（沿用 rock5b 调好的 `default-brightness-level = <2048>` 等）。
- MUST NOT 使用 `pwm-backlight`（E3 屏自带 SGM37604A I2C 背光，不走 8hd 模板的 PD22/PWM0-4）。

#### Scenario: Allwinner DSI0 栈与 OF-graph 正确

- **WHEN** 编译并加载 `sun60i-a733-cubie-a7a-meizu-e3-panel.dtbo`
- **THEN** `&dsi0combophy` / `&dlcd0` / `&dsi0` 被使能，panel 声明 4 条 data lane
- **AND** board.dts 的 `allwinner,virtual-panel` `port@1` 端点与 `allwinner,panel-dsi` 节点的 `port` 端点互连
- **AND** overlay 中不出现 Rockchip 的 `&dsi1`/`route_dsi1`/`simple-panel-dsi`/`rockchip,pins`

#### Scenario: 触摸与背光挂 twi2

- **WHEN** overlay 应用到 radxa-cubie-a7a
- **THEN** `&twi2`（PD16/PD17）上出现 `sec_ts@0x48`（irq-gpio = `<&pio PD 18>`）与 `backlight@0x36`（`sgmicro,sgm37604a`，enable = `<&pio PD 23>`）
- **AND** TP-RST（`&pio PD 19`）经 gpio-hog 输出高解复位
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
