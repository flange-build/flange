## MODIFIED Requirements

### Requirement: 包结构与内容

`meizu-e3-panel` 包 MUST 位于 `components/packages/meizu-e3-panel/`，并 MUST 含子目录 `driver/` 与 `device-tree/`。`driver/` MUST 提供三个 `oot-driver`：`sec_ts`（三星 SEC 触摸驱动，含其固件）、`sgm37604a`（SGM37604A I2C 背光驱动）、`panel_meizu_e3`（魅族 E3 屏 mainline drm_panel 风格 OOT 驱动，供 mainline drm 栈如 drm/msm 消费——rock5b 走 Rockchip BSP `simple-panel-dsi` / a7a 走 Allwinner BSP `allwinner,panel-dsi`，两板编出但不加载）。`device-tree/` MUST 提供按 board 区分的 `.dtso` overlay，且 `package.py` 的 `panel` component `overlays` 映射 MUST 同时包含 `radxa-rock5b`、`radxa-cubie-a7a`、`radxa-dragon-q6a` 三个 board 键。每个 `oot-driver` 子目录 MUST 自带可独立 `make M=` 编译的 `Makefile`（OOT 形态，`obj-m`）。

#### Scenario: 包目录齐备

- **WHEN** 检视 `components/packages/meizu-e3-panel/`
- **THEN** 存在 `package.py`、`driver/sec_ts/`、`driver/sgm37604a/`、`driver/panel_meizu_e3/`、`device-tree/`
- **AND** `package.py` 的 `components` 声明 `sec_ts`、`sgm37604a`、`panel_meizu_e3` 三个 `oot-driver` 与一个 `devicetree`

#### Scenario: 驱动可独立 OOT 编译

- **WHEN** 对 `driver/sgm37604a` / `driver/panel_meizu_e3` 执行 `make M=<dir> KSRC=<kernel_src>` 风格的 OOT 编译
- **THEN** 产出对应 `sgm37604a.ko` / `panel_meizu_e3.ko`（不依赖修改内核 in-tree 的 Kconfig/Makefile）

#### Scenario: overlays 映射含三块实板

- **WHEN** 检视 `package.py` 的 `panel` component `overlays` 映射
- **THEN** 含键 `"radxa-rock5b"` 指向 `device-tree/rk3588-rock-5b-meizu-e3-panel.dtso`
- **AND** 含键 `"radxa-cubie-a7a"` 指向 `device-tree/sun60i-a733-cubie-a7a-meizu-e3-panel.dtso`
- **AND** 含键 `"radxa-dragon-q6a"` 指向 `device-tree/qcom-qcs6490-radxa-dragon-q6a-meizu-e3-panel.dtso`
- **AND** `device-tree/` 下三个 `.dtso` 文件均存在

## ADDED Requirements

### Requirement: sec_ts / sgm37604a 跨 6.6 内核 ABI 兼容垫片

包内既有 `sec_ts` / `sgm37604a` OOT 驱动 MUST 跨 a7a (5.15) / rock5b (6.1) / radxa-dragon-q6a (6.6.90 QCLINUX BSP) 三档内核编出，通过 `LINUX_VERSION_CODE` 守卫吸收以下漂移：

- **i2c_driver.remove 返回类型**（commit on 6.1 起 `int` → `void`）：既有守卫 `#if LINUX_VERSION_CODE >= KERNEL_VERSION(6, 1, 0)`。
- **i2c_driver.probe 签名**（commit `b8a1a4cd5e93`，6.6 起合并 probe_new 到 probe，删 `const struct i2c_device_id *` 参数）：sec_ts 与 sgm37604a 均 MUST 用 `#if LINUX_VERSION_CODE >= KERNEL_VERSION(6, 6, 0)` 守卫；`id` 形参在两驱动中均从未被使用，分流干净。
- **class_create 签名**（commit `1aaba11da9aa`，6.4 起去掉首参 `THIS_MODULE`）：sec_ts MUST 用 `#if LINUX_VERSION_CODE >= KERNEL_VERSION(6, 4, 0)` 守卫。
- **pinctrl/consumer.h 间接 include 丢失**（6.6 链路）：sec_ts MUST 显式 `#include <linux/pinctrl/consumer.h>`（无版本守卫，对所有目标内核安全）。

#### Scenario: sec_ts / sgm37604a 三档内核均编出

- **WHEN** 用各自 board kernel 源跑 `make M=<driver> KSRC=<ksrc>` OOT 编译
- **THEN** a7a (5.15) / rock5b (6.1) / radxa-dragon-q6a (6.6.90) 三档 build 均产出对应 `.ko`，无 `-Werror=incompatible-pointer-types` / `-Werror=implicit-function-declaration`

### Requirement: panel_meizu_e3 OOT 驱动语义

`driver/panel_meizu_e3/` MUST 提供 mainline drm_panel 风格的 DSI panel 驱动，形态对标 mainline `drivers/gpu/drm/panel/panel-himax-hx8394.c` 等简洁专用 panel 驱动。MUST 满足：

- `compatible = "meizu,e3-panel"`；模块 alias MUST 含 `of:N*T*Cmeizu,e3-panelC*`，使 DT 节点 probe 时按 of-modalias 自动加载。
- panel timing/format 硬编码：active = 1080×2160；refresh = 60Hz；htotal = 1317（hfp=229 / hbp=4 / hsync=4）；vtotal = 2176（vfp=8 / vbp=6 / vsync=2）；pixel-clock ≈ 171.95 MHz。
- DSI 配置：`lanes = 4`；`format = MIPI_DSI_FMT_RGB888`；`mode_flags = MIPI_DSI_MODE_VIDEO`（**非 burst**——burst 在 A733/QCS6490 实测出竖条纹/抖动；E3 同 timing 在 rock5b 也只在非 burst 下稳定）。
- init sequence：`mipi_dsi_dcs_exit_sleep_mode`（0x11）+ `msleep(120)` + `mipi_dsi_dcs_set_display_on`（0x29）+ `msleep(10)`；exit sequence：display-off + sleep-in。
- DT prop 解析：`reset-gpios`（active-low，驱动管理复位时序，标准 20ms assert + 10ms deassert + 120ms enable 之间的稳定延时）、`vdd-supply` / `vccio-supply`（两路 regulator）、`backlight` phandle（可选）。
- MUST NOT 引入 in-tree Kconfig/Makefile 修改；Makefile 仅 `obj-m += panel_meizu_e3.o`。

#### Scenario: 模块结构与编译

- **WHEN** 对 `driver/panel_meizu_e3/` 执行 OOT 编译
- **THEN** 产出 `panel_meizu_e3.ko`
- **AND** `modinfo panel_meizu_e3.ko` 含 `alias: of:N*T*Cmeizu,e3-panelC*`

#### Scenario: DT 节点 probe 时自动加载

- **WHEN** rootfs 已装 `panel_meizu_e3.ko` 到 `lib/modules/<release>/updates/`，目标 dts 出现 `compatible = "meizu,e3-panel"` 节点
- **THEN** 内核按 of-modalias 自动加载该模块
- **AND** drm_panel 链路成功 probe，屏可点亮

#### Scenario: timing 与 mode_flags 与 a7a 实板一致

- **WHEN** 检视驱动源码常量
- **THEN** display_mode 含 `hactive=1080 / vactive=2160 / clock=171950 / hfront_porch=229 / hback_porch=4 / hsync_len=4 / vfront_porch=8 / vback_porch=6 / vsync_len=2`
- **AND** `mode_flags = MIPI_DSI_MODE_VIDEO`（不含 `MIPI_DSI_MODE_VIDEO_BURST`）

### Requirement: radxa-dragon-q6a overlay 接线

`device-tree/qcom-qcs6490-radxa-dragon-q6a-meizu-e3-panel.dtso` MUST 按 mainline qcom drm/msm 显示栈编写（**不**复用 rock5b 的 Rockchip DRM overlay，**不**复用 a7a 的 Allwinner sunxi overlay），按 radxa-dragon-q6a 原理图 v1.21 sheet 31（J10 LCD MIPI 39pin FPC）接线生成，且 MUST 满足：

- 显示链路 MUST 使能 `&mdss`、`&mdss_dsi`、`&mdss_dsi_phy`（`vdds-supply = <&vreg_l10c_0p88>`）。
- panel 节点 MUST 用 `compatible = "meizu,e3-panel"`（由本变更新增的 `panel_meizu_e3` OOT 驱动消费）。
- DSI 4-lane MUST 经 OF-graph 端点互连：panel `port@0` ↔ `&mdss_dsi0_out`，`data-lanes = <0 1 2 3>`。
- 屏复位 MUST 接 `&tlmm 44 GPIO_ACTIVE_LOW`（与 8HD 同款 LCD_PANEL_RESET 引脚，原理图 DISP0_RESET_N → R313 → FPC pin 5）；MUST 在 `&tlmm` 节点下配 pinctrl `lcd_panel_reset`（function = "gpio"、`drive-strength = <8>`）。
- LCD 主供电 MUST 经 GPIO 使能的 `regulator-fixed`：使能脚 `&tlmm 80 GPIO_ACTIVE_HIGH`（原理图 LCD_VCC_EN → SGM2578AAD load-switch → VCC_3V3_LCD → FPC pin 2/30/31），`regulator-name = "vcc_3v3_lcd"`；panel `vdd-supply` 引用之。MUST NOT 引用 `&vcc_3v3` 作 `vin-supply`（mainline radxa branch 有此 label，QCLINUX BSP base 不声明；板上 VCC_3V3 是 SY7120RAC buck 输出的 always-on 固定 rail，DT 不建模即可）。`vccio-supply` MUST 引用 `&vreg_l1c_1p8`（PMIC PM7325 LDO L1C，1.8V always-on PMIC 直出），MUST NOT 引用聚合 `&vcc_1v8` label（同理 QCLINUX BSP 不声明）。
- 触摸 `sec_ts@0x48` 与背光 `backlight@0x36` MUST 挂 `&i2c13`（QUP1_SE5 / qupv3_id_1），`clock-frequency = <100000>`，且 MUST 使能 `&qupv3_id_1`。`&i2c13` MUST 声明 `qcom,load-firmware;` boolean——QCLINUX BSP `qcom-geni-se.c::geni_load_se_firmware` 缺此属性时直接 `return -EINVAL` → i2c bus 不上线 → 触摸/背光客户端不实例化（dmesg `Cannot load firmware from linux for i2c error: -22`）。仅 `qcs9075-radxa-airbox-q900.dts` 显式声明此属性，Q6A 必须自己补。
- 触摸节点 `compatible = "sec,sec_ts"`，MUST 用 sec_ts 私有属性 `sec,irq_gpio = <&tlmm 81 0>` 而非 i2c 子系统标准 `interrupts-extended`——sec_ts 驱动 `of_get_named_gpio(np, "sec,irq_gpio", 0)` + 内部 `gpio_to_irq()`，**不**读 `interrupts-extended`；缺则 `Failed to get irq gpio` probe -EINVAL。MUST 声明 `sec,max_coords = <1080>, <2160>`。MUST 声明 `sec,skip-fw-update-on-probe;`（a7a 同款 workaround：跳过开机软复位+强刷固件流程，E3 屏自带固件无需 host 刷写，稳态优先；Q6A 上虽未必必需，加无副作用）。复位脚 `&tlmm 105`（TS_RESET_N → FPC pin 23）MUST 用 `regulator-fixed`（`gpio = <&tlmm 105 GPIO_ACTIVE_HIGH>`、`enable-active-high`、`regulator-always-on`、`regulator-boot-on`）在 boot 时拉高解复位，**MUST NOT 用 gpio-hog**——与 a7a 保持一致以降维护心智。
- 背光节点 `compatible = "sgmicro,sgm37604a"` @ `reg = <0x36>`（屏自带 SGM37604A I2C 背光芯片，FPC pin 26/27 = TP_SDA/SCL 共用 i2c13）；panel `backlight` phandle MUST 引用之；亮度参数（`led-channels` / `max-current` / `default-brightness-level`）MUST 取实机可见档位（沿用 a7a 调好的 `default-brightness-level = <2048>` 等）。
- MUST NOT 引用 `&pm8350c_pwm` / `&pm8350c_gpios` 任何 PWM/GPIO；MUST NOT 声明 `pwm-backlight`——Q6A 板载 SY7203 boost LED 驱动与 E3 屏自带 SGM37604A 是功能互斥的两条背光通道，本 overlay 选 SGM37604A 路径，SY7203 因 EDP_BLPWM 不被引用而保持 disabled，FPC LED+/LED- 输出悬空安全。
- pinctrl group `ts_int_conn`、`ts_rst_conn`、`lcd_panel_reset` MUST 在 `&tlmm` 节点下声明（与 radxa-display-8hd Q6A overlay 同款形态）。

#### Scenario: mainline drm/msm DSI 栈与 OF-graph 正确

- **WHEN** 编译并合并 `qcom-qcs6490-radxa-dragon-q6a-meizu-e3-panel.dtbo` 到 base dtb
- **THEN** `&mdss` / `&mdss_dsi` / `&mdss_dsi_phy` 被使能，panel 4 data-lanes
- **AND** panel `port@0` 端点与 `&mdss_dsi0_out` 互连
- **AND** overlay 中不出现 Rockchip 的 `&dsi1` / `simple-panel-dsi` 或 Allwinner 的 `&dsi0combophy` / `allwinner,panel-dsi`

#### Scenario: 触摸与背光挂 i2c13 + 复位走 regulator-fixed

- **WHEN** overlay 应用到 radxa-dragon-q6a
- **THEN** `&i2c13`（`&qupv3_id_1` 已使能）上出现 `sec_ts@0x48`（`sec,irq_gpio = <&tlmm 81 0>`、`sec,skip-fw-update-on-probe;`）与 `backlight@0x36`（`sgmicro,sgm37604a`）
- **AND** `&i2c13` 节点含 `qcom,load-firmware;` boolean
- **AND** TP-RST（`&tlmm 105`）经 `regulator-fixed`（always-on/boot-on）在 boot 时拉高解复位，overlay 中不出现 `gpio-hog`
- **AND** panel `backlight` phandle 引用 `backlight@0x36`，overlay 中不出现 `pwm-backlight` 也不引用 `&pm8350c_pwm` / `&pm8350c_gpios`
- **AND** sec_ts 节点中**不**出现 `interrupts-extended`（驱动不读，仅 `sec,irq_gpio` 是有效路径）

#### Scenario: LCD 主供电与 reset 链

- **WHEN** overlay 应用到 radxa-dragon-q6a
- **THEN** 存在 `vcc_3v3_lcd: vcc-3v3-lcd-regulator`（`regulator-fixed`、`gpio = <&tlmm 80 GPIO_ACTIVE_HIGH>`、**不**含 `vin-supply`），panel `vdd-supply` 引用之；`vccio-supply` 引用 `&vreg_l1c_1p8`（PMIC LDO 直出）
- **AND** panel `reset-gpios = <&tlmm 44 GPIO_ACTIVE_LOW>`，`&tlmm` 下含 `lcd_panel_reset` pinctrl group
- **AND** 开机时屏供电、复位时序正常，panel 与触摸均能 probe

### Requirement: radxa-dragon-q6a 所需内核内建项

启用本包点亮 radxa-dragon-q6a 屏所依赖的内核功能——qcom mainline drm/msm（`CONFIG_DRM_MSM`）、对应的 mdss_dsi 控制器 / dsi_phy 驱动、qcom GENI/QUP I2C（`CONFIG_I2C_QCOM_GENI`）、qcom tlmm pinctrl（`CONFIG_PINCTRL_MSM`/相应 SoC 子驱动）——MUST 在 radxa-dragon-q6a 内核中可用（`qcom_defconfig` 默认含），无需 defconfig fragment。背光与触摸 MUST 由包内 `sgm37604a` / `sec_ts` 两个 OOT 驱动提供；panel 驱动 MUST 由包内 `panel_meizu_e3` OOT 驱动提供（QCLINUX BSP 6.6.90 内 `drivers/gpu/drm/panel/` 无 `simple-panel-dsi` 等通用 DSI panel 驱动），三个 `.ko` MUST 安装到 `lib/modules/.../updates/` 并随 DT 节点自动加载。

为使 OOT 加载不被拒，QCS6490 SoC config（`components/platform/qualcommqcs6490/qcs6490/config.py::kernel`）MUST 声明 `disable_configs: ["MODULE_SIG_FORCE"]`——qcom_defconfig 默认 `CONFIG_MODULE_SIG_FORCE=y` 拒绝未签名模块加载（modprobe `Key was rejected by service` / dmesg `Loading of unsigned module is rejected`），flange OOT 流水线不签 → 必须关掉强制。OOT 加载 taint kernel `E` flag 但工作；`MODULE_SIG` 本身保留（签名模块仍验证，仅不强制）。与 rk/all/aml 三平台对齐（它们内核都不开 SIG_FORCE）。

为使 i2c-geni 找到 QUP firmware，`components/platform/qualcommqcs6490/overlay/usr/lib/firmware/qupv3fw.elf.zst` MUST 是 symlink 指向 `qcom/qcs6490/qupv3fw.elf.zst`——`request_firmware("qupv3fw.elf")` 在 `/lib/firmware/` 顶层找；linux-firmware deb 实际安装到 `/lib/firmware/qcom/qcs6490/qupv3fw.elf.zst`。内核 `CONFIG_FW_LOADER_COMPRESS_ZSTD=y` 自动解压 `.zst`。overlay 路径 MUST 走 `usr/lib/firmware/...` 而非 `lib/firmware/...`，因 Ubuntu noble usrmerge `/lib -> /usr/lib`、顶层 `lib/` 目录会与 rootfs 中的 `lib` symlink 冲突。

#### Scenario: drm/msm 与 GENI I2C 可用

- **WHEN** 构建 radxa-dragon-q6a 内核（`qcom_defconfig`）
- **THEN** `CONFIG_DRM_MSM=y` 或 `=m`，`CONFIG_I2C_QCOM_GENI=y`，`CONFIG_PINCTRL_MSM=y`
- **AND** mainline drm/msm 可绑定 `&mdss_dsi` 与本变更 dtso 引入的 `meizu,e3-panel` 节点

#### Scenario: 三个 OOT 驱动随节点加载

- **WHEN** board opt-in 选中 `meizu-e3-panel` 包并 build `radxa-dragon-q6a-meizu-e3-bringup-debug`，开机
- **THEN** `sec_ts.ko` / `sgm37604a.ko` / `panel_meizu_e3.ko` 均装到 `lib/modules/<release>/updates/`
- **AND** DT 出现 `sec,sec_ts` / `sgmicro,sgm37604a` / `meizu,e3-panel` 节点时三个模块按 of-modalias 自动加载并 probe（dmesg 出 `taints kernel` + `module verification failed: signature and/or required key missing - tainting kernel` 表示 SIG_FORCE 已关、未签名模块允许加载，是预期行为）

#### Scenario: i2c-geni QUP firmware 加载成功

- **WHEN** 构建 `radxa-dragon-q6a-meizu-e3-bringup-debug` 并刷写上板
- **THEN** rootfs `/usr/lib/firmware/qupv3fw.elf.zst` 是 symlink 指向 `qcom/qcs6490/qupv3fw.elf.zst`
- **AND** dmesg 出 `geni_se ... a94000.i2c: Firmware load for I2C protocol is Success for xfer mode 1`
- **AND** `/sys/bus/i2c/devices/` 含 i2c-13 bus，子设备 `13-0036`（sgm37604a）与 `13-0048`（sec_ts）均存在

### Requirement: radxa-dragon-q6a 启用 meizu-e3-bringup product

`components/board/radxa-dragon-q6a/config.py` MUST 在 `products` 列表中追加 `meizu-e3-bringup`（与既有 `default` 并列），并 MUST 在该 product 条件键下注入 `packages: ["meizu-e3-panel"]`。`default` product MUST 不引入本包，使 `radxa-dragon-q6a-default-{debug,release}` 产物与本变更前**字节等价**。lunch target `radxa-dragon-q6a-meizu-e3-bringup-{debug,release}` MUST 由现有 product/variant 机制自动生成。

#### Scenario: default product 字节等价

- **WHEN** lunch `radxa-dragon-q6a-default-debug`，build 出 raw.img
- **THEN** 与本变更前同一 lunch target 的产物字节等价（cache 命中，hash 不变）

#### Scenario: meizu-e3-bringup product 引入包

- **WHEN** lunch `radxa-dragon-q6a-meizu-e3-bringup-debug`，build
- **THEN** `config["packages"]` 含 `"meizu-e3-panel"`
- **AND** kernel oot_modules 含 `sec_ts` / `sgm37604a` / `panel_meizu_e3`
- **AND** `boot.package_overlays` 含 `qcom-qcs6490-radxa-dragon-q6a-meizu-e3-panel.dtbo`
- **AND** rootfs `/boot/qcs6490-radxa-dragon-q6a.dtb` 是 base dtb 与该 dtbo 经 `fdtoverlay` 合并的产物（见 [[build-time-dtb-overlay-merge]]）

### Requirement: radxa-dragon-q6a 背光路径选择

Q6A 板原理图 v1.21 sheet 31 在 LCD FPC（J10）上同时引出**两条背光通道**：(a) 板载 SY7203DBC boost LED 驱动 → VCC_LEDA / VCC_LEDK → FPC pin 35/39 直驱屏 LED 串（由 PM7350C GPIO_08 的 EDP_BLPWM 控制 EN/PWM）；(b) FPC pin 26/27 = TP_SDA/SCL（QUP1_SE5 i2c13）→ 屏自带 SGM37604A I2C 背光芯片（panel 内部）→ 屏 LED 串。两条通道**功能互斥**：E3 屏在 LED+/LED- 引脚悬空、靠 SGM37604A 内部驱动 LED；本变更 MUST 选 SGM37604A 路径，MUST NOT 引用 EDP_BLPWM 或 SY7203 相关节点（不引用 `&pm8350c_pwm` / `&pm8350c_gpios`、不声明 `pwm-backlight`）。这样 SY7203 EN 默认悬置 → boost 不工作 → LED+/LED- 输出悬空，电气安全。

#### Scenario: 背光由 SGM37604A I2C 驱动

- **WHEN** overlay 应用到 radxa-dragon-q6a 且 `sgm37604a` 模块加载
- **THEN** `&i2c13` 上 `backlight@36` 绑定 sgmicro/sgm37604a，`/sys/class/backlight/sgm37604a` 出现
- **AND** overlay 中不出现 `pwm-backlight` / `&pm8350c_pwm` / `&pm8350c_gpios` 引用
- **AND** PM7350C GPIO_08（EDP_BLPWM）保持默认未配置状态

#### Scenario: 默认亮度可见

- **WHEN** 系统开机
- **THEN** 背光默认亮度处于可见档位（非接近 0 的极暗值），可经 `/sys/class/backlight/sgm37604a/brightness` 调节
