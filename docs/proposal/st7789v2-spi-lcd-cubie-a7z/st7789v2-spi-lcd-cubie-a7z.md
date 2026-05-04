# Cubie A7Z 外接 ST7789V2 SPI LCD 方案

## 概述

为 Radxa Cubie A7Z (Allwinner A733) 外接一块 ST7789V2 240×280 SPI LCD 屏幕。

**当前状态**：走 **drm/tiny `panel-mipi-dbi-spi`**（mainline v5.18 backport 到 linux-a733 5.15.147，见 change `st7789v2-tinydrm-cutover`），LCD 暴露为 `/dev/dri/card*`，init 序列由构建期生成的 `/lib/firmware/panel-mipi-dbi-spi.bin` 加载。LCD 不再充当系统主控制台。

历史阶段（按时间顺序）：
1. **Phase 0**（已停用）：SPI1 + 用户态 spidev + libgpiod (软 CS)，dashboard PoC
2. **Phase 1**（已下线）：fbtft (`fb_st7789v`) + fbcon + `console=tty1`，LCD 当主控台
3. **Phase 2**（**当前**）：drm/tiny `panel-mipi-dbi-spi`，纯 DRM 设备

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

用户态 spidev 阶段（Phase 0，PoC 历史）：

- ✅ 7 色横向彩条显示（红 / 绿 / 蓝 / 黄 / 青 / 紫 / 白）
- ✅ Apple "博物馆画廊"风 dashboard 实时刷新（hero 圆环 + 二分指标，单一 Action Blue accent）
- ✅ SpaceX "Falcon HUD"风 dashboard 实时刷新（黑底 + Spectral White 单色 + 6 区块 + 同屏 30+ 数据维度）

fbtft 内核驱动阶段（Phase 1，已下线）：

- ✅ ST7789V 通过 fbtft 注册为 `/dev/fb0` (`fb_st7789v 240x280 16bpp` @ SPI 40 MHz)
- ✅ fbcon attached（vtcon1 master frame buffer device），`getty@tty1` 在 LCD 上启动 login
- ✅ Terminus 6×12 字体应用，密度达到 240/6=40 列 × 280/12=23 行
- ✅ `console=tty1` cmdline 让内核 boot dmesg 与 systemd 启动消息也输出到 LCD（与串口 ttyAS0 并存）
- ✅ 框架侧 `boot.board_overlays` 三源机制 + cubie-a7z config 改动通过 48 个 overlay 单元/集成测试（含 16 个新 case）

drm/tiny `panel-mipi-dbi-spi` 阶段（Phase 2，**当前**）：

- ✅ 内核 backport patch 干净 apply 到 linux-a733 5.15.147（`git apply --check` 通过）
- ✅ Python firmware 编码器 12 个单元测试覆盖（header / 多参命令 / delay / 错误路径）
- ✅ `RootfsBuilder._install_panel_firmware` 4 个集成单测覆盖（编码落地 / 缺源报错 / no-op / 子目录 dest）
- ⏳ 在板冒烟（dmesg probe / `/dev/dri/card*` / modetest 显图）—— 待 `flange flash` + 上电验证

## 演进路径

### 路径 A（**当前主路径**）：drm/tiny `panel-mipi-dbi-spi` → `/dev/dri/card*`

cubie-a7z 现行实现。change `st7789v2-tinydrm-cutover` 把 mainline v5.18 的通用 SPI MIPI DBI panel driver backport 到 linux-a733（5.15.147），LCD 暴露为标准 DRM 设备，可被 modetest / kmscube / weston / 用户态 DRM 客户端直接驱动。

**内核 backport**：`components/platform/allwinnera733/patches/kernel/01-tinydrm-panel-mipi-dbi.patch`
- 取自 mainline v5.18 commit `48b1f5440f8c`（在 tspi-rk3566 6.1 BSP 中能直接复用源码作蓝本）
- 5.15 适配点：`drm_gem_dma_helper.h` → `drm_gem_cma_helper.h`、`DEFINE_DRM_GEM_DMA_FOPS` → `..._CMA_FOPS`、`DRM_GEM_DMA_DRIVER_OPS_VMAP` → `..._CMA_VMAP`、移除 `.mode_valid` 字段（5.15 未导出）、`of_get_drm_panel_display_mode` → `of_get_drm_display_mode`、`spi_driver.remove` 返 int
- 启用：`CONFIG_DRM_PANEL_MIPI_DBI=m` 通过 a733 平台 defconfig fragment `panel_mipi_dbi.config` 注入

**Init 序列固件化**：`components/board/radxa-cubie-a7z/firmware/panel/st7789v2-240x280.txt`
- 可读文本源（`command 0xNN [0xPP ...]` / `delay <ms>`）
- 构建期由 `builder/firmware_panel.py` 编码为 mainline `panel.bin` 二进制（16 字节 magic header + 命令条目 + delay NOP）
- 落 rootfs `/lib/firmware/panel-mipi-dbi-spi.bin`（driver 用 `<compatible[0]>.bin` 派生，**不**读 `firmware-name` DT 属性）

**DTS overlay**（同名文件就地覆盖）：
- `compatible = "panel-mipi-dbi-spi"`
- 接线 cs/dc/reset 不变（PB3 软 CS、PB5 DC、PB6 RES）
- `panel-timing.hback-porch = <0>` / `vback-porch = <20>` 表达 280 行圆角模块的 (0, 20) GRAM 偏移——`drm_mipi_dbi.c::mipi_dbi_set_window_address` 每帧自动用 `top_offset/left_offset` 写 CASET/RASET
- `write-only` 标记（DBI 单向写，无 MISO）

**板级 config**（`components/board/radxa-cubie-a7z/config.py`）：

```python
"rootfs": {
    "panel_firmware": [
        {"src": "firmware/panel/st7789v2-240x280.txt",
         "dest": "panel-mipi-dbi-spi.bin"},
    ],
    # console=tty1 / kbd / console-setup / fonts-terminus 全部移除
},
```

**框架能力新增**：
- `RootfsBuilder._install_panel_firmware`（`builder/rootfs.py`）：通用 panel firmware 编译落地 hook，所有平台 rootfs 子类调用
- `builder/firmware_panel.py`：mainline `panel.bin` 二进制格式编码器 + 单元测试覆盖

> **代价**：LCD 不再充当系统主控制台。开机不再在 LCD 上看到 dmesg/systemd 启动消息/login，必须通过 DRM 客户端（modetest / kmscube / 用户态应用）才能渲染。串口 `ttyAS0` 仍是主控台，调试不受影响。

### 路径 B（已下线）：fbtft + fbcon → `/dev/fb0`

历史实现（Phase 1，已被路径 A 替换）。原方案借 `fb_st7789v` 让 LCD 当系统主控台，问题：

1. fbtft 框架老旧、上游已停止接受新驱动
2. 不与 mesa/wayland/kmscube 等现代 GUI 栈兼容
3. 一屏一驱动的耦合形态——换屏要写新内核驱动

git 历史保留：`git log -- components/board/radxa-cubie-a7z/dtso/sun60iw2p1-spi1-st7789v-display.dtso` 可见迁移 commit。

### 路径 C：用户态 dashboard（**待激活**）

dashboard 包装为 board-level Python 包：字体 / blit / 图像加载 / 帧率管理，适合"仪表盘 / 自定义 UI"型场景。

> 路径 A 落地后 LCD 已是 DRM 设备，dashboard 可基于 `pydrm` / `libdrm` / `drm_fb` mmap `/dev/dri/card*` 重构（不再走 `/dev/spidev1.0` 直 blit）。Phase 0 spidev 版本作为 PoC 历史保留，复活时机视具体场景。

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
