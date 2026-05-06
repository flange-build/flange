# Rock 5C Lite + Waveshare 1.3" LCD HAT (ST7789VM) — tinydrm 屏幕支持

- 状态：设计中（待用户复审 → writing-plans）
- 日期：2026-05-07
- 目标板：`radxa-rock5c-lite`（SoC = RK3582，复用 `rk3588s-rock-5c.dts`）
- 子板：Waveshare 1.3" LCD HAT for Raspberry Pi
  - 控制器：ST7789VM
  - 玻璃：1.3 寸 IPS、240(H) × 240(V)
  - 接口：4 线 SPI（DC/RST/CS/CLK/MOSI），背光低边 NPN 开关，3 个独立按键 + 5 向摇杆
- 关联先例：commit `4b9826d feat(cubie-a7z): ST7789V2 SPI LCD 从 fbtft 切到 drm/tiny panel-mipi-dbi-spi`

## 1. 目标 / 非目标

### 1.1 目标

把 Waveshare 1.3" LCD HAT 通过 RPi 40-pin 直接堆叠在 Rock 5C Lite 上，落地：

1. **LCD**：暴露为标准 DRM 设备 `/dev/dri/card*`，`modetest` / weston / Qt / fbcon 通用接口可直接出图，分辨率 240×240、默认横屏（MADCTL=0x70）。
2. **按键输入**：3 个 KEY + 5 向摇杆中实际可用的 7 个键全部以单一 `gpio-keys` input device 暴露；`evtest` 可观测标准 `KEY_F1/F2/F3/UP/DOWN/LEFT/ENTER` event。
3. **轻侵入**：不动平台 kernel patch；复用 cubie-a7z 已建好的 `firmware_panel.py` + `RootfsBuilder._install_panel_firmware` hook + DTBO 编译流水线。**唯一需要在 Python builder 中新增的代码**：`RockchipKernelBuilder` 中加 `_write_panel_mipi_dbi_fragment(src_dir)` 方法（约 5 行 `Path.write_text`），与现有 `_write_panthor_fragment` 同模式，与 `AllwinnerA733KernelBuilder._write_panel_mipi_dbi_override` 同语义——Rockchip kernel builder 的 fragment 体系是**代码生成而非文件加载**（参照 `_write_case_insensitive_fix`），因此无法仅靠"放一个 .config 文件"完成 fragment 注入。
4. **默认启用**：lunch 出来的整机镜像开机即可见屏，不需要运行时手工启用 overlay。

### 1.2 非目标（YAGNI）

- ❌ **背光 PWM 调光**：HAT 的 BL 信号在 Rock 5C Lite 上对应物理 pin 18（GPIO1_B0），该 pin 七个 mux function 中**无 PWM**。用户决策选项 C：完全不在 dts 中接管 BL，依赖原理图上 R2 = 10K 上拉的硬件默认行为（开机即亮）。
- ❌ **摇杆 RIGHT 键的软件 fallback**：HAT 上 Joy RIGHT (BCM26) 落到 Rock 5C Lite 物理 pin 37 = SARADC_VIN2，无 GPIO mux。用户决策选项 A：接受该键不工作，DT 注释明确说明物理原因，不走 SARADC 用户态轮询、不走 uinput 模拟。
- ❌ **平台层提级**：`CONFIG_DRM_PANEL_MIPI_DBI=m` defconfig fragment 留在 rk3582 SoC 层，不上提到 rockchip 顶层；rk3588 / rk3588s 真要用再加。
- ❌ **fbdev compatibility shim**：DRM 自带 fbcon emulation 已够用，不另装 `fbdev` 兼容层。
- ❌ **新增 capability / builder 代码 / 单元测试**：所有所需基建（panel firmware 编码器、rootfs hook、device-tree-overlay 编译流水线、kernel defconfig fragment 注入）已在仓库中存在。

## 2. 关键决策与原因

| 决策 | 选项 | 原因 |
|---|---|---|
| 内核驱动路线 | drm/tiny `panel-mipi-dbi-spi` | rkr5.1 内核（linux 6.1）mainline 自带（v5.18 入主线），无需 backport patch。`/dev/dri/card*` 是通用接口，与 fbtft 老式 fbdev 路线相比更利于 Wayland/Qt/SDL2 等现代 GUI 栈。cubie-a7z 已实测稳定。 |
| SPI 控制器 | SPI4 + `spi4m2_*` pinctrl | Rock 5C Lite 40-pin header pin 19/21/23/24 的 Function7 正好是 SPI4_M2 全套（MOSI/MISO/CLK/CS0），与 RPi SPI0 物理位完全对齐。可直接堆叠且**硬件 CS** 可用，不需 cubie-a7z 那种 GPIO 软 CS。 |
| RST 极性 | DT `GPIO_ACTIVE_HIGH` | 见 memory：mainline `mipi_dbi_hw_reset()` 假设 `1 = released, 0 = asserted` 物理直写语义，DT 必须按惯例声明 ACTIVE_HIGH，否则 gpiolib `active_low` 翻转会把 `set(1)` 反成物理 LOW，panel 永停 reset。即使 ST7789 物理 reset 为低有效也照此约定。 |
| 默认朝向 / init seq | Waveshare 官方 init + MADCTL=0x70 横屏 | 物理 PCB 摆正后摇杆/按键朝向与显示方向一致，最自然。Init seq 严格照抄 Waveshare 1.3" LCD HAT 官方 demo（`LCD_1in3.c`），仅 MADCTL = 0x70，COLMOD = 0x05；其余 PORCTRL/GCTRL/VCOM/gamma 与 cubie-a7z 那份 ST7789V2 相同（ST7789 家族 BSP 默认值）。 |
| 背光接管 | 不接管 | Pin 18 无 PWM mux，用户接受默认常亮。原理图 R2 = 10K 上拉到 3.3V，BLK 悬空时 Q1 base ≈ 3.3V，BL 默认导通。 |
| Joy RIGHT | 不接 | Pin 37 是 SARADC，无 GPIO mux。DT 注释明示。 |
| 按键 keycode 方案 | KEY_F1/F2/F3 + 方向键 + KEY_ENTER | 标准方向键被 Qt/SDL2/X11 直接识别为方向输入，K1-K3 用 KEY_F1-F3 做应用快捷键最通用。游戏手柄风格 BTN_0/1/2 此次不用。 |
| Overlay 默认启用 | 加入 `default_overlays` | lunch 出来的整机镜像默认即可见屏，与 OTG-peripheral overlay 同等待遇。 |
| Kernel fragment 落点 | rk3582 SoC 层 | 这块板独有需求，不上提到 rockchip 平台层；将来谁要再提。 |

## 3. 架构与变更清单

### 3.1 新增/修改文件

```
components/board/radxa-rock5c-lite/
├── config.py                                          [修改]
│   ├── boot.board_overlays    += "rk3588s-rock-5c-st7789vm-lcd-keys.dtbo"
│   ├── boot.default_overlays  += "rk3588s-rock-5c-st7789vm-lcd-keys.dtbo"
│   └── rootfs.panel_firmware  = [{ src: "firmware/panel/st7789vm-240x240.txt",
│                                    dest: "panel-mipi-dbi-spi.bin" }]
├── dtso/
│   └── rk3588s-rock-5c-st7789vm-lcd-keys.dtso         [新增]
└── firmware/panel/
    └── st7789vm-240x240.txt                           [新增]

components/platform/rockchip/rk3582/config.py          [修改]
└── kernel.defconfig += "panel_mipi_dbi.config"
    # fragment 文件本身**不放在** components/ 下，而是在构建期由
    # RockchipKernelBuilder._write_panel_mipi_dbi_fragment 写入
    # arch/$ARCH/configs/panel_mipi_dbi.config（与 case_insensitive_fix /
    # panthor 同机制；详见 §6.2）

builder/platforms/rockchip/kernel.py                   [修改]
├── 新增方法 _write_panel_mipi_dbi_fragment(src_dir)   # 写 5 行 fragment
└── 在 configure() 中追加调用                            # 与既有 _write_* 同位置

wiki/
├── boards/radxa-rock5c-lite.md                        [修改]
│   └── 新增小节 "1.3″ LCD HAT (ST7789VM) 显示与按键"
└── log.md                                             [修改]
    └── 增 sync 条目
```

### 3.2 不需要改动的部件

- `builder/firmware_panel.py` — cubie-a7z 那次新建，文本 → panel.bin 编码器，本次直接复用
- `builder/rootfs.py::RootfsBuilder._install_panel_firmware` — 通用 hook，本次直接复用
- `builder/platforms/rockchip/rootfs.py` — 已挂上 `_install_panel_firmware` hook，本次无需动
- `openspec/specs/panel-firmware-build/spec.md` — capability 已建，本次复用

## 4. DTS Overlay 详解

文件：`components/board/radxa-rock5c-lite/dtso/rk3588s-rock-5c-st7789vm-lcd-keys.dtso`

### 4.1 Pin / 资源占用

| HAT 信号 | RPi BCM | Rock 5C Lite 物理 pin | RK GPIO | 复用模式 |
|---|---|---|---|---|
| MOSI | 10 | 19 | GPIO1_A1 | SPI4_MOSI_M2 (Function7) |
| MISO | 9  | 21 | GPIO1_A0 | SPI4_MISO_M2 (Function7) |
| SCLK | 11 | 23 | GPIO1_A2 | SPI4_CLK_M2 (Function7) |
| CS0  | 8  | 24 | GPIO1_A3 | SPI4_CS0_M2 (Function7) — **硬件片选** |
| DC   | 25 | 22 | GPIO1_B5 | GPIO output |
| RST  | 27 | 13 | GPIO4_B2 | GPIO output (DT 声明 ACTIVE_HIGH) |
| BL   | 24 | 18 | GPIO1_B0 | **不接管**（默认硬件常亮） |
| K1   | 21 | 40 | GPIO4_B1 | GPIO input + pull_up |
| K2   | 20 | 38 | GPIO4_A5 | GPIO input + pull_up |
| K3   | 16 | 36 | GPIO4_A2 | GPIO input + pull_up |
| Joy UP    | 6  | 31 | GPIO1_B1 | GPIO input + pull_up |
| Joy DOWN  | 19 | 35 | GPIO4_A0 | GPIO input + pull_up |
| Joy LEFT  | 5  | 29 | GPIO1_B2 | GPIO input + pull_up |
| Joy PRESS | 13 | 33 | GPIO1_B4 | GPIO input + pull_up |
| ~~Joy RIGHT~~ | ~~26~~ | ~~37~~ | ~~SARADC_VIN2~~ | ❌ 物理上无 GPIO mux，不可用 |

### 4.2 Overlay 三段 fragment

**Fragment@0 — SPI4 controller + LCD panel 节点**

```dts
target = <&spi4>;
__overlay__ {
    status = "okay";
    pinctrl-names = "default";
    pinctrl-0 = <&spi4m2_cs0 &spi4m2_pins>;   /* 实施时查 rkr5.1 dtsi 确认 phandle 名 */
    #address-cells = <1>;
    #size-cells = <0>;
    /* 用硬件 CS（SPI4_CS0_M2），不写 cs-gpios */

    panel@0 {
        compatible = "panel-mipi-dbi-spi";
        reg = <0>;
        spi-max-frequency = <40000000>;
        dc-gpios    = <&gpio1 RK_PB5 GPIO_ACTIVE_HIGH>;
        reset-gpios = <&gpio4 RK_PB2 GPIO_ACTIVE_HIGH>;   /* 见 memory，必须 ACTIVE_HIGH */
        write-only;
        width-mm = <23>;
        height-mm = <23>;
        status = "okay";

        panel-timing {
            hactive = <240>;
            vactive = <240>;
            hback-porch = <0>;    /* 240×240 全屏，无 GRAM offset */
            vback-porch = <0>;
            hfront-porch = <0>;
            vfront-porch = <0>;
            hsync-len = <0>;
            vsync-len = <0>;
            clock-frequency = <3456000>;   /* binding 必填占位（driver 不用像素时钟）*/
        };
    };
};
```

**Fragment@1 — gpio-keys 节点**

```dts
target-path = "/";
__overlay__ {
    keys-st7789vm-hat {
        compatible = "gpio-keys";
        pinctrl-names = "default";
        pinctrl-0 = <&keys_st7789vm_pins>;
        autorepeat;

        key-k1     { label = "K1";        linux,code = <KEY_F1>;   gpios = <&gpio4 RK_PB1 GPIO_ACTIVE_LOW>; debounce-interval = <20>; };
        key-k2     { label = "K2";        linux,code = <KEY_F2>;   gpios = <&gpio4 RK_PA5 GPIO_ACTIVE_LOW>; debounce-interval = <20>; };
        key-k3     { label = "K3";        linux,code = <KEY_F3>;   gpios = <&gpio4 RK_PA2 GPIO_ACTIVE_LOW>; debounce-interval = <20>; };
        key-up     { label = "Joy UP";    linux,code = <KEY_UP>;   gpios = <&gpio1 RK_PB1 GPIO_ACTIVE_LOW>; debounce-interval = <20>; };
        key-down   { label = "Joy DOWN";  linux,code = <KEY_DOWN>; gpios = <&gpio4 RK_PA0 GPIO_ACTIVE_LOW>; debounce-interval = <20>; };
        key-left   { label = "Joy LEFT";  linux,code = <KEY_LEFT>; gpios = <&gpio1 RK_PB2 GPIO_ACTIVE_LOW>; debounce-interval = <20>; };
        key-press  { label = "Joy PRESS"; linux,code = <KEY_ENTER>;gpios = <&gpio1 RK_PB4 GPIO_ACTIVE_LOW>; debounce-interval = <20>; };

        /*
         * Joy RIGHT (BCM26) 物理上接到 Rock 5C Lite pin 37 = SARADC_VIN2，
         * 该 pin 七个 mux function 全无 GPIO，不能做数字输入。intentionally absent.
         */
    };
};
```

**Fragment@2 — pinctrl 内部上拉**

原理图上按键和摇杆均只接到 GND，无外部上拉电阻，必须显式 `pcfg_pull_up` 否则 floating 状态会乱触发。

```dts
target = <&pinctrl>;
__overlay__ {
    keys-st7789vm-hat {
        keys_st7789vm_pins: keys-st7789vm-pins {
            rockchip,pins =
                <4 RK_PB1 RK_FUNC_GPIO &pcfg_pull_up>,   /* K1 */
                <4 RK_PA5 RK_FUNC_GPIO &pcfg_pull_up>,   /* K2 */
                <4 RK_PA2 RK_FUNC_GPIO &pcfg_pull_up>,   /* K3 */
                <1 RK_PB1 RK_FUNC_GPIO &pcfg_pull_up>,   /* UP */
                <4 RK_PA0 RK_FUNC_GPIO &pcfg_pull_up>,   /* DOWN */
                <1 RK_PB2 RK_FUNC_GPIO &pcfg_pull_up>,   /* LEFT */
                <1 RK_PB4 RK_FUNC_GPIO &pcfg_pull_up>;   /* PRESS */
        };
    };
};
```

### 4.3 Metadata 头

参照 cubie-a7z 那份 dtso 习惯，文件头加 metadata block：

```dts
metadata {
    title = "Enable ST7789VM 240x240 SPI LCD HAT + 7 keys on Rock 5C Lite";
    compatible = "radxa,rock-5c-lite";
    category = "display";
    exclusive = "spi4",
                "GPIO1_A0", "GPIO1_A1", "GPIO1_A2", "GPIO1_A3",   /* SPI4_M2 */
                "GPIO1_B5", "GPIO4_B2",                            /* DC, RST */
                "GPIO4_B1", "GPIO4_A5", "GPIO4_A2",                /* K1 K2 K3 */
                "GPIO1_B1", "GPIO4_A0", "GPIO1_B2", "GPIO1_B4";    /* Joy U D L Press */
    description = "Bind Waveshare 1.3\" LCD HAT (ST7789VM) on SPI4_M2; 7 GPIO keys via gpio-keys. BL (pin 18 = GPIO1_B0) intentionally not managed (no PWM mux; default ON via 10K pull-up). Joy RIGHT (pin 37 = SARADC_VIN2) intentionally absent.";
};
```

## 5. Panel firmware 详解

文件：`components/board/radxa-rock5c-lite/firmware/panel/st7789vm-240x240.txt`

构建期由 `builder.firmware_panel` 编为 mainline 兼容的 panel.bin（15B magic header `MIPI DBI\x00...` + cmd 序列），落 rootfs `/lib/firmware/panel-mipi-dbi-spi.bin`。Driver 不读 DT `firmware-name` 属性，固定按 `<compatible[0]>.bin` 在 `/lib/firmware/` 下查找——dest 名称固定不可改。

```text
# ST7789VM 240x240 (Waveshare 1.3" LCD HAT) — 横屏 (MADCTL=0x70)
# 严格照抄 Waveshare 官方 demo LCD_1in3.c init seq；MADCTL 钉成 0x70 横屏。
# 不写 CASET/RASET：driver mipi_dbi_set_window_address 每帧自动按
# panel-timing.{hback,vback}-porch (此板均 = 0) 计算窗口起点。

# MADCTL — 横屏 (MX=1, MV=1)
command 0x36 0x70
# COLMOD — 0x05 (Waveshare demo 默认；与 0x55 等效，均为 16bpp 65K RGB)
command 0x3A 0x05

# PORCTRL
command 0xB2 0x0C 0x0C 0x00 0x33 0x33
# GCTRL
command 0xB7 0x35
# VCOMS
command 0xBB 0x19
# LCMCTRL
command 0xC0 0x2C
# VDV/VRH Enable (use register, not NVM)
command 0xC2 0x01
# VRHS
command 0xC3 0x12
# VDVS
command 0xC4 0x20
# FRCTRL2 — 60 Hz
command 0xC6 0x0F
# PWCTRL1
command 0xD0 0xA4 0xA1
# PVGAMCTRL
command 0xE0 0xD0 0x04 0x0D 0x11 0x13 0x2B 0x3F 0x54 0x4C 0x18 0x0D 0x0B 0x1F 0x23
# NVGAMCTRL
command 0xE1 0xD0 0x04 0x0C 0x11 0x13 0x2C 0x3F 0x44 0x51 0x2F 0x1F 0x1F 0x20 0x23

# Display Inversion ON — ST7789 IPS 必需
command 0x21
# Sleep Out
command 0x11
delay 120
# Display ON
command 0x29
```

## 6. 平台层改动

### 6.1 `components/platform/rockchip/rk3582/config.py`

`kernel.defconfig` 在末尾追加：

```python
"defconfig": [
    "rockchip_linux_defconfig",
    "case_insensitive_fix.config",
    "panel_mipi_dbi.config",   # 新增：CONFIG_DRM_PANEL_MIPI_DBI=m
],
```

### 6.2 Kernel config fragment（builder 代码生成）

`RockchipKernelBuilder` 现行做法是在 `configure()` 阶段把 fragment 文本**直接写入** `arch/$ARCH/configs/<name>.config`（参见现有 `_write_case_insensitive_fix` / `_write_panthor_fragment`），SoC 配置在 `kernel.defconfig` list 中按需引入。**rockchip 体系下没有"放 .config 文件到 components/ 就能注入"的路径**——必须加一个新方法。

新增 `RockchipKernelBuilder._write_panel_mipi_dbi_fragment(src_dir)`，与 a733 那边 `_write_panel_mipi_dbi_override` 完全同语义，仅文件名同 a733 复用：

```python
def _write_panel_mipi_dbi_fragment(self, src_dir: Path):
    """生成 config fragment 启用 mainline panel-mipi-dbi-spi 驱动（v5.18 in-tree，rkr5.1 6.1 自带，无需 backport）。"""
    fragment = src_dir / "arch" / self.ARCH / "configs" / "panel_mipi_dbi.config"
    fragment.write_text(
        "# panel-mipi-dbi-spi 通用 SPI DBI 屏 DRM 驱动\n"
        "# mainline v5.18 已 in-tree，rkr5.1 (linux 6.1) 自带，无需 backport\n"
        "CONFIG_DRM_PANEL_MIPI_DBI=m\n"
    )
    self._status("panel_mipi_dbi.config 生成")
```

并在 `configure()` 顶部追加一行调用，与既有 `_write_case_insensitive_fix(src_dir)` / `_write_panthor_fragment(src_dir, config)` 同位置：

```python
def configure(self, src_dir: Path, config: dict):
    self._write_case_insensitive_fix(src_dir)
    self._write_panthor_fragment(src_dir, config)
    self._write_panel_mipi_dbi_fragment(src_dir)   # 新增
    ...
```

> 与 a733 不同，**这里只需要 `CONFIG_DRM_PANEL_MIPI_DBI=m` 一行**：`CONFIG_DRM_KMS_HELPER` 在 rockchip_linux_defconfig 中已 =y，`CONFIG_DRM_MIPI_DBI` 由 Kconfig `select` 自动拉入，无需显式声明。

## 7. 板级 config 改动

`components/board/radxa-rock5c-lite/config.py` 在现有 BOARD dict 中：

```python
BOARD = {
    ...
    "boot": {
        "board_overlays": [
            "rk3588s-rock-5c-otg-peripheral.dtbo",
            "rk3588s-rock-5c-st7789vm-lcd-keys.dtbo",      # 新增
        ],
        "default_overlays": [
            "rk3588s-rock-5c-otg-peripheral.dtbo",
            "rk3588s-rock-5c-st7789vm-lcd-keys.dtbo",      # 新增 — 默认启用
        ],
    },
    "rootfs": {
        "+extra_firmware": [ ... 现有 AIC8800 不动 ... ],
        "panel_firmware": [                                # 新增
            {
                "src": "firmware/panel/st7789vm-240x240.txt",
                "dest": "panel-mipi-dbi-spi.bin",
            },
        ],
    },
    ...
}
```

## 8. 验证

### 8.1 在板验证（人手跑）

| 项 | 命令 | 期望 |
|---|---|---|
| panel driver probe | `dmesg \| grep panel-mipi-dbi-spi` | probe 成功，init seq 已执行 |
| DRM device 存在 | `ls /dev/dri/` | 至少 `card0` |
| Connector 状态 | `modetest -M panel-mipi-dbi -c` | SPI-1 connected, 240x240 |
| 出图 | `modetest -M panel-mipi-dbi -s <conn>:240x240` | 屏上彩色 SMPTE 测试条 |
| 输入设备 | `ls /dev/input/by-path/` | 见 `*-keys-st7789vm-hat-event` |
| 7 键 evtest | `evtest /dev/input/eventN` | K1-K3→F1-F3, Joy U/D/L/Press→UP/DOWN/LEFT/ENTER |
| Joy RIGHT | `evtest` 时按 Joy RIGHT | 无事件（intentional）|
| 背光默认常亮 | 目测 | 屏画面可见 |
| 既有功能不破 | `lsusb \| grep AIC` + adbd 烧录 | 不回归 |

### 8.2 构建机回归

```bash
pytest tests/builder/test_firmware_panel.py -v
pytest tests/builder/test_rootfs_panel_firmware.py -v
flange build radxa-rock5c-lite-userdebug
ls .build/radxa-rock5c-lite-userdebug/output/*.img
```

### 8.3 文档同步

- `wiki/boards/radxa-rock5c-lite.md`：当前**该文件尚不存在**（commit 725f10e 引入 board 时未建 wiki 页面）。本变更新建该文件，结构参照 `wiki/boards/radxa-cubie-a7z.md`，至少含：板基本信息、AIC8800D80 USB combo（已实现）、USB-C OTG peripheral overlay（已实现）、本次新增的 1.3″ LCD HAT（ST7789VM）显示与按键小节（含 SPI4_M2 pin 占用、7 键映射、Joy RIGHT 残缺与 BL 默认常亮的硬件原因）。
- `wiki/log.md` 加 sync 条目。

## 9. 已知风险与缓解

| 风险 | 缓解 |
|---|---|
| RST 极性踩坑（DT 声明 ACTIVE_LOW 导致 panel 永停 reset） | DT 强制 ACTIVE_HIGH；dtso 注释引 memory；本 spec §2 / §4.2 显式写出原因 |
| `panel-mipi-dbi-spi.bin` dest 名错（driver 派生自 compatible[0]，不读 firmware-name 属性） | dest 字面量在 spec §3.1 / §5 / §7 三处一致，并注释说明不可改 |
| BL pin 18 默认行为意外（某 driver 把 GPIO1_B0 拉低导致灭屏） | dts 完全不声明 GPIO1_B0，靠硬件 R2=10K 上拉默认导通；§8.1 加 grep 验证 |
| Pin 假设错位（用户提供的 Function 表与实际 dts 不一致） | 实施时第一步 `dmesg \| grep -E 'spi4\|panel-mipi'` 验证 SPI4 enabled、所有 IRQ 正常注册；按键 evtest 验证 |
| `spi4m2_*` pinctrl phandle 名 rkr5.1 与 mainline 不一致 | 实施时 `grep -r 'spi4m2' arch/arm64/boot/dts/rockchip/`，按实际名称填 |
| Kernel fragment 路径约定 | 用 `builder/paths.py` 定位；与 rockchip kernel builder 当前 fragment 加载逻辑一致；不在 spec 写死路径字面量 |

## 10. 不在范围内（重申）

见 §1.2。明确**不做**的事：BL PWM 调光、Joy RIGHT 软件 fallback、平台层提级、fbdev shim、新 capability。
