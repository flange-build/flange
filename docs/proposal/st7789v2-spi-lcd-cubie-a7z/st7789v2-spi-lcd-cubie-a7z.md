# Cubie A7Z 外接 ST7789V2 SPI LCD 方案

## 概述

为 Radxa Cubie A7Z (Allwinner A733) 外接一块 ST7789V2 240×280 SPI LCD 屏幕。

**当前状态**：已通过 **SPI1 + 用户态 spidev + libgpiod (软 CS)** 点亮，7 色彩条显示验证通过（kernel 5.15.147+，ubuntu-base，2026-05-03）。

后续可视场景演进到 fbtft（出 `/dev/fb1`）或 drm/tiny mipi-dbi（出 `/dev/dri/card1`），见末节"演进路径"。

## 硬件信息

| 项目 | 值 |
|---|---|
| 设备 | Radxa Cubie A7Z |
| SoC | Allwinner A733 (sun60iw2p1) |
| 屏幕 | ST7789V2 240×280 SPI LCD |
| 屏幕 Pin | GND, VCC, SCL, SDA, RES, DC, CS, BLK |

## 接线表（实际验证）

| ST7789V2 Pin | 信号 | 40-Pin Header | SoC Ball | gpiochip0 line | pinmux 状态 |
| --- | --- | --- | --- | --- | --- |
| GND | 地 | PIN_6 (任一 GND) | — | — | — |
| VCC | 电源 (3.3V) | PIN_1 | — | — | — |
| SCL | SPI Clock | PIN_23 | PD12 | — | spi1 (内核占用) |
| SDA | SPI MOSI | PIN_19 | PD11 | — | spi1 (内核占用) |
| CS  | Chip Select | PIN_31 | PB3 | 35 | GPIO（软件翻转） |
| DC  | Data/Command | PIN_12 | PB5 | 37 | GPIO |
| RES | Reset | PIN_35 | PB6 | 38 | GPIO |
| BLK | 背光 | PIN_36 | PB4 | 36 | GPIO（可选） |

> **背光可选**：BLK 接 PIN_36 (PB4) 可软件控制开关；接 PIN_1 (3.3V) 则常亮。

> **gpiochip0 line 编号**：sunxi pinctrl 采用 `port_letter * 32 + pin` 编号（PB=1，PD=3），故 PB3=35，PB4=36，PB5=37，PB6=38。已被运行时 pinmux-pins 输出 `pin 106 (PD10)` 验证一致（3×32+10=106）。

## 控制器选型

Cubie A7Z 共有 SPI0-SPI3 四个控制器：

| 控制器 | 引脚组 | 40-Pin 映射 | 当前可用性 |
| --- | --- | --- | --- |
| SPI0 | PC bank | 否（eMMC 占用） | 不可用 |
| **SPI1** | **PD10-13** | **是（PIN_24=CS / PIN_19=MOSI / PIN_23=SCLK / PIN_21=MISO）** | **当前使用** |
| SPI2 | PB0-3 | 是（PIN_7=SCLK / PIN_11=MOSI / PIN_29=MISO / PIN_31=CS0） | 备选，需禁用 i2s0 + uart2 |
| SPI3 | 无 40-Pin 映射 | 否 | 不可用 |

### 为什么是 SPI1

- `components/board/radxa-cubie-a7z/config.py` 已把 `sun60iw2p1-spi1-spidev.dtbo` 列入 `default_overlays`，开机即出 `/dev/spidev1.0`，**零额外 overlay**。
- 不与板载 i2s0 音频冲突。
- 单向写场景下无需 MISO，软件 CS 性能足够（已实测 40 MHz）。

### PB3 为何走软 CS

PB3 的硬件 SPI 复用是 **SPI2_CS0 (func 4)**，不能给 SPI1 做硬件片选。SPI1 的硬件 CS0 落在 PD10（PIN_24）—— 当前由 spidev1.0 节点占用，让用户空间通过 `/dev/spidev1.0` 触发。

实测做法：**直接把 PB3 当作 GPIO 软件翻转 CS**，并让 spidev1.0 的硬件 CS（PD10）保持悬空（不接到 LCD 模块）—— ST7789 不会响应它，不影响功能。这是和 radxa-overlays 项目里多个 LCD overlay 一致的"软 CS"思路。

## 当前实现：用户态 spidev + libgpiod

### 运行时依赖

板上需安装（已通过 `apt-get install -y` 完成）：

| 包 | 版本（Ubuntu 24.04） | 用途 |
| --- | --- | --- |
| `python3-spidev` | 3.6 | `/dev/spidev1.0` Python 绑定（rootfs 默认已带） |
| `gpiod` + `python3-libgpiod` | 1.6.3 | gpiochip chardev 用户态 API |
| `python3-pil` | 10.2 | RGB565 帧缓冲编码 |

> rootfs 长期方案：把上述包加入 `components/board/radxa-cubie-a7z/config.py` 的 `rootfs.packages`，避免每次 apt 安装。

### 初始化序列

ST7789V2 标准启动序列（在脚本中实现）：

```
SLPOUT (0x11)              ; 退出睡眠 + 等 120 ms
MADCTL (0x36) = 0x00       ; 默认 portrait
COLMOD (0x3A) = 0x55       ; RGB565
PORCTRL (0xB2) = 0C 0C 00 33 33
GCTRL  (0xB7) = 35
VCOMS  (0xBB) = 19
LCMCTRL(0xC0) = 2C
VDVVRHEN(0xC2)= 01
VRHS   (0xC3) = 12
VDVS   (0xC4) = 20
FRCTRL2(0xC6) = 0F         ; 60 Hz
PWCTRL1(0xD0) = A4 A1
PVGAMCTRL(0xE0) = D0 04 0D 11 13 2B 3F 54 4C 18 0D 0B 1F 23
NVGAMCTRL(0xE1) = D0 04 0C 11 13 2C 3F 44 51 2F 1F 1F 20 23
INVON  (0x21)              ; ST7789 IPS 面板必需
DISPON (0x29)
RAMWR  (0x2C) <pixel data>
```

帧缓冲偏移：240×280 圆角模块默认 `(x=0, y=20)`（GRAM 上 280 行从 y=20 开始），方屏模块用 `(0, 0)`。

### 脚本入口

驱屏脚本（开发时位于 `/tmp/lcd_st7789/st7789.py`，板上推送至 `/root/st7789.py`）：

```bash
python3 st7789.py --mode bars              # 7 色横向彩条（已验证）
python3 st7789.py --mode red               # 纯色
python3 st7789.py --hz 24000000            # 降速排查 SPI 时序
python3 st7789.py --xoff 0 --yoff 0        # 方屏模块偏移
python3 st7789.py --xoff 0 --yoff 20       # 圆角模块偏移（默认）
```

> 脚本固化进仓库的位置待定 —— 视演进路径选择（路径 C 用户态库会把它包成 board-level Python 模块）。

### 已验证

用户态 spidev 阶段（Phase 0，已被 Phase 1 取代）：

- ✅ 7 色横向彩条显示（红 / 绿 / 蓝 / 黄 / 青 / 紫 / 白）
- ✅ Apple "博物馆画廊"风 dashboard 实时刷新（hero 圆环 + 二分指标，单一 Action Blue accent）
- ✅ SpaceX "Falcon HUD"风 dashboard 实时刷新（黑底 + Spectral White 单色 + 6 区块 + 同屏 30+ 数据维度）

fbtft 内核驱动阶段（Phase 1，**当前主路径**）：

- ✅ ST7789V 通过 fbtft 注册为 `/dev/fb0` (`fb_st7789v 240x280 16bpp` @ SPI 40 MHz)
- ✅ fbcon attached（vtcon1 master frame buffer device），`getty@tty1` 在 LCD 上启动 login
- ✅ Terminus 6×12 字体应用，密度达到 240/6=40 列 × 280/12=23 行
- ✅ `console=tty1` cmdline 让内核 boot dmesg 与 systemd 启动消息也输出到 LCD（与串口 ttyAS0 并存）
- ✅ 框架侧 `boot.board_overlays` 三源机制 + cubie-a7z config 改动通过 48 个 overlay 单元/集成测试（含 16 个新 case）

入仓固化（Phase 2，**当前主路径**）：

- ✅ 板私有 overlay 落点：`components/board/radxa-cubie-a7z/overlays/sun60iw2p1-spi1-st7789v-display.dtso`
- ✅ console-setup file overlay：`components/board/radxa-cubie-a7z/overlay/etc/default/console-setup`
- ✅ fb_st7789v 兜底 modprobe：`components/board/radxa-cubie-a7z/overlay/etc/modules-load.d/st7789v.conf`
- ✅ `boot.kernel_args = "console=tty1"` + `rootfs.packages = [kbd, console-setup, fonts-terminus]`

## 演进路径

### 路径 A（**已实施**）：fbtft 内核驱动 + fbcon 终端 → `/dev/fb0`

cubie-a7z 当前主路径。LCD 作为系统主显示，开机即看到内核 dmesg 滚动 → systemd 启动消息 → login 提示，全程 Terminus 6×12 小字（240×280 屏密度上限：40 列 × 23 行）。

**落地的板私有 overlay**（`components/board/radxa-cubie-a7z/overlays/sun60iw2p1-spi1-st7789v-display.dtso`）：

- 释放 SPI1 上的 spidev1.0，在 `&spi1` 下挂 `compatible = "sitronix,st7789v"` 节点
- `cs-gpios = <&pio 1 3 1>`（PB3 软 CS，与 dashboard 阶段同接线，**完全不改板线**）
- `dc-gpios = <&pio 1 5 0>`（PB5）、`reset-gpios = <&pio 1 6 1>`（PB6）
- `sunxi,spi-cs-mode = <1>`（软件 CS 模式）

**框架扩展**：原 device-tree-overlay 组件只支持两源（in-tree + vendor 仓库）。这个板级私有 overlay 既不属于上游 vendor 仓库，又不便落入内核 in-tree —— 因此在 `builder/dtb_overlay.py` 新增第三类 overlay 源 `boot.board_overlays`，源文件位于 `components/board/<board>/overlays/`，复用 vendor overlays 同一 cpp+dtc 编译流水线。三源（`dtb_overlays` / `vendor_overlays` / `board_overlays`）在 boot.img 同一 `/dtbs/<vendor>/overlay/` 目录平铺，basename 全局唯一，撞名时构建期立即报错。

**cubie-a7z 板级配置同步改动**（`components/board/radxa-cubie-a7z/config.py`）：

```python
"boot": {
    "vendor_overlays": A733_VENDOR_OVERLAYS,
    "board_overlays": ["sun60iw2p1-spi1-st7789v-display.dtbo"],
    "default_overlays": ["sun60iw2p1-spi1-st7789v-display.dtbo"],  # 原 spidev1
    "kernel_args": "console=tty1",                                  # 新增
},
"rootfs": {
    "packages": ["kbd", "console-setup", "fonts-terminus"],         # 新增
    ...
},
```

**板级 rootfs file overlay**：
- `overlay/etc/default/console-setup` —— `FONTSIZE="6x12"` Terminus
- `overlay/etc/modules-load.d/st7789v.conf` —— `fb_st7789v` 兜底 modprobe

> **fb 编号注**：dmesg 显示 `graphics fb0` 因为当前内核启动时 sunxi-drm 没启用 fbdev emulation（HDMI 未接），fbtft 抢到了 fb 编号 0；如未来 sunxi-drm 也注册 fb，fbtft 会顺延到 fb1。任何编号下 fbcon 都能正常 attach。

### 路径 B：drm/tiny mipi-dbi → `/dev/dri/card1`（**不可行，记录**）

板上 5.15 内核虽然 `CONFIG_DRM_FBDEV_EMULATION=y`，但 drm/tiny 目录里**只有 `ili9486.ko`** 一个驱动，没有 `panel-mipi-dbi-spi.ko` 也没有 ST7789 的 drm 通用驱动。要走 drm 路径必须重编内核加上对应模块，工作量远大于路径 A，且收益不显著（fbcon 在 fbtft 上一样可用）。**已搁置**，待未来内核升级或更换 BSP 再评估。

### 路径 C：用户态 dashboard（**当前不可用，PoC 历史保留**）

dashboard 包装为 board-level Python 包：字体 / blit / 图像加载 / 帧率管理，适合"仪表盘 / 自定义 UI"型场景。

> 路径 A 实施后，`/dev/spidev1.0` 已被 fbtft 内核驱动占用，dashboard 需改写 SPI blit 后端为 `mmap /dev/fb0` 才能继续运行；与 fbcon 终端共享同一物理屏幕需要应用层做让出/接管协调（如类似 Linux console 的 `KDSETMODE`）。**当前 dashboard 处于不可用状态，作为 PoC 历史保留**，是否复活看是否有具体应用场景。

## 应用层 PoC：系统遥测 dashboard

为验证用户态显示链路与设计可塑性，已实现两套**同硬件、不同设计语言**的 dashboard，均在板上 1 Hz 实时刷新通过。这是"演进路径 C（用户态库）"的具体实例 —— 证明这块 240×280 LCD 在保持同一渲染管线的前提下，能从极简产品展示翻转到航天工程仪表盘。

### 两套视觉语言

| 风格 | 设计来源 | 美学要点 | 字体 |
| --- | --- | --- | --- |
| **Apple "博物馆画廊"** | [DESIGN-apple.md](../design/DESIGN-apple.md) | 黑底克制 / 单一 Action Blue (#0066cc) accent / hero 圆环 + 二分支撑指标 / negative tracking | InterDisplay-SemiBold + Inter-Medium |
| **SpaceX "Falcon HUD"** | [DESIGN-spacex.md](../design/DESIGN-spacex.md) | 纯黑 / Spectral White (#f0f0fa) 单色 / 全大写 + 正字距 / 6 区块 mission-briefing 编号 / 同屏 30+ 维度 | DejaVuSansMono-Bold（D-DIN 替代品） |

### 数据采集

全部从内核虚拟文件系统读取，无第三方依赖：

| 源 | 维度 |
| --- | --- |
| `/proc/stat` 的 `cpu` / `cpu0..cpu7` | 总负载 + 8 核 per-core 负载（4×Cortex-A55 LITTLE + 4×Cortex-A78 big） |
| `/proc/meminfo` | `MemTotal` / `MemAvailable`，算 used / total / pct |
| `/sys/class/thermal/thermal_zone*/{type,temp}` | 6 个温度域：CPU LITTLE (CPL) / CPU big (CPB) / GPU / NPU / DDR / 外壳 (SKN) |
| `/proc/loadavg` | 1 m / 5 m / 15 m 平均负载 |
| `/proc/net/dev` | 全网卡 RX / TX 字节累计，按 dt 算实时速率 |
| `/proc/uptime` | T+ mission-clock 计时器 |

### 渲染管线

```
PIL 内存画布 (480×560 = 2× supersample)
   │
   ├─ ImageDraw 绘 bar / arc / text / sparkline
   │
   ▼
LANCZOS 下采样 → 240×280 RGB
   │
   ▼
numpy 向量化转换 → RGB565 big-endian bytes
   │
   ▼
spidev1.0 writebytes2 → ST7789V2 RAMWR
```

2× supersample + LANCZOS 是嵌入式小屏抗锯齿的标准做法 —— 弧线、字距、细 hairline 在 240 px 上能保持清晰。numpy RGB565 转换让全帧编码在毫秒级，瓶颈在 SPI 带宽（240×280×2 = 131 KB / 帧 @ 40 MHz ≈ 27 ms 理论下限）。

### 脚本组织

| 文件 | 职责 |
| --- | --- |
| `st7789.py` | 驱屏底层：reset / init seq / `set_window` / `blit_rgb565`，附 `--mode bars/red/.../white` 自检 |
| `sysinfo.py` | 当前默认：SpaceX HUD 高密度遥测（顶状态栏 + 4 工程区块 + 底部双行遥测 + heartbeat tick） |
| `sysinfo_apple.py` | Apple 风 dashboard 备份（hero 圆环 + 二分指标 + 宽字距 caption） |

入口示例：

```bash
python3 sysinfo.py                # SpaceX HUD 实时（1 Hz）
python3 sysinfo.py --once         # 单帧
python3 sysinfo.py --save out.png # 离线预览（不刷 LCD）
python3 sysinfo_apple.py          # Apple 风
```

### 待落入仓库

脚本目前仍在开发位置（板上 `/root/`，宿主 `/tmp/lcd_st7789/`），尚未固化进 `components/`。建议落点（与"演进路径 C"一致）：

```
components/board/radxa-cubie-a7z/app/lcd/
├── st7789.py             # 驱屏库
├── sysinfo.py            # 默认 dashboard（SpaceX HUD）
└── sysinfo_apple.py      # 备选 dashboard（Apple 风）
```

并在 `rootfs.packages` 增列：

```
python3-spidev
python3-libgpiod
python3-pil
python3-numpy
fonts-inter
fonts-dejavu-core
```

需要决定（待用户输入）：
- 当前所有脚本一并入仓库，还是只保留一份"主"风格？
- 入仓时是否同步开机自启（systemd unit）？

## 备选方案：SPI2 + 硬件 CS

如果未来出于以下原因需要切换到 SPI2：
- 想用真正的硬件 CS（PB3 = SPI2_CS0），减轻 CPU 软翻片选开销
- SPI1 被其他用途占用

参见原始 SPI2 设计草案（详见 git 历史），需要一并处理：
- 牺牲板载 i2s0 音频（释放 PB4/5/6）
- 在板级 DTS 中把 uart2 标 `disabled`（释放 PB0-3）

接线会变为：SCL=PIN_7 (PB0)、SDA=PIN_11 (PB1)、CS=PIN_31 (PB3)、DC/RES/BLK 不变。

## 参考来源

- [radxa-pkg/radxa-overlays](https://github.com/radxa-pkg/radxa-overlays) — overlay 命名与软 CS 模式参考
- Allwinner A733 BSP pinctrl 驱动 — PB / PD bank SPI function 4 映射
- Cubie A7Z 板级 DTS — `sun60i-a733-cubie-a7z.dts`
- ST7789V2 Datasheet — Sitronix
- flange 仓库：
  - `components/board/radxa-cubie-a7z/config.py` —— 默认 overlay 与 vendor overlay 配置
  - `builder/overlays.py` —— vendor overlay 编译流水线
  - `openspec/specs/extlinux-dtb-overlays/spec.md` —— overlay 启用机制
