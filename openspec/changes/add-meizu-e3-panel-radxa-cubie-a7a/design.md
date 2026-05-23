## Context

`meizu-e3-panel` 硬件特性包已在 `radxa-rock5b`（RK3588）实机点亮魅族 E3 39pin MIPI-DSI 屏（显示 + 触摸 + 背光）。包含三个 component：`sec_ts`（OOT 触摸）、`sgm37604a`（OOT I2C 背光）、`panel`（按 board 路由的 `.dtso` overlay）。现用户把同一块屏接到 `radxa-cubie-a7a`（Allwinner A733）的 LCD FPC 连接器（J10，原理图 v1.10），要在该板点亮。

a7a 首版（变更 `add-a733-radxa-cubie-a7a`）已贯通 platform→SoC→board，但 board.dts 的 `&dsi0/panel@0` 是 `allwinner,virtual-panel` 占位，DSI 主屏点亮被列为 Non-Goal。本变更补上这块。

约束：
- flange 坚持 OOT 驱动路线，不打内核补丁；`builder/` 与 `components/platform/allwinnera733/` 本次零改动。
- a7a 已有 `default` product（HDMI 直出裸机），新增 product MUST 不回归 default 产物。
- 引脚必须从 a7a 原理图实锤，不照抄 rock5b（不同 SoC、不同连接器）。

## Goals / Non-Goals

**Goals:**
- 给 `meizu-e3-panel` 包补一份 A733/cubie-a7a 专属 panel overlay，复用包内 `sec_ts` / `sgm37604a` 两个 OOT 驱动（驱动逻辑不变，仅补跨内核兼容垫片，见决策 6）。
- 给 `radxa-cubie-a7a` 加 `meizu-e3-bringup` product，照搬 rock5b 的 product/条件键机制，实现「一行 opt-in 点屏」。
- 证明同一硬件特性包跨 SoC（RK3588 → A733）复用：DT overlay 按目标显示栈重写，驱动逻辑不变（跨内核 API 差异以版本守卫垫片吸收）。

**Non-Goals:**
- 不改 `builder/`、不改 SoC 平台层、不改 `default` product、不改 rock5b 取值（见 proposal 非目标）。
- 不接 `LCD-PWM`(PD22) / `TP-SENSOR`(PD15)。
- 不做 HDMI/DSI 双显切换策略。

## Decisions

### 决策 1：A733 overlay 不移植 rock5b，按 sunxi 显示栈重写，骨架抄 radxa-display-8hd

rock5b overlay 是 Rockchip DRM 栈：`&dsi1` + VOP `&route_dsi1`/`vp3_out_dsi1` + `simple-panel-dsi` + `rockchip,pins`。A733 是 Allwinner sunxi 栈，节点模型完全不同，无法移植。

**选定**：照搬同连接器的 vendor overlay `cubie-a7a-radxa-display-8hd.dtso` 作为显示骨架——
- 使能 `&dsi0combophy` / `&dlcd0` / `&dsi0`（4-lane，`dsi0_4lane_pins_a/b`）。
- 复用 board.dts 既有 `panel: panel@0`（`allwinner,virtual-panel`）作为 DSI↔真实 panel 的 OF-graph 中转：virtual-panel 的 `port@1` → 真实 `dsi_panel` 节点的 `port`。
- 真实 panel 用 `compatible = "allwinner,panel-dsi"`（A733 BSP 通用 DSI panel 驱动）。

**Alternatives considered**：
- *直接改 board.dts 的 virtual-panel 为真实 panel*：board.dts 来自外部 `allwinner-device` 子模块，多 board 共享，改它越权且污染 default；overlay 是正解。
- *从零手写 sunxi DSI 绑定*：8hd 是 Radxa 给同一连接器做的官方屏，引脚/电源轨/OF-graph 已验证，抄它零风险。

### 决策 2：背光沿用 sgm37604a，不用 8hd 的 pwm-backlight

魅族 E3 屏自带 SGM37604A I2C 背光芯片（@0x36），在屏模组上、与载板无关——rock5b 用的就是它。8hd 模板用 `pwm-backlight`（经载板 PD22/PWM0-4），那是 8hd 屏的接法，不适用 E3。

**选定**：a7a 与 rock5b 同样 opt-in `[sec_ts, sgm37604a]`；overlay 在 `twi2` 上声明 `backlight@36`（`sgmicro,sgm37604a`），panel `backlight` phandle 引用之，使能脚 `&pio PD 23`（LCD_light_EN）。亮度参数平移 rock5b 实机调好的档位（`led-channels`/`max-current`/`default-brightness-level=2048`）。

`allwinner,panel-dsi` 驱动通过标准 `backlight = <&...>` phandle 解析背光（已读 `panel-dsi.c` 确认 `panel->backlight`），与 rock5b 同构。

### 决策 3：init/exit 序列与 timing 从 rock5b 平移

读 A733 BSP `bsp/drivers/drm/panel/panel-dsi.c` 确认：`allwinner,panel-dsi` 消费的 `panel-init-sequence` 字节格式为 `[data_type delay payload_length payload...]`，与 rock5b `simple-panel-dsi` **完全一致**。魅族 E3 是「傻」屏（IC 自配置），序列极短：

```
panel-init-sequence = [ 05 78 01 11   05 0A 01 29 ];   // sleep-out(120ms) + display-on(10ms)
panel-exit-sequence = [ 05 00 01 28   05 00 01 10 ];   // display-off + sleep-in
```

timing 平移 rock5b：1080×2160 @ 157MHz，4-lane。

**注意头文件差异**：DSI flags/format 用 `<dt-bindings/display/sunxi-lcd.h>`（`MIPI_DSI_MODE_VIDEO=1` 等 sunxi 位定义、format 用数字），**非** rock5b 的 `<dt-bindings/display/drm_mipi_dsi.h>`。

### 决策 4：引脚从 a7a 原理图 v1.10 实锤，与 8hd 同连接器 1:1 印证

a7a 的 LCD FPC（J10，41pin）连接器引脚（原理图网络名 → A733 PIO ball，2026-05-23 实读 SoC pinout P7 + 电源页 P4，并与 8hd overlay 双重印证）：

| 信号 | 网络名 | A733 PIO / 总线 | 8hd 印证 |
|------|--------|----------------|----------|
| 触摸+背光 I2C | `TWI2-SCK`/`TWI2-SDA` | PD16 / PD17，`function="twi2"` | ✓ |
| 触摸中断 | `TP-INT` | `&pio PD 18` (PD-EINT18) | ✓ gt911 irq PD18 |
| 触摸复位 | `TP-RST` | `&pio PD 19` (PD-EINT19) | ✓ gt911 reset PD19 |
| 屏复位 | `LCD-RST` | `&pio PD 21` (PD-EINT21) | ✓ reset-gpios PD21 |
| 背光使能 | `LCD_light_EN` | `&pio PD 23` (PD-EINT23) | ✓ backlight en PD23 |
| 3.3V 电源轨 | `VCC33-LCD` | `&reg_dc1sw1`（SW OUT1, 3.3V 可开关） | ✓ power0-supply |
| 1.8V 电源轨 | `VCC18-LCD` | `&reg_bldo2`（=VCC-PD bank IO） | ✓ power1-supply |

DSI 数据走 DSI0 4-lane（PD0–PD9：`MIPI-DSI0-DP0..DP3` + `CKP/CKN`），与 board.dts `&dsi0` + `dsi0_4lane_pins_a/b` 对应。

`sec_ts` 触摸节点：`compatible="sec,sec_ts"`、`reg=<0x48>`、`sec,irq_gpio=<&pio PD 18 ...>`（驱动内部 `gpio_to_irq`）、`sec,max_coords=<1080>,<2160>`。复位脚 PD19 沿用 rock5b 思路（sec_ts 驱动不管理 reset，用 `&pio` gpio-hog 输出高解复位）。

### 决策 5：board 加 product 照搬 rock5b 条件键机制

`radxa-cubie-a7a/config.py` 改动（与 rock5b 同构）：
```python
"products": ["default", "meizu-e3-bringup"],
"+packages:meizu-e3-bringup": [
    {"name": "meizu-e3-panel", "drivers": ["sec_ts", "sgm37604a"]},
],
"boot": {
    ...,
    "+default_overlays:meizu-e3-bringup": [
        "sun60i-a733-cubie-a7a-meizu-e3-panel.dtbo",
    ],
},
```
`default` product 不带条件键内容，产物 byte-identical。`package.py` 的 `panel.overlays` 追加 `"radxa-cubie-a7a": "device-tree/sun60i-a733-cubie-a7a-meizu-e3-panel.dtso"`。

### 决策 6：OOT 驱动跨内核兼容用版本守卫垫片（实施中发现）

原假设「sec_ts/sgm37604a 驱动零改动」被构建证伪：这两个 Android 系 vendor 驱动隐式依赖 Rockchip 6.1 BSP 的内核 API，在 A733 主线系 5.15 上有两处不兼容：
1. `sec_ts` 硬包含 `<linux/wakelock.h>`——该头早被主线移除（被 wakeup_source 取代），Rockchip BSP 自带 Android 兼容头，A733 5.15 无。
2. 两驱动的 i2c `.remove` 回调：6.1 起返回 `void`，5.15 为 `int`（`-Werror=incompatible-pointer-types` 致命）。

**选定：版本守卫 + 兼容垫片，不动驱动业务逻辑、不碰内核**——
- wakelock：新增 `driver/sec_ts/sec_ts_wakelock.h`，用 `__has_include(<linux/wakelock.h>)` 分流：有则用原生（rock5b），无则把 `wake_lock_init`/`wake_lock_timeout` 映射到 `wakeup_source_register`/`__pm_wakeup_event`（A733）。源文件改 include 即可。
- remove：用 `LINUX_VERSION_CODE >= KERNEL_VERSION(6,1,0)` 分流函数签名与返回值。

**为何这样而非别的**：
- *改 board.dts/SoC 层*：无关，这是驱动源问题。
- *用 `-I` 注入 wakelock.h 覆盖*：依赖 kbuild include 顺序、会在 rock5b 上覆盖原生头（行为风险）；`__has_include` 显式且 rock5b 零变化。
- *换 5.15 版 sec_ts*：换整套驱动代价大、丢失 rock5b 已验证状态。

**代价**：驱动源不再是「零改动」；共享驱动改动会失效 rock5b 内核内容哈希、触发一次重编（版本守卫保证产物功能等价）。已验证 a733 两 .ko 干净编出 + 装入 `updates/`。

## Risks / Trade-offs

- [改共享驱动源影响 rock5b] → 改动全用版本守卫（`__has_include` / `LINUX_VERSION_CODE`），rock5b 6.1 命中原生路径、代码路径不变；但内容哈希变化触发 rock5b 内核重编（产物功能等价）。回归确认 rock5b meizu-e3-bringup 仍正常编出（task 3.4）。

- [触摸坐标方向在 a7a 机械朝向下可能不对] → `sec,max_coords` 与 X/Y 翻转属软件调参，上电后用 `evtest` 标定；列为实测验收项，不阻塞接线。
- [E3 1080×2160@157MHz 比 8hd 800×1280@70MHz 高一倍带宽，DSI combophy/PHY 时钟可能需调] → 首版按 8hd 的 `dsi0combophy`/`dlcd0` 默认时钟点屏；若花屏/不亮，查 DE `assigned-clock-rates` 与 DSI PHY，必要时起 SoC 平台层独立变更（本变更不碰 platform）。
- [`allwinner,panel-dsi` 对 init-sequence 短序列是否够] → E3 在 rock5b 仅 sleep-out+display-on 即点亮，A733 同格式驱动应一致；若不亮先确认 reset 时序（`reset-num`/`reset-delay-ms`/`reset-on/off-sequence`）。
- [HDMI 默认直出与 DSI 屏共存] → 8hd overlay 不关 HDMI，A733 DE 支持双 VO（board.dts `&vo0/&vo1` 均 okay）；首次点屏确认默认输出落点，必要时调 `route`/优先级。
- [package.py 追加映射键影响 rock5b] → 仅新增 `radxa-cubie-a7a` 键，rock5b 取值与产物不变；回归验证 rock5b meizu-e3-bringup 与 a7a default 产物。

## Bring-up 实测结论（2026-05-23/24，实板 radxa-cubie-a7a + 魅族 E3 屏）

显示已实板点亮（modetest SMPTE 彩条 + fbcon 控制台清晰稳定）。过程推翻了多个初始假设，最终获胜配置与关键教训如下：

### 显示获胜配置（已验证）

- **timing 来自 E3 屏原厂高通 panel DT（三星 s6d6ft0 / Tianma FHD），不是 rock5b 平移值**：
  `htotal=1317`（hfp **229** / hbp **4** / hsync **4**）、`vtotal=2176`（vfp **8** / vbp **6** / vsync **2**）、`clock-frequency=171947520`（60Hz）。
  早先抄 rock5b 的 hfp115/hbp13/hsync3→htotal **1211** 是**斜纹(shear)根因**。
- **`dsi,flags = <(MIPI_DSI_MODE_VIDEO)>`（非 burst）**：与同板可工作的 `radxa-display-10fhd` 一致。
  burst（VIDEO_BURST + NO_EOT + CLOCK_NON_CONTINUOUS）在 A733 上出**细密竖条纹+抖动**；非 burst 干净。
  注：高通原厂 panel DT 写的是 `traffic-mode=burst_mode`，但 Allwinner 的 burst 实现与之不等价，实测非 burst 才对。
- TP 复位 PD19 用 **`regulator-fixed`（always-on/boot-on）** 解除，**不能用 Rockchip 风格 gpio-hog**——
  sunxi pinctrl 的 `&pio` 子节点必须是 pinmux group，放 gpio-hog 会让主 pinctrl probe 挂掉、连带 MMC 失去引脚、内核找不到 rootfs **启动卡死**（本次踩坑，已改 regulator-fixed）。

### 关键教训

- **变量纠缠会误导**：早先「非 burst 不出图、必须 burst」的结论是在 timing 还错(htot1211)时测的、无效。timing 修对后非 burst 才是正解。改一个变量、验一个。
- **远程隔屏调显示低效**：用 `modetest -s 147:1080x2160`（libdrm-tests）出稳定测试图 + 保持管线活跃，是远程判断画质的关键手段（用户态写 /dev/fb0、/dev/tty0 唤不醒已 gate 的 DRM 管线）。
- **fbcon 默认在 dummy**：本镜像 `vtcon0=dummy` 占用控制台、`vtcon1=frame buffer device` 未绑，故开机后/modetest 退出后面板黑。`echo 1 > /sys/class/vtconsole/vtcon1/bind` 可让控制台常驻面板（开机自动绑定属独立 console 配置，待收尾）。

### 触摸（未完成，待续）

- 触摸 `sec_ts@0x48`(twi2) 引脚已对原理图核实正确（TP-INT=PD18、TP-RST=PD19、TP-SCL/SDA=PD16/17、TP-VCC=VCC18-LCD 1.8V 已供电、I2C 上拉 2.2K 已贴）。
- 现象：芯片 I2C **NACK 不应答**（同总线背光 sgm37604a@0x36 正常），驱动注册了 input 但运行期 `i2c read one event failed` 刷屏。
- 已排除：电源（TP-VCC=VCC18-LCD 已上）、复位（PD19 实测 out hi 已解除）、总线/上拉、地址（rock5b 同模组 @0x48 验证）。
- 头号嫌疑：s6d6ft0 是 TDDI（触显一体），触摸 I2C 可能需显示**活动扫描**时才唤醒；待干净验证（开机即让显示活动后再看 NACK 是否停）。次选：上电后需复位**脉冲**而非常高、或 IRQ 极性。
