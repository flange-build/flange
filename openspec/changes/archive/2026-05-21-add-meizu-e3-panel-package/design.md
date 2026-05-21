## Context

flange 已有两套不打内核补丁的外设接入机制，但来源位置都被硬编码，无法跨板复用成「一组配套件」：

- **OOT 模块**（`builder/kernel_base.py`）：`kernel.oot_sources`（git 源）+ `kernel.oot_modules`（`make M=<dir>` → strip → 装入 `lib/modules/.../updates/`）。rock5b 已用此路编 rtl8852be。`builder/source.py` 已支持 `local_path` / `source='local'` 的非 git 本地源。
- **board overlay**（`builder/dtb_overlay.py` + device-tree-overlay 组件）：`boot.board_overlays` + `components/board/<board>/dtso/<stem>.dtso` → cpp+dtc → `.dtbo` → boot 分区 `/dtbs/<vendor>/overlay/`，可经 `boot.default_overlays` 默认挂载。

参考件 `/Users/eki/Downloads/radxa-meizu-e3` 是同一块魅族 E3 屏在 **rk3576 rock-4d** 上的适配（sgm37604a I2C 背光 + sec_ts 触摸 + DSI panel dtsi），全程走 armbian 内核补丁。本变更要把它移植到 **rk3588 radxa-rock5b**，并沉淀为可复用的包机制。

rock5b 接线已由原理图 `components/board/radxa-rock5b/docs/radxa_rock_5b_v1423_sch.pdf` (v1.423) 实证，与 rk3576 完全不同（详见 Decisions）。

## Goals / Non-Goals

**Goals:**

- 引入 `components/packages/` 通用包：一个 `package.py` 清单声明若干带 `type` 的 component，引擎按 type 分发到现有 OOT / overlay / deb 流水线。
- board 用 `packages: [...]` 一行 opt-in；包内容纳入内容哈希。
- `oot-driver` 支持按需编译：包内驱动仅当被实际引用时才编。
- 落地 `meizu-e3-panel` 包并点亮 rock5b 的屏（显示 + 触摸 + 背光）。

**Non-Goals:**

- 不做包间依赖 / 版本约束 / 远程包仓库。
- 不把驱动改成 in-tree 内核补丁。
- `deb` 类型仅在 schema 预留，不落地具体 deb。
- 不适配 rock5b 之外的板子。

## Decisions

### 决策 1：包清单用 `package.py`（Python dict），不用 YAML

沿用 flange 全仓 `config.py` 的 Python 配置约定（board/SoC/platform 全是 `config.py` 返回 dict），包清单同构。形态：

```python
# components/packages/meizu-e3-panel/package.py
PACKAGE = {
    "name": "meizu-e3-panel",
    "description": "魅族 E3 39pin MIPI-DSI 屏（显示 + 触摸 + 背光）",
    "components": [
        {"type": "oot-driver", "name": "sec_ts",    "dir": "driver/sec_ts",
         "ko_pattern": ["sec_ts.ko"]},
        {"type": "oot-driver", "name": "sgm37604a", "dir": "driver/sgm37604a",
         "ko_pattern": ["sgm37604a.ko"]},
        {"type": "devicetree", "name": "panel",
         "overlays": {"radxa-rock5b":
                      "device-tree/rk3588-rock-5b-meizu-e3-panel.dtso"}},
    ],
}
```

**备选**：YAML/TOML 声明式清单。否决——会引入第二套配置语言，且 Python dict 能直接 deep_merge 进现有配置体系，类型分发也更直接。

### 决策 2：引擎按 type 分发到既有流水线，包机制只做「胶水层」

新增 `builder/packages.py` 负责：加载 board `packages` 列表 → 读取各包 `package.py` → 按 component `type` 合成既有构建输入：

```
type=oot-driver  → 合成 kernel.oot_modules 条目，dir 指向包目录的本地路径
                   (复用 source.py local_path)，make_args 注入标准
                   KSRC/M/ARCH/CROSS_COMPILE → 复用 _compile/_install_oot_modules
type=devicetree  → 取该 board 对应的 .dtso → 复用 device-tree-overlay 的 cpp+dtc
                   → 作为「package overlay」第四源注册进打包集合
type=deb         → 复用 rootfs deb 安装路径（本次仅预留）
```

底层编译/安装能力全部复用，不重写。

**备选**：让包机制自带独立的编译实现。否决——重复造轮子，且会与现有 OOT/overlay 行为分叉。

### 决策 3：`oot-driver` 按需编译（方案 A）

包内可携带多个 OOT 驱动，但**只编译被实际启用的**。判定规则：当某 board 启用包时，该 board 对应的 overlay 引用了哪些驱动（compatible / 节点），就编哪些；或由 board 在 opt-in 时显式声明启用子集。rock5b 用 pwm-backlight，不引用 sgm37604a，故 sgm37604a 随包保留但不编。

**实现取向**：board opt-in 形式支持「整包」与「按需选 component」两种粒度，例如
`"packages": ["meizu-e3-panel"]`（取该包对此 board 声明的默认集）或显式
`{"name": "meizu-e3-panel", "drivers": ["sec_ts"]}`。rock5b 用后者只取 sec_ts。

**备选**：opt-in 即编全部驱动（未引用的 .ko 装进 rootfs 但不绑定）。否决——浪费编译时间、污染 modules，且 sgm37604a 在 rock5b 上无对应硬件、徒增体积。

### 决策 4：package overlay 作为 overlay 第四源

`extlinux-dtb-overlays` 现有三源（in-tree / vendor / board）。package devicetree 编出的 `.dtbo` 加入为第四源，与三源同等：纳入打包集合、参与 `default_overlays` 子集校验、参与 basename 全局唯一约束（撞名即失败）。`cache.py` 的 board overlay 源目录哈希逻辑扩展到包的 device-tree 目录。

### 决策 5：rock5b overlay 接线（原理图 v1.423 实证）

| 功能 | 信号网络 | rk3588 落点 | 设备树落点 |
|------|----------|-------------|-----------|
| DSI | MIPI_DPHY1_TX ×4lane | dsi1 | `&dsi1` + `route_dsi1`/`dsi1_in_vp3`/`vp3_out_dsi1` |
| 触摸 I2C | I2C6_M0 | i2c6（已 okay，m0，RTC@0x51） | `&i2c6` 加 `sec_ts@0x48` |
| 触摸 reset | TP_RST_L | gpio0 RK_PC6 | sec_ts reset-gpio |
| 触摸 irq | TP_INT_L | gpio0 RK_PD3 | sec_ts irq-gpio |
| 屏复位 | LCD_RESET | gpio2 RK_PC1 | panel reset-gpios |
| 背光使能 | LCD_light_EN | gpio2 RK_PC2 | pwm-backlight enable-gpios |
| 背光调光 | LCD_PWM | gpio4 RK_PC2 = PWM2 (M2) | `&pwm2` + pwm-backlight pwms |
| 屏供电 | LCD_3V3 / VCC_1V8_S0 | regulator-fixed | power-supply |
| LED 供电 | VCC_LEDA / VCC_LEDK | 板载 MP3302 boost | （硬件，由 pwm-backlight 控） |

与 rk3576 参考的差异：DSI `dsi`(单)→`dsi1`+vp3；I2C `i2c0`→`i2c6`；背光 sgm37604a(I2C)→ **pwm-backlight**（内核内建）；GPIO bank 全变。overlay 照 rk3588 重写，参考 `rk3588-orangepi-5-plus-lcd.dtsi` 同 BSP 模板。

### 决策 6：内核内建项确认

显示链依赖 `simple-panel-dsi`（rockchip drm panel-simple）与 `CONFIG_BACKLIGHT_PWM`。先确认 rock5b BSP defconfig 已内建；缺则在 SoC defconfig fragment 补，不新增 OOT 模块。

### 决策 7：overlay 新增根级节点必须包进显式 fragment（U-Boot 2017.09 兼容）

radxa-rock5b 的 BSP U-Boot 是 **2017.09**（Rockchip fork），其 libfdt
`overlay_symbol_update()` 硬性要求 overlay 内每个带 label 节点的符号路径都是
`/<fragment>/__overlay__/...`。若把带 label 节点直接写在 overlay 根
（`/ { vcc3v3_lcd: ...; }`），dtc 导出根相对符号 `/vcc3v3-lcd`，老 libfdt 在
`strchr(path+1,'/')` 找不到第二个 `/` 时 `return FDT_ERR_BADOVERLAY`，
`fdt_overlay_apply` 整体失败、U-Boot 连 base DTB 都加载不了 → boot 挂死。

**修复**：所有新增根级节点（regulator / backlight）包进显式
`fragment { target-path = "/"; __overlay__ { ... } }`，符号即变
`/fragment@N/__overlay__/...`，老 libfdt 接受。

**验证方式**：用 BSP U-Boot 自带 libfdt 源（`scripts/dtc/libfdt/fdt_overlay.c`）
编离线 harness 复现 `fdt_overlay_apply`——修复前 `overlay_symbol_update` 返回
`-16 FDT_ERR_BADOVERLAY`，修复后五步全 `0`。新版 libfdt（宿主 `fdtoverlay`）
容忍根相对符号，故离线宿主工具无法复现，必须用 BSP 同源 libfdt 验证。

**备选（已否决）**：构建期 fdtoverlay 合并进 base DTB、extlinux 不写
fdtoverlays。可彻底绕开 U-Boot overlay apply，但偏离 flange「per-board 运行时
overlay」设计；overlay 结构修复后运行时已可靠，无需引入第二套机制。

### 决策 8：实机 bringup 修正（supersedes 决策 5 背光部分）

决策 5 初判 rock5b 背光走板载 MP3302 + 内核 pwm-backlight，**实机验证后证明错误**。对照用户提供的 rock-5c 同屏 dtsi + 逐步实机调试，最终接线修正为：

- **背光 = 面板自带 SGM37604A I2C 芯片**（`backlight@36` 挂 i2c6，`compatible="sgmicro,sgm37604a"`），由包内 `sgm37604a` OOT 驱动控制；使能脚 GPIO0-A0 = `gpio0 RK_PA0`。rock5b 连接器的 MP3302/VCC_LEDA 是板原生背光，**这块屏不走**。rock5b opt-in 因此改为同时选 `sec_ts` + `sgm37604a`。
- **OF-graph 端口必需**：dsi1 `port@1` ↔ panel `port@0` 端点。缺则 `dw-mipi-dsi2` `drm_of_find_panel_or_bridge(port=1)` 返回 `-19 Failed to find panel or bridge`。
- **LCD 供电必需**：LCD_3V3 由 `LCD_PWREN_H = gpio1 RK_PC4` 经板载负载开关使能（原理图 page23/15）。做成 GPIO 使能的 always-on regulator-fixed，panel `vdd-supply` 引用之；否则 panel 与触摸均无电（触摸 I2C 不应答 / 屏不亮）。
- **亮度参数**：`led-channels=0x1F`(4 路) + `max-current=0x03`(40mA) + `default-brightness-level=2048`(~50%)。原值 `default-brightness-level=128`(≈3%) 致「非常非常暗」。

**调试方法论**：用 BSP 同源 libfdt 离线 harness 验证 overlay apply；用 `modetest -s` 强制 SMPTE 测试图确认显示管线（区分「显示没出图」vs「纯背光问题」）；用 python `/dev/i2c-6` ioctl 在线改 sgm37604a 寄存器定位亮度参数。

## Risks / Trade-offs

- **sec_ts OOT 编译可行性**（最高风险）→ 先做验证 spike：把 `driver/sec_ts` 对 rk3588 BSP 6.1 内核 `make M=` 试编，确认头文件/符号/固件不依赖内核 in-tree 改动。若失败，回退到 in-tree 补丁路线并记录在 Open Questions。
- **panel 节点 compatible 与 init-sequence 移植** → 参考用 `simple-panel-dsi` + 厂商 init/exit sequence；rk3588 BSP 的 panel-simple-dsi 若 of_match 或时序属性不同，按 BSP 实际属性名调整，以 `rk3588-orangepi-5-plus-lcd.dtsi` 为对照。
- **dsi1 + DCPHY1 使能** → rk3588 DSI 走 combo dcphy；overlay 需确认 phy 引用随 `&dsi1` 自动带起，否则补 phy 节点 status。
- **i2c6 复用冲突** → 已确认 i2c6 现挂 RTC@0x51，与 sec_ts@0x48 无地址冲突，overlay 仅追加节点不改总线。
- **按需编译的判定复杂度** → 用「board opt-in 显式声明启用子集」降复杂度，避免从 overlay 反解析驱动引用。

## Open Questions

- sec_ts 是否需要在 overlay 之外额外的 modules-load.d 自动加载配置？（OOT 模块默认装入 updates/，depmod 后是否随 DT 节点自动 probe 待 spike 验证。）
- rock5b BSP 内核 panel-simple-dsi / pwm-backlight / pwm2 是否均已内建，待构建期确认后决定是否补 defconfig fragment。
