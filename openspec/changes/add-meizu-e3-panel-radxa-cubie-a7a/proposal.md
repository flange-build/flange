## Why

`radxa-cubie-a7a`（Allwinner A733）首版交付时刻意把 MIPI DSI 主屏点亮归为 Non-Goal——board.dts 的 `&dsi0/panel@0` 是 `allwinner,virtual-panel` 占位，需具体面板 init 序列方可点亮。现用户已把魅族 E3 39pin MIPI-DSI 屏（显示 + 触摸 + 背光）接到 a7a 的 LCD FPC 连接器（J10，原理图 v1.10），需要在该板点亮这块屏。这块屏的复用包 `meizu-e3-panel`（含 `sec_ts` 触摸 + `sgm37604a` 背光两个 OOT 驱动）已在 `radxa-rock5b` 落地并实机点亮，本变更把它扩展到第二块实板，验证「同一硬件特性包跨 SoC 复用」——核心是新增 A733 专属 DT overlay 并给 a7a 加一个 product；OOT 驱动逻辑不变，但实测发现需补两处 6.1→5.15 跨内核兼容垫片（详见 What Changes，均以版本守卫实现，rock5b 行为不变）。

## What Changes

- **`meizu-e3-panel` 包新增 A733 overlay**：新增 `components/packages/meizu-e3-panel/device-tree/sun60i-a733-cubie-a7a-meizu-e3-panel.dtso`，按 Allwinner sunxi 显示栈编写（`&dsi0` + `&dlcd0` + `&dsi0combophy` + `allwinner,virtual-panel` 的 OF-graph 转接 + `allwinner,panel-dsi` 真实 panel 节点）。**不能移植** rock5b 的 Rockchip DRM overlay（`&dsi1`/VOP VP3/`simple-panel-dsi` 与 sunxi 栈完全不同），显示骨架照搬同连接器的 `cubie-a7a-radxa-display-8hd` vendor overlay。
- **`package.py` 注册 a7a overlay 映射**：`panel` component 的 `overlays` 映射追加一行 `"radxa-cubie-a7a": "device-tree/sun60i-a733-cubie-a7a-meizu-e3-panel.dtso"`。
- **`radxa-cubie-a7a` 新增 `meizu-e3-bringup` product**：照搬 rock5b 的 product 机制——`products: ["default", "meizu-e3-bringup"]`、`"+packages:meizu-e3-bringup": [{"name": "meizu-e3-panel", "drivers": ["sec_ts", "sgm37604a"]}]`、`"+default_overlays:meizu-e3-bringup": ["sun60i-a733-cubie-a7a-meizu-e3-panel.dtbo"]`。`default` product 维持纯裸机（HDMI 直出 + 板载音频），不挂屏。
- **背光沿用 `sgm37604a`**：魅族 E3 屏自带 SGM37604A I2C 背光芯片（@0x36），与载板无关，a7a 与 rock5b 同样选 `[sec_ts, sgm37604a]` 两个 OOT 驱动，**不**使用 8hd 模板的 `pwm-backlight`。
- **OOT 驱动跨内核兼容垫片**（实施中发现，原「驱动零改动」假设证伪）：sec_ts/sgm37604a 是 Android 系 vendor 驱动，隐式依赖 Rockchip 6.1 BSP 的内核 API，在 A733 主线系 5.15 上有两处不兼容，均以**版本守卫**修复（rock5b 6.1 走原生路径、行为不变）：① `sec_ts` 硬包含 5.15 已无的 `<linux/wakelock.h>`——新增 `driver/sec_ts/sec_ts_wakelock.h` 兼容垫片（`__has_include` 守卫，回退到现代 wakeup_source）；② 两驱动的 i2c `.remove` 回调签名 6.1 改 `void`、5.15 为 `int`——以 `LINUX_VERSION_CODE` 守卫分流。
- **引脚全部从 a7a 原理图 v1.10 实锤**（与 `radxa-display-8hd` 同连接器 1:1 印证）：触摸 + 背光 I2C 走 `twi2`（PD16/PD17）；触摸中断 `&pio PD 18`、复位 `&pio PD 19`；屏复位 `&pio PD 21`；背光使能 `&pio PD 23`；电源轨 `&reg_dc1sw1`（VCC33-LCD 3.3V）/ `&reg_bldo2`（VCC18-LCD 1.8V）。DSI 走 DSI0 4-lane（PD0–PD9）。
- **init/exit 序列与 timing 从 rock5b 平移**：`allwinner,panel-dsi` 与 rock5b 的 `simple-panel-dsi` 消费**同一种** `panel-init-sequence` DCS 字节格式；魅族 E3 序列极短（`05 78 01 11` sleep-out + `05 0A 01 29` display-on），逐字节平移；timing 沿用 1080×2160@157MHz。DSI flags/format 改用 `<dt-bindings/display/sunxi-lcd.h>` 常量（非 Rockchip 的 `drm_mipi_dsi.h`）。
- **新增知识库条目**：`wiki/boards/radxa-cubie-a7a.md` 补 meizu-e3-bringup product 段落，`wiki/concepts/硬件特性包.md` 补「跨 SoC 复用」实例。
- **零改动** `builder/`：包机制、product/variant、device-tree-overlay 流水线均已就绪；lunch target `radxa-cubie-a7a-meizu-e3-bringup-{debug,release}` 由现有机制自动生成。

## Capabilities

### New Capabilities

（无——本变更不引入新 capability。a7a overlay 接线、product 启用、所需 A733 内核内建项均落在既有 `meizu-e3-panel` capability 契约内扩展。）

### Modified Capabilities

- `meizu-e3-panel`：在既有「包结构与内容」「rock5b overlay 接线」「rock5b 背光走 sgm37604a」「所需内核内建项」之外，新增 **radxa-cubie-a7a overlay 接线**（Allwinner DSI0 栈 + `allwinner,panel-dsi` + twi2/PD 引脚组 + 电源轨 + init/exit/timing）、**radxa-cubie-a7a 启用 meizu-e3-bringup product**（products 维度 + packages opt-in + default_overlays）、**radxa-cubie-a7a 所需内核内建项**（A733 BSP 的 `allwinner,panel-dsi` / sunxi DSI / dlcd0 / dsi0combophy 内建可用）三条 Requirement；并更新「包结构与内容」承认 `overlays` 映射含 `radxa-cubie-a7a`。

## Impact

- **代码层** `builder/`：零改动。
- **内容层** `components/`：
  - 新增 `components/packages/meizu-e3-panel/device-tree/sun60i-a733-cubie-a7a-meizu-e3-panel.dtso`。
  - 新增 `components/packages/meizu-e3-panel/driver/sec_ts/sec_ts_wakelock.h`（wakelock 兼容垫片）。
  - 修改 `components/packages/meizu-e3-panel/driver/sec_ts/{sec_ts_main.c,sec_ts_selftest.c}`（改用垫片头 + i2c remove 版本守卫）。
  - 修改 `components/packages/meizu-e3-panel/driver/sgm37604a/sgm37604a.c`（i2c remove 版本守卫）。
  - 修改 `components/packages/meizu-e3-panel/package.py`（overlays 映射追加一行）。
  - 修改 `components/board/radxa-cubie-a7a/config.py`（加 products 维度 + 条件键 packages / default_overlays）。
- **外部依赖**：`allwinner,panel-dsi` 驱动位于 A733 BSP `linux-a733` 的 `bsp/drivers/drm/panel/panel-dsi.c`（已 cache，2026-05-23 读源确认消费 `panel-init-sequence` DCS 字节格式、`backlight` phandle、`power%d-supply`/`reset-gpios`）；显示骨架参照 `device-tree-overlay` 组件内 `cubie-a7a-radxa-display-8hd.dtso`（已 cache）。
- **回归范围**：`radxa-cubie-a7a-default-{debug,release}` 产物 MUST byte-identical（新增 product 仅在 lunch `meizu-e3-bringup` 时注入包内容，default 不受影响）。`radxa-rock5b` 的 meizu-e3-bringup：package.py 仅追加映射键、config 取值不变，但**驱动源改动**（兼容垫片）会失效 rock5b 内核内容哈希触发重编；版本守卫保证 rock5b 6.1 走原生路径（wakelock 原生头 + remove 返回 void），编译产物功能等价，需回归确认。
- **lunch target**：`radxa-cubie-a7a-meizu-e3-bringup-debug` / `-release` 自动生成，无 CLI 改动。
- **Flash 工具链**：完全复用 `AllwinnerA733FlashStrategy`，与 default product 同 boot0/分区布局。
- **实测验收项**：上电点屏后用 `evtest` 校准触摸坐标方向（`sec,max_coords` 与 X/Y 翻转/镜像在 a7a 机械朝向下可能需重标），属实测调参非接线未知。

## 非目标

- **不**修改 `builder/` 任何代码：包机制 / product / overlay 流水线已就绪，本变更纯内容增量。
- **不**修改 `components/platform/allwinnera733/`：SoC 层多 board 共享；若实测发现需 SoC 层调整（如 DSI PHY 时钟、defconfig 补 panel 内建项），起独立平台层变更。
- **不**改 `default` product 行为：default 维持 HDMI 直出裸机，不挂屏、不带 OOT 驱动与 panel overlay。
- **不**把 `sec_ts` / `sgm37604a` 改为 in-tree 内核补丁：坚持 flange OOT 路线（兼容垫片是 vendored 驱动自身的跨内核移植，非内核补丁）。
- **不**改动 rock5b 的 overlay / product / config 取值：package.py 仅追加 a7a 映射键。共享驱动源的兼容垫片以版本守卫隔离，rock5b 6.1 行为不变（但会触发一次内核重编，见回归范围）。
- **不**接 `LCD-PWM`（PD22/PWM0-4）：E3 背光经 I2C 寄存器调光、使能走 PD23，与 rock5b 一致不用硬件 PWM；除非实测发现 SGM37604A 需 PWM dimming 输入再起独立变更。
- **不**接次要触摸信号 `TP-SENSOR`（PD15）：sec_ts 基本功能不需要。
- **不**为其他 A733 板（a7z/a7s/a5e）适配该屏：本次仅 a7a。
- **不**实现 HDMI/DSI 双显切换策略：仅声明 overlay 随 boot.img 入盘并默认应用，双显共存行为由 A733 DE 默认决定，首版以点亮 DSI 屏为验收。
