# Rock 5C Lite + Waveshare 1.3" LCD HAT (ST7789VM) — tinydrm 屏幕支持 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 Radxa ROCK 5C Lite 直接堆叠 Waveshare 1.3" LCD HAT (ST7789VM 240×240 + 3 keys + 5 向摇杆) 时，屏幕通过 mainline `panel-mipi-dbi-spi` DRM 驱动出图、7 个按键通过 `gpio-keys` 暴露为标准 input event。

**Architecture:** 复用 cubie-a7z 已建好的 drm/tiny `panel-mipi-dbi-spi` 流水线（`firmware_panel.py` 文本→panel.bin、`RootfsBuilder._install_panel_firmware` hook、DTBO 编译）。Rockchip 侧需新增一个 5 行的 `_write_panel_mipi_dbi_fragment` builder 方法，与现有 `_write_panthor_fragment` 同模式。SPI4_M2 与 RPi 40-pin 的 SPI0 物理位完美对齐，硬件 CS 可用。

**Tech Stack:** Linux 6.1 (rkr5.1 BSP) `drm/tiny/panel-mipi-dbi.c` (mainline v5.18 in-tree) · Rockchip RK3582 SoC · DTS overlay (cpp + dtc) · Python builder (pytest)

**Spec:** `docs/superpowers/specs/2026-05-07-rock5c-lite-st7789vm-tinydrm-design.md`

**关键约束（务必读）：**

1. **RST GPIO 极性**：DT 必须声明 `GPIO_ACTIVE_HIGH`，即使 ST7789 物理 reset 是低有效。理由：mainline `mipi_dbi_hw_reset()` 用 `gpiod_set_value(reset, 0/1)` 直接表达 release/assert 语义，DT 声明 ACTIVE_LOW 会触发 gpiolib 翻转，结果 `set(1)` 反成物理 LOW、panel 永停 reset。这条已有先例踩坑（cubie-a7z + memory），不要"修正"它。
2. **panel firmware 文件名固定**：driver 不读 DT `firmware-name` 属性，固定按 `<compatible[0]>.bin` 在 `/lib/firmware/` 下查找。`dest` 必须是 `panel-mipi-dbi-spi.bin`，不可改。
3. **背光（GPIO1_B0 / pin 18）完全不接管**：硬件 R2=10K 上拉到 3.3V，BLK 悬空时 Q1 ON、BL 默认常亮。dts 不要加 `gpio-backlight` 节点，不要给该 pin 任何 pinctrl 声明。
4. **Joy RIGHT (pin 37 = SARADC_VIN2) 物理上无 GPIO mux**：dts 注释明确说明，不接事件、不接 SARADC fallback。
5. **不要新建 `components/platform/.../patches/kernel/configs/`**：rockchip kernel builder 不从那里加载 fragment，必须走 builder 代码生成路径。

---

## File Structure

新增/修改文件清单（与 spec §3.1 同步）：

| 文件 | 动作 | 责任 |
|---|---|---|
| `builder/platforms/rockchip/kernel.py` | 修改 | 加 `_write_panel_mipi_dbi_fragment` 方法 + 在 `configure()` 调用 |
| `tests/builder/test_rockchip_kernel_panel_fragment.py` | 新增 | 单元测试 fragment 生成逻辑 |
| `components/platform/rockchip/rk3582/config.py` | 修改 | `kernel.defconfig` 追加 `panel_mipi_dbi.config` |
| `components/board/radxa-rock5c-lite/dtso/rk3588s-rock-5c-st7789vm-lcd-keys.dtso` | 新增 | SPI4_M2 + panel-mipi-dbi-spi + gpio-keys 一体 overlay |
| `components/board/radxa-rock5c-lite/firmware/panel/st7789vm-240x240.txt` | 新增 | Waveshare init seq + MADCTL=0x70 横屏 |
| `components/board/radxa-rock5c-lite/config.py` | 修改 | `boot.board_overlays` / `boot.default_overlays` / `rootfs.panel_firmware` |
| `wiki/boards/radxa-rock5c-lite.md` | 新增 | 板级 wiki 页面（首次创建） |
| `wiki/log.md` | 修改 | sync 条目 |

---

## 总体节奏

7 个任务，按依赖顺序执行：

1. **Task 1 — Builder 代码（rockchip kernel fragment 生成）**：基础设施，必须先做，纯 Python TDD
2. **Task 2 — 平台配置（rk3582 SoC 引入 fragment）**：依赖 Task 1
3. **Task 3 — Panel firmware 源文件**：独立，Waveshare init seq
4. **Task 4 — DTS overlay**：独立，但 Task 5 依赖它
5. **Task 5 — 板级 config 改动（连线 overlay + panel firmware）**：依赖 Task 3 + 4
6. **Task 6 — 在板验证（人手）**：依赖前 5 个任务完成 + 镜像构建
7. **Task 7 — Wiki 文档同步**：独立，可与 Task 6 并行

每个任务结尾有一次 commit。Commit message 风格沿用仓库习惯（`feat(rk3582/rock5c-lite): ...` / `fix(builder/...): ...`，正文中文，结尾 Co-Authored-By）。

---

## Task 1 — RockchipKernelBuilder 加 `_write_panel_mipi_dbi_fragment` 方法

**Goal:** 让 `RockchipKernelBuilder.configure()` 在 kernel 源码树写出 `arch/arm64/configs/panel_mipi_dbi.config` fragment（包含 `CONFIG_DRM_PANEL_MIPI_DBI=m`），与现有 `_write_panthor_fragment` / `_write_case_insensitive_fix` 同模式。

**Files:**
- Modify: `builder/platforms/rockchip/kernel.py` （在 `configure` 顶部加调用 + 类内加方法）
- Test: `tests/builder/test_rockchip_kernel_panel_fragment.py` （新建）

### Step 1.1 — 看现有同类测试有没有可参考的 pattern

- [ ] **看测试约定**

```bash
ls /Users/eki/Project/Embedded_Project/flange/tests/builder/ | grep -E 'rockchip|panthor|case_insensitive' || true
grep -rn "_write_panthor_fragment\|_write_case_insensitive_fix" /Users/eki/Project/Embedded_Project/flange/tests/ | head
```

预期：可能没有现成测试覆盖这两个方法，则我们的新测试就是这一类的首例，按通用 pytest + tmp_path 风格写即可。

### Step 1.2 — 写失败测试

- [ ] **创建测试文件 `tests/builder/test_rockchip_kernel_panel_fragment.py`**

```python
"""测试 RockchipKernelBuilder._write_panel_mipi_dbi_fragment 行为。

与 _write_panthor_fragment 不同：panel-mipi-dbi-spi driver 在 mainline v5.18
已 in-tree，rkr5.1 (linux 6.1) 自带，无需 backport patch、无需条件分支。
fragment 总是写入相同内容，由 SoC kernel.defconfig list 决定是否引入。
"""

from pathlib import Path

import pytest

from builder.platforms.rockchip.kernel import RockchipKernelBuilder


@pytest.fixture
def builder(monkeypatch):
    """构造一个 RockchipKernelBuilder 实例，并屏蔽其 _status 输出。

    KernelBuilder 基类的 __init__ 需要 source/docker 等依赖，但本测试
    只调用纯 Path I/O 的方法，所以走 object.__new__ 绕过构造函数。
    """
    b = RockchipKernelBuilder.__new__(RockchipKernelBuilder)
    monkeypatch.setattr(b, "_status", lambda *a, **kw: None, raising=False)
    return b


def test_writes_fragment_to_arch_configs(builder, tmp_path):
    src = tmp_path / "linux"
    (src / "arch" / "arm64" / "configs").mkdir(parents=True)

    builder._write_panel_mipi_dbi_fragment(src)

    fragment = src / "arch" / "arm64" / "configs" / "panel_mipi_dbi.config"
    assert fragment.is_file()


def test_fragment_enables_panel_mipi_dbi_module(builder, tmp_path):
    src = tmp_path / "linux"
    (src / "arch" / "arm64" / "configs").mkdir(parents=True)

    builder._write_panel_mipi_dbi_fragment(src)

    text = (src / "arch" / "arm64" / "configs" / "panel_mipi_dbi.config").read_text()
    assert "CONFIG_DRM_PANEL_MIPI_DBI=m" in text


def test_fragment_is_idempotent(builder, tmp_path):
    """重复调用应得到相同内容（不追加、不报错）。"""
    src = tmp_path / "linux"
    (src / "arch" / "arm64" / "configs").mkdir(parents=True)

    builder._write_panel_mipi_dbi_fragment(src)
    first = (src / "arch" / "arm64" / "configs" / "panel_mipi_dbi.config").read_text()

    builder._write_panel_mipi_dbi_fragment(src)
    second = (src / "arch" / "arm64" / "configs" / "panel_mipi_dbi.config").read_text()

    assert first == second


def test_configure_invokes_panel_mipi_dbi_fragment(builder, tmp_path, monkeypatch):
    """configure() 应在写其他 fragment 后也调用 panel mipi dbi fragment。

    通过监控 _write_panel_mipi_dbi_fragment 是否被调用一次来验证。
    """
    src = tmp_path / "linux"
    (src / "arch" / "arm64" / "configs").mkdir(parents=True)

    calls = []

    def fake_panel(self, src_dir):
        calls.append(src_dir)

    def fake_case(self, src_dir):
        pass

    def fake_panthor(self, src_dir, config):
        pass

    def fake_make(self, src_dir, targets, **kw):
        pass

    monkeypatch.setattr(RockchipKernelBuilder, "_write_panel_mipi_dbi_fragment", fake_panel)
    monkeypatch.setattr(RockchipKernelBuilder, "_write_case_insensitive_fix", fake_case)
    monkeypatch.setattr(RockchipKernelBuilder, "_write_panthor_fragment", fake_panthor)
    monkeypatch.setattr(RockchipKernelBuilder, "make", fake_make)

    builder.configure(src, {"kernel": {"defconfig": "rockchip_linux_defconfig"}})

    assert calls == [src], f"expected exactly one call to _write_panel_mipi_dbi_fragment with src={src}, got {calls}"
```

### Step 1.3 — 跑测试确认失败

- [ ] **跑测试**

```bash
cd /Users/eki/Project/Embedded_Project/flange && pytest tests/builder/test_rockchip_kernel_panel_fragment.py -v
```

预期：4 个测试全失败，原因 `AttributeError: 'RockchipKernelBuilder' object has no attribute '_write_panel_mipi_dbi_fragment'` 或 `AttributeError ... type ...`。

### Step 1.4 — 实现 `_write_panel_mipi_dbi_fragment` 方法

- [ ] **修改 `builder/platforms/rockchip/kernel.py`**

在 `_write_panthor_fragment` 方法**之后**追加新方法：

```python
    def _write_panel_mipi_dbi_fragment(self, src_dir: Path):
        """生成 config fragment 启用 mainline panel-mipi-dbi-spi 驱动。

        Mainline v5.18 已 in-tree（drivers/gpu/drm/tiny/panel-mipi-dbi.c，
        commit 48b1f5440f8c），rkr5.1 (linux 6.1) 自带，**无需 backport
        patch**——与 a733 (5.15) 那边的同名 fragment 是同语义但不同来源。

        该 fragment **总是写入**（不像 panthor 有 SoC 条件分支）；SoC 配置
        决定是否在 kernel.defconfig list 中引入。CONFIG_DRM_KMS_HELPER 在
        rockchip_linux_defconfig 中已 =y，CONFIG_DRM_MIPI_DBI 由 Kconfig
        select 自动拉入，无需在此显式声明。
        """
        fragment = src_dir / "arch" / self.ARCH / "configs" / "panel_mipi_dbi.config"
        fragment.write_text(
            "# panel-mipi-dbi-spi 通用 SPI DBI 屏 DRM 驱动\n"
            "# mainline v5.18 已 in-tree，rkr5.1 (linux 6.1) 自带，无需 backport\n"
            "CONFIG_DRM_PANEL_MIPI_DBI=m\n"
        )
        self._status("panel_mipi_dbi.config 生成")
```

并在 `configure` 方法体顶部、紧跟现有 `_write_panthor_fragment` 调用之后追加一行：

```python
    def configure(self, src_dir: Path, config: dict):
        """支持单 defconfig 字符串或多步 defconfig 合并 list。
        ...（保留现有 docstring）...
        """
        self._write_case_insensitive_fix(src_dir)
        self._write_panthor_fragment(src_dir, config)
        self._write_panel_mipi_dbi_fragment(src_dir)   # ← 新增
        defconfig = config["kernel"]["defconfig"]
        ...
```

> 同时把 `configure` docstring 中"两个 fragment 都始终生成" 那段话同步改成"三个 fragment 都始终生成"，并在示例 `["rockchip_linux_defconfig", "case_insensitive_fix.config", "rk3588_panthor.config"]` 后追加 `, "panel_mipi_dbi.config"`，保持文档与代码一致。

### Step 1.5 — 跑测试确认通过

- [ ] **再跑一遍**

```bash
cd /Users/eki/Project/Embedded_Project/flange && pytest tests/builder/test_rockchip_kernel_panel_fragment.py -v
```

预期：4/4 PASS。

### Step 1.6 — 跑 builder 全套测试，确保不破回归

- [ ] **全量回归**

```bash
cd /Users/eki/Project/Embedded_Project/flange && pytest tests/builder/ -v --timeout=60
```

预期：全部 PASS（重点确保 `test_firmware_panel.py` 和 `test_rootfs_panel_firmware.py` 仍通过，没碰到任何隐式依赖）。

### Step 1.7 — Commit

- [ ] **commit**

```bash
git -C /Users/eki/Project/Embedded_Project/flange add \
  builder/platforms/rockchip/kernel.py \
  tests/builder/test_rockchip_kernel_panel_fragment.py
git -C /Users/eki/Project/Embedded_Project/flange commit -m "$(cat <<'EOF'
feat(builder/rockchip): 加 panel_mipi_dbi.config fragment 生成

RockchipKernelBuilder 新增 _write_panel_mipi_dbi_fragment(src_dir)，
在 configure() 阶段把 CONFIG_DRM_PANEL_MIPI_DBI=m 写入
arch/arm64/configs/panel_mipi_dbi.config，与现有 _write_panthor_fragment
/ _write_case_insensitive_fix 同模式。

Mainline v5.18 panel-mipi-dbi-spi 驱动 (drivers/gpu/drm/tiny/panel-mipi-dbi.c,
commit 48b1f5440f8c) 已 in-tree，rkr5.1 (linux 6.1) 自带，无需 backport
patch——与 a733 (5.15) 那边的同名 fragment 是同语义但不同来源。

为后续 Rock 5C Lite 接 Waveshare 1.3" LCD HAT (ST7789VM SPI 屏) 做铺垫；
SoC 配置在 kernel.defconfig list 中按需引入即可激活。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2 — RK3582 SoC 配置：在 defconfig list 中引入 panel_mipi_dbi.config

**Goal:** `kernel.defconfig` 列表追加 `panel_mipi_dbi.config`，使 RK3582 内核构建时该 fragment 被合并进 `.config`。

**Files:**
- Modify: `components/platform/rockchip/rk3582/config.py:46-55`

### Step 2.1 — 修改 SoC 配置

- [ ] **编辑 `components/platform/rockchip/rk3582/config.py`**

定位 `kernel.defconfig` 列表，把：

```python
        "defconfig": [
            "rockchip_linux_defconfig",
            "case_insensitive_fix.config",
        ],
```

改为：

```python
        "defconfig": [
            "rockchip_linux_defconfig",
            "case_insensitive_fix.config",
            # 启用 mainline panel-mipi-dbi-spi 驱动 (CONFIG_DRM_PANEL_MIPI_DBI=m)，
            # 用于 Rock 5C Lite + Waveshare 1.3" LCD HAT (ST7789VM SPI 屏) 等
            # 板级 SPI display；fragment 由 RockchipKernelBuilder 在
            # configure() 阶段写到 arch/arm64/configs/panel_mipi_dbi.config。
            "panel_mipi_dbi.config",
        ],
```

### Step 2.2 — 验证 Python config 可被 import 解析

- [ ] **静态检查**

```bash
cd /Users/eki/Project/Embedded_Project/flange && python -c "
from components.platform.rockchip.rk3582.config import SOC
assert 'panel_mipi_dbi.config' in SOC['kernel']['defconfig'], SOC['kernel']['defconfig']
print('OK:', SOC['kernel']['defconfig'])
"
```

预期：打印 `OK: ['rockchip_linux_defconfig', 'case_insensitive_fix.config', 'panel_mipi_dbi.config']`。

### Step 2.3 — Commit

- [ ] **commit**

```bash
git -C /Users/eki/Project/Embedded_Project/flange add \
  components/platform/rockchip/rk3582/config.py
git -C /Users/eki/Project/Embedded_Project/flange commit -m "$(cat <<'EOF'
feat(rk3582): kernel defconfig 引入 panel_mipi_dbi.config fragment

在 RK3582 SoC 的 kernel.defconfig 合并列表追加 panel_mipi_dbi.config，
启用 CONFIG_DRM_PANEL_MIPI_DBI=m。

为下一步 Rock 5C Lite 板上接 Waveshare 1.3" LCD HAT (ST7789VM SPI 屏)
做铺垫——LCD 走 mainline drm/tiny panel-mipi-dbi-spi 通用驱动，
init seq 走 /lib/firmware/panel-mipi-dbi-spi.bin。

fragment 文件本身由 RockchipKernelBuilder._write_panel_mipi_dbi_fragment
在 configure() 阶段写入 arch/arm64/configs/，rockchip kernel builder
fragment 体系是代码生成而非文件加载。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3 — Panel firmware 源文件（Waveshare init seq + MADCTL=0x70 横屏）

**Goal:** 加 panel init seq 文本文件，构建期由 `builder.firmware_panel` 编为 mainline panel-mipi-dbi-spi 兼容的 panel.bin。

**Files:**
- Create: `components/board/radxa-rock5c-lite/firmware/panel/st7789vm-240x240.txt`

### Step 3.1 — 创建 firmware 源文件

- [ ] **新建 `components/board/radxa-rock5c-lite/firmware/panel/st7789vm-240x240.txt`**

```text
# ST7789VM 240x240 (Waveshare 1.3" LCD HAT) — 横屏 (MADCTL=0x70)
#
# 严格照抄 Waveshare 官方 demo LCD_1in3.c init seq，仅 MADCTL 钉成 0x70 横屏。
# 由 builder.firmware_panel 在构建期编为 mainline 兼容的 panel.bin（16B magic
# header + cmd 序列 + delay NOP），落 rootfs /lib/firmware/panel-mipi-dbi-spi.bin。
#
# dest 文件名固定不可改：driver 不读 DT firmware-name 属性，固定按
# <compatible[0]>.bin 在 /lib/firmware/ 下查找。
#
# 不写 CASET/RASET：driver mipi_dbi_set_window_address 每帧自动按
# panel-timing.{hback,vback}-porch (此板均 = 0) 计算窗口起点。

# MADCTL — 横屏 (MX=1, MV=1)；竖屏改 0x00
command 0x36 0x70
# COLMOD — 0x05 (Waveshare demo 默认；与 0x55 等效，均为 16bpp 65K RGB)
command 0x3A 0x05

# PORCTRL — Porch Setting
command 0xB2 0x0C 0x0C 0x00 0x33 0x33
# GCTRL — Gate Control = 0x35 (VGH=13.26V, VGL=-10.43V)
command 0xB7 0x35
# VCOMS — VCOM Setting = 0x19 (~0.725V)
command 0xBB 0x19
# LCMCTRL — LCM Control = 0x2C
command 0xC0 0x2C
# VDV/VRH Enable — 用 register 而非 NVM
command 0xC2 0x01
# VRHS — VAP/VAN Voltage = 0x12
command 0xC3 0x12
# VDVS — VDV = 0x20 (默认)
command 0xC4 0x20
# FRCTRL2 — Frame Rate Control = 0x0F (60 Hz)
command 0xC6 0x0F
# PWCTRL1 — Power Control 1
command 0xD0 0xA4 0xA1
# PVGAMCTRL — Positive Voltage Gamma Control
command 0xE0 0xD0 0x04 0x0D 0x11 0x13 0x2B 0x3F 0x54 0x4C 0x18 0x0D 0x0B 0x1F 0x23
# NVGAMCTRL — Negative Voltage Gamma Control
command 0xE1 0xD0 0x04 0x0C 0x11 0x13 0x2C 0x3F 0x44 0x51 0x2F 0x1F 0x1F 0x20 0x23

# Display Inversion ON — ST7789 IPS 必需，不开会反色
command 0x21
# Sleep Out — 退出睡眠（必须等 ≥120 ms 才能继续）
command 0x11
delay 120
# Display ON
command 0x29
```

### Step 3.2 — 验证文件可被 firmware_panel 解析为合法 panel.bin

- [ ] **跑解析器干跑（unit-style smoke）**

```bash
cd /Users/eki/Project/Embedded_Project/flange && python -c "
from builder.firmware_panel import compile_panel_firmware
from pathlib import Path
src = Path('components/board/radxa-rock5c-lite/firmware/panel/st7789vm-240x240.txt')
out = compile_panel_firmware(src)
assert out[:15] == b'MIPI DBI\x00\x00\x00\x00\x00\x00\x00', out[:16].hex()
print('OK: panel.bin size =', len(out), 'bytes, magic header valid')
"
```

> 上面的 import 路径假设是 `compile_panel_firmware`。如果实际函数名不同（例如 `encode_panel_firmware` / `compile_firmware`），先 `grep -E '^def ' builder/firmware_panel.py` 看一眼，按实际名字调即可。Magic header 字节序与长度按实际 mainline panel-mipi-dbi.c 的 `MIPI_DBI_FW_MAGIC` 字符串实现核对：先看 `builder/firmware_panel.py` 顶部常量名（cubie-a7z 那次有定义），按它的常量比对，不要硬编码。

预期：解析无异常，输出 panel.bin 字节数大致 ≥ 16(magic) + 命令字节数；magic header 与 builder 内常量一致。

### Step 3.3 — Commit

- [ ] **commit**

```bash
git -C /Users/eki/Project/Embedded_Project/flange add \
  components/board/radxa-rock5c-lite/firmware/panel/st7789vm-240x240.txt
git -C /Users/eki/Project/Embedded_Project/flange commit -m "$(cat <<'EOF'
feat(rock5c-lite): 加 ST7789VM 240x240 panel init seq (Waveshare 1.3" LCD HAT)

新增 components/board/radxa-rock5c-lite/firmware/panel/st7789vm-240x240.txt，
严格照抄 Waveshare 官方 demo LCD_1in3.c 的 init seq，MADCTL=0x70 横屏、
COLMOD=0x05 16bpp。其他 PORCTRL/GCTRL/VCOM/gamma 与 cubie-a7z 那份
ST7789V2 init 完全一致——ST7789 家族 BSP 默认值。

由 builder.firmware_panel 在构建期编为 mainline 兼容 panel.bin，
落 rootfs /lib/firmware/panel-mipi-dbi-spi.bin。下一步在 board config
里挂 rootfs.panel_firmware 把它接进 RootfsBuilder._install_panel_firmware
hook。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4 — DTS overlay (`rk3588s-rock-5c-st7789vm-lcd-keys.dtso`)

**Goal:** 一份 dtso 把 SPI4_M2 + panel-mipi-dbi-spi panel 节点 + 7 键 gpio-keys 节点全部声明出来。

**Files:**
- Create: `components/board/radxa-rock5c-lite/dtso/rk3588s-rock-5c-st7789vm-lcd-keys.dtso`

### Step 4.1 — 先在 kernel 源码树确认 spi4 / pinctrl phandle 名

> **注意：** 这一步只在你**有本地或远端 rkr5.1 内核源码**的前提下做。如果暂时没有，先按下面的"假设值"写 dtso，构建报错时再回来定位。

- [ ] **若有 kernel src，在 src 树查 spi4m2 mux phandle 名与 RK_PB/RK_PA 头**

```bash
# 假设 kernel src 在 .build/sources/kernel 下
grep -rn 'spi4m2\|spi4_m2' /Users/eki/Project/Embedded_Project/flange/.build/sources/kernel/arch/arm64/boot/dts/rockchip/ 2>&1 | head -10
grep -rn 'rk3588.*pinctrl\|spi4m2' /Users/eki/Project/Embedded_Project/flange/.build/sources/kernel/arch/arm64/boot/dts/rockchip/rk3588s.dtsi 2>&1 | head -10
```

预期 phandle 名（按 rkr5.1 BSP 习惯，2 个候选）：
- 候选 A：`spi4m2_cs0` + `spi4m2_pins`（拆分 CS 与数据线 pinctrl）
- 候选 B：单一 `spi4m2_xfer`（数据线集合）+ `spi4m2_cs0`

按实际 dtsi 中找到的 label 名为准。下面的 dtso 写候选 A，若实际是 B，把 `pinctrl-0 = <&spi4m2_cs0 &spi4m2_pins>;` 改成对应 phandle。

### Step 4.2 — 创建 dtso 文件

- [ ] **新建 `components/board/radxa-rock5c-lite/dtso/rk3588s-rock-5c-st7789vm-lcd-keys.dtso`**

```dts
// SPDX-License-Identifier: GPL-2.0
/*
 * Bind Waveshare 1.3" LCD HAT (ST7789VM, 240x240) on Rock 5C Lite via
 * RPi-compatible 40-pin GPIO header. Three subsystems:
 *
 *   1. SPI4 (Function7 mux on header pins 19/21/23/24, "SPI4_M2"):
 *      MOSI = pin 19 / GPIO1_A1
 *      MISO = pin 21 / GPIO1_A0
 *      CLK  = pin 23 / GPIO1_A2
 *      CS0  = pin 24 / GPIO1_A3   (hardware CS, no cs-gpios needed)
 *
 *   2. ST7789VM panel via mainline drm/tiny panel-mipi-dbi-spi (linux v5.18+,
 *      rkr5.1 6.1 in-tree). Init seq loaded from
 *      /lib/firmware/panel-mipi-dbi-spi.bin (driver derives filename from
 *      compatible[0]; firmware-name DT property is NOT consulted).
 *      DC  = pin 22 / GPIO1_B5
 *      RST = pin 13 / GPIO4_B2
 *
 *      RST GPIO MUST be declared GPIO_ACTIVE_HIGH (even though ST7789 reset
 *      is physically low-active): mipi_dbi_hw_reset() uses gpiod_set_value()
 *      with "1 = released, 0 = asserted" direct-write semantics. Declaring
 *      ACTIVE_LOW makes gpiolib invert the final set(1) into a physical LOW
 *      and the panel stalls in reset forever.
 *
 *   3. 7 GPIO buttons via gpio-keys:
 *      K1 = pin 40 / GPIO4_B1  → KEY_F1
 *      K2 = pin 38 / GPIO4_A5  → KEY_F2
 *      K3 = pin 36 / GPIO4_A2  → KEY_F3
 *      Joy UP    = pin 31 / GPIO1_B1 → KEY_UP
 *      Joy DOWN  = pin 35 / GPIO4_A0 → KEY_DOWN
 *      Joy LEFT  = pin 29 / GPIO1_B2 → KEY_LEFT
 *      Joy PRESS = pin 33 / GPIO1_B4 → KEY_ENTER
 *
 *      All keys are external-pulldown-via-button-to-GND; pinctrl declares
 *      pcfg_pull_up because the HAT has no external pull resistors.
 *
 *      Joy RIGHT (BCM26 → header pin 37) is intentionally absent: pin 37 on
 *      Rock 5C Lite is SARADC_VIN2, with no GPIO mux available — physically
 *      unusable as a digital input.
 *
 *   Backlight (BLK / pin 18 / GPIO1_B0) is intentionally NOT managed in this
 *   overlay: no PWM mux available on this pin, and the schematic R2=10K
 *   pull-up to 3.3V on Q1's base means the BL defaults to ON when BLK is
 *   floating. Leaving GPIO1_B0 at default mux state preserves this behavior.
 */

/dts-v1/;
/plugin/;

#include <dt-bindings/gpio/gpio.h>
#include <dt-bindings/input/input.h>
#include <dt-bindings/pinctrl/rockchip.h>

/ {
	compatible = "rockchip,rk3588s";

	metadata {
		title = "Enable Waveshare 1.3\" LCD HAT (ST7789VM 240x240) + 7 keys on Rock 5C Lite";
		compatible = "radxa,rock-5c-lite";
		category = "display";
		exclusive = "spi4",
			    "GPIO1_A0", "GPIO1_A1", "GPIO1_A2", "GPIO1_A3",
			    "GPIO1_B5", "GPIO4_B2",
			    "GPIO4_B1", "GPIO4_A5", "GPIO4_A2",
			    "GPIO1_B1", "GPIO4_A0", "GPIO1_B2", "GPIO1_B4";
		description = "Bind Waveshare 1.3\" LCD HAT (ST7789VM) on SPI4_M2 with hardware CS; 7 GPIO keys via gpio-keys (KEY_F1..F3 + arrow keys + ENTER). BL (pin 18 = GPIO1_B0) intentionally not managed (no PWM mux; default ON via 10K pull-up on Q1 base). Joy RIGHT (pin 37 = SARADC_VIN2) intentionally absent (no GPIO mux). Init seq from /lib/firmware/panel-mipi-dbi-spi.bin.";
	};

	fragment@0 {
		target = <&spi4>;

		__overlay__ {
			status = "okay";
			pinctrl-names = "default";
			pinctrl-0 = <&spi4m2_cs0 &spi4m2_pins>;
			#address-cells = <1>;
			#size-cells = <0>;

			panel@0 {
				compatible = "panel-mipi-dbi-spi";
				reg = <0>;
				spi-max-frequency = <40000000>;
				dc-gpios    = <&gpio1 RK_PB5 GPIO_ACTIVE_HIGH>;
				reset-gpios = <&gpio4 RK_PB2 GPIO_ACTIVE_HIGH>;
				write-only;
				width-mm  = <23>;
				height-mm = <23>;
				status = "okay";

				panel-timing {
					hactive = <240>;
					vactive = <240>;
					hback-porch  = <0>;
					vback-porch  = <0>;
					hfront-porch = <0>;
					vfront-porch = <0>;
					hsync-len = <0>;
					vsync-len = <0>;
					/* binding requires this; driver does not use pixel clock */
					clock-frequency = <3456000>;
				};
			};
		};
	};

	fragment@1 {
		target-path = "/";

		__overlay__ {
			keys-st7789vm-hat {
				compatible = "gpio-keys";
				pinctrl-names = "default";
				pinctrl-0 = <&keys_st7789vm_pins>;
				autorepeat;

				key-k1 {
					label = "K1";
					linux,code = <KEY_F1>;
					gpios = <&gpio4 RK_PB1 GPIO_ACTIVE_LOW>;
					debounce-interval = <20>;
				};
				key-k2 {
					label = "K2";
					linux,code = <KEY_F2>;
					gpios = <&gpio4 RK_PA5 GPIO_ACTIVE_LOW>;
					debounce-interval = <20>;
				};
				key-k3 {
					label = "K3";
					linux,code = <KEY_F3>;
					gpios = <&gpio4 RK_PA2 GPIO_ACTIVE_LOW>;
					debounce-interval = <20>;
				};
				key-up {
					label = "Joy UP";
					linux,code = <KEY_UP>;
					gpios = <&gpio1 RK_PB1 GPIO_ACTIVE_LOW>;
					debounce-interval = <20>;
				};
				key-down {
					label = "Joy DOWN";
					linux,code = <KEY_DOWN>;
					gpios = <&gpio4 RK_PA0 GPIO_ACTIVE_LOW>;
					debounce-interval = <20>;
				};
				key-left {
					label = "Joy LEFT";
					linux,code = <KEY_LEFT>;
					gpios = <&gpio1 RK_PB2 GPIO_ACTIVE_LOW>;
					debounce-interval = <20>;
				};
				key-press {
					label = "Joy PRESS";
					linux,code = <KEY_ENTER>;
					gpios = <&gpio1 RK_PB4 GPIO_ACTIVE_LOW>;
					debounce-interval = <20>;
				};

				/*
				 * Joy RIGHT (HAT BCM26 → header pin 37) maps to SARADC_VIN2
				 * on Rock 5C Lite — no GPIO mux exists for this pin. Cannot
				 * be wired as digital input. Intentionally absent.
				 */
			};
		};
	};

	fragment@2 {
		target = <&pinctrl>;

		__overlay__ {
			keys-st7789vm-hat {
				keys_st7789vm_pins: keys-st7789vm-pins {
					rockchip,pins =
						<4 RK_PB1 RK_FUNC_GPIO &pcfg_pull_up>,   /* K1 */
						<4 RK_PA5 RK_FUNC_GPIO &pcfg_pull_up>,   /* K2 */
						<4 RK_PA2 RK_FUNC_GPIO &pcfg_pull_up>,   /* K3 */
						<1 RK_PB1 RK_FUNC_GPIO &pcfg_pull_up>,   /* Joy UP */
						<4 RK_PA0 RK_FUNC_GPIO &pcfg_pull_up>,   /* Joy DOWN */
						<1 RK_PB2 RK_FUNC_GPIO &pcfg_pull_up>,   /* Joy LEFT */
						<1 RK_PB4 RK_FUNC_GPIO &pcfg_pull_up>;   /* Joy PRESS */
				};
			};
		};
	};
};
```

### Step 4.3 — Commit（dtso 单独提交，构建一并验证放到 Task 6）

- [ ] **commit**

```bash
git -C /Users/eki/Project/Embedded_Project/flange add \
  components/board/radxa-rock5c-lite/dtso/rk3588s-rock-5c-st7789vm-lcd-keys.dtso
git -C /Users/eki/Project/Embedded_Project/flange commit -m "$(cat <<'EOF'
feat(rock5c-lite): 加 Waveshare 1.3" LCD HAT (ST7789VM) DTS overlay

新增 components/board/radxa-rock5c-lite/dtso/rk3588s-rock-5c-st7789vm-lcd-keys.dtso，
单文件三段 fragment 同时声明：

  1. &spi4 + spi4m2_* pinctrl + panel-mipi-dbi-spi panel@0 节点
     (SPI4_M2 与 RPi 40-pin SPI0 物理位完美对位，硬件 CS 可用)
  2. gpio-keys 节点暴露 7 键：K1-K3 → KEY_F1-F3，Joy UP/DOWN/LEFT/PRESS
     → 标准方向键 + KEY_ENTER
  3. pinctrl 内部上拉 (pcfg_pull_up)：HAT 无外部上拉电阻

关键约束：
- panel 的 reset-gpios 必须声明 GPIO_ACTIVE_HIGH（即使 ST7789 物理 reset
  为低有效）：mainline mipi_dbi_hw_reset() 用 gpiod_set_value() 直写
  release/assert 语义，DT 标 ACTIVE_LOW 会被 gpiolib 翻转成永停 reset
- Backlight (pin 18 / GPIO1_B0) 故意不接管：硬件 R2=10K 上拉默认常亮，
  且该 pin 无 PWM mux
- Joy RIGHT (pin 37 = SARADC_VIN2) 物理上无 GPIO mux，故意不接

下一步在 board config 中把 .dtbo 加入 board_overlays + default_overlays，
并挂 rootfs.panel_firmware 把 init seq 部署到 /lib/firmware/。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5 — 板级 config 改动（连线 overlay 与 panel firmware）

**Goal:** `radxa-rock5c-lite/config.py` 里把新 .dtbo 加入 `boot.board_overlays` + `boot.default_overlays`，并挂 `rootfs.panel_firmware` 让 firmware bin 落到镜像。

**Files:**
- Modify: `components/board/radxa-rock5c-lite/config.py:126-162`

### Step 5.1 — 编辑 board config

- [ ] **修改 BOARD["boot"] 与 BOARD["rootfs"]**

`boot` dict 改为（仅展示需要变化的字段）：

```python
    "boot": {
        # 板私有 overlay 源文件位于 components/board/radxa-rock5c-lite/dtso/，
        # 由 device-tree-overlay 组件用 cpp+dtc 编译为 <stem>.dtbo，打到 boot
        # 分区 /dtbs/rockchip/overlay/。
        "board_overlays": [
            # rk3588s-rock-5c.dts 把 &usbdrd_dwc3_0 的 dr_mode 钉成 "host"，
            # dwc3 当 USB host 用、不暴露 UDC，gadget（adbd / FunctionFS）
            # 无法 bind。本 overlay 切回 peripheral 模式以恢复 OTG device
            # 角色（详见 dtso 文件头注释）。
            "rk3588s-rock-5c-otg-peripheral.dtbo",
            # Waveshare 1.3" LCD HAT (ST7789VM SPI 屏 + 3 键 + 5 向摇杆)
            # 通过 RPi 40-pin GPIO header 直接堆叠；走 mainline drm/tiny
            # panel-mipi-dbi-spi (SPI4_M2 硬件 CS) + gpio-keys。详见
            # dtso 文件头说明（含 RST 极性、BL 不接管、Joy RIGHT 缺失原因）。
            "rk3588s-rock-5c-st7789vm-lcd-keys.dtbo",
        ],
        # 默认启用 USB OTG peripheral overlay：lunch target 出来的整机镜像
        # 默认走 device 模式，方便 adbd / 镜像更新流程。需要 host-only 用法
        # 时从 default_overlays 中剔除即可（运行时编辑 extlinux.conf
        # fdtoverlays，或 lunch 不同 product/variant 走条件配置）。
        # LCD HAT overlay 也默认启用：开机即出图，无需手工启用。
        "default_overlays": [
            "rk3588s-rock-5c-otg-peripheral.dtbo",
            "rk3588s-rock-5c-st7789vm-lcd-keys.dtbo",
        ],
    },
```

`rootfs` dict 在现有 `+extra_firmware` 之后追加 `panel_firmware`：

```python
    "rootfs": {
        # AIC8800D80 USB 固件部署到 /lib/firmware/aic8800D80/（详见原注释）
        "+extra_firmware": [
            {
                "name": "aic8800-d80",
                "source": "oot:aic8800",
                "repo_subdir": "src/USB/driver_fw/aic8800D80",
                "files": AIC8800_D80_USB_FIRMWARE_FILES,
                "dest": "lib/firmware/aic8800D80",
            },
        ],
        # ST7789VM panel-mipi-dbi-spi 的 init 序列：构建期由
        # builder.firmware_panel 把文本源编为 mainline 兼容 panel.bin，
        # 落 rootfs /lib/firmware/panel-mipi-dbi-spi.bin。dest 名固定不可改：
        # driver 不读 DT firmware-name 属性，固定按 <compatible[0]>.bin
        # 在 /lib/firmware/ 下查找。
        "panel_firmware": [
            {
                "src": "firmware/panel/st7789vm-240x240.txt",
                "dest": "panel-mipi-dbi-spi.bin",
            },
        ],
    },
```

> **注意 path:** `repo_subdir` 原值是 `"src/USB/driver_fw/aic8800D80"`，**不要改** —— 这是 commit 725f10e 当时的实测有效路径。本步骤只在 board config 内追加新字段，不要顺手"清理"既有值。

### Step 5.2 — 静态校验 board config 可被 import

- [ ] **import 校验**

```bash
cd /Users/eki/Project/Embedded_Project/flange && python -c "
from components.board.radxa_rock5c_lite.config import BOARD
assert 'rk3588s-rock-5c-st7789vm-lcd-keys.dtbo' in BOARD['boot']['board_overlays']
assert 'rk3588s-rock-5c-st7789vm-lcd-keys.dtbo' in BOARD['boot']['default_overlays']
pf = BOARD['rootfs']['panel_firmware']
assert pf == [{'src': 'firmware/panel/st7789vm-240x240.txt', 'dest': 'panel-mipi-dbi-spi.bin'}], pf
print('OK')
" 2>&1
```

> 如果 board 模块路径用连字符（`radxa-rock5c-lite`），上面 import 会失败。flange builder 实际 load board 走的是 paths/discovery，不是 Python import；改用读 file 的方式校验：
>
> ```bash
> cd /Users/eki/Project/Embedded_Project/flange && python -c "
> import importlib.util, sys
> spec = importlib.util.spec_from_file_location('rock5c_lite_board',
>     'components/board/radxa-rock5c-lite/config.py')
> mod = importlib.util.module_from_spec(spec)
> sys.modules['rock5c_lite_board'] = mod
> spec.loader.exec_module(mod)
> b = mod.BOARD
> assert 'rk3588s-rock-5c-st7789vm-lcd-keys.dtbo' in b['boot']['board_overlays']
> assert 'rk3588s-rock-5c-st7789vm-lcd-keys.dtbo' in b['boot']['default_overlays']
> pf = b['rootfs']['panel_firmware']
> assert pf == [{'src': 'firmware/panel/st7789vm-240x240.txt', 'dest': 'panel-mipi-dbi-spi.bin'}], pf
> print('OK')
> "
> ```

### Step 5.3 — Commit

- [ ] **commit**

```bash
git -C /Users/eki/Project/Embedded_Project/flange add \
  components/board/radxa-rock5c-lite/config.py
git -C /Users/eki/Project/Embedded_Project/flange commit -m "$(cat <<'EOF'
feat(rock5c-lite): 启用 Waveshare 1.3" LCD HAT (ST7789VM) overlay + panel firmware

把新加的 rk3588s-rock-5c-st7789vm-lcd-keys.dtbo 同时挂到 board_overlays
和 default_overlays —— LCD HAT 默认开机即生效。

把 firmware/panel/st7789vm-240x240.txt 通过 rootfs.panel_firmware 字段
注入 RootfsBuilder._install_panel_firmware hook，构建期
builder.firmware_panel 编为 panel.bin、落 rootfs
/lib/firmware/panel-mipi-dbi-spi.bin（dest 名固定，driver 派生自
compatible[0]）。

至此 LCD HAT 三件套（驱动 / 设备树 / firmware）齐备，下一步在板验证：
modetest -M panel-mipi-dbi 出图 + evtest 7 键事件。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6 — 在板验证

**Goal:** Docker 内构建 → 刷板 → 在板上跑全套验证项，每项打勾才能算 feature 完成。

**Pre-req:** 物理 HAT 已堆在 Rock 5C Lite 上；adbd 烧录或 SD 卡刷机环境就绪。

### Step 6.1 — 跑一次仓库回归测试

- [ ] **测试**

```bash
cd /Users/eki/Project/Embedded_Project/flange && \
  pytest tests/builder/test_firmware_panel.py \
         tests/builder/test_rootfs_panel_firmware.py \
         tests/builder/test_rockchip_kernel_panel_fragment.py \
         -v --timeout=60
```

预期：全部 PASS。

### Step 6.2 — Docker 内构建整机镜像

- [ ] **build**

```bash
cd /Users/eki/Project/Embedded_Project/flange && \
  flange lunch radxa-rock5c-lite-userdebug && \
  flange build
```

预期：构建成功，output 目录里有 .img；构建日志能看到：
- `panel_mipi_dbi.config 生成`（来自 `RockchipKernelBuilder._write_panel_mipi_dbi_fragment._status`）
- `device-tree-overlay` 阶段编译出 `rk3588s-rock-5c-st7789vm-lcd-keys.dtbo`
- rootfs 阶段把 `panel-mipi-dbi-spi.bin` 写入 `lib/firmware/`

如果 cpp/dtc 报错（最常见两类）：
- `spi4m2_cs0` undefined → 查看 dtsi 内实际 phandle 名，按 Task 4 Step 4.1 调整
- `<dt-bindings/input/input.h>` 未找到 → 这是标准内核头，确认 cpp -I 是否带了 `arch/arm64/boot/dts/include/`；问题在 `builder/overlays.py` cpp 调用，不是本 dtso 的错

### Step 6.3 — 刷板 & 启动

- [ ] **flash**

```bash
cd /Users/eki/Project/Embedded_Project/flange && flange flash
# (按已有流程：USB peripheral overlay 已 default 启用，adbd 流可用)
```

启动后通过串口 ttyS2@1500000 上 console。

### Step 6.4 — 在板验证（在 Rock 5C Lite shell 里）

- [ ] **driver 加载与 DT probe**

```bash
lsmod | grep -E 'panel_mipi_dbi|drm_mipi_dbi'
# 期望：panel_mipi_dbi、drm_mipi_dbi 都在线

dmesg | grep -E 'panel-mipi-dbi-spi|spi4|gpio-keys'
# 期望：spi4 controller probe ok；panel-mipi-dbi-spi probe ok（dmesg 提到
# 加载 firmware /lib/firmware/panel-mipi-dbi-spi.bin、init seq 已执行）；
# gpio-keys-st7789vm-hat 注册 7 个 input button

ls -l /dev/dri/
# 期望：至少 card0 + renderD128（rk3582 GPU 熔断，无 vop 路径下 panel
# 应该是唯一 card 节点）

ls /dev/input/by-path/ | grep keys-st7789vm
# 期望：有一条带 keys-st7789vm-hat 字样的 event 链接
```

- [ ] **modetest 出图**

```bash
modetest -M panel-mipi-dbi -c
# 期望：列出 SPI-1 connector，状态 connected，模式 240x240

# 用上一步看到的 connector_id 与 crtc_id 替换 <CONN>:<CRTC>
modetest -M panel-mipi-dbi -s <CONN>@<CRTC>:240x240
# 期望：屏上出现彩色 SMPTE 测试条（横屏方向，不旋转）；按 Ctrl+C 退出
# 注：MADCTL=0x70 横屏方向应与摇杆/按键朝向一致
```

如果屏上是花屏 / 全黑：
- 全黑 → 大概率 RST 极性问题。复查 dtso `reset-gpios = <&gpio4 RK_PB2 GPIO_ACTIVE_HIGH>` 是否被改成了 ACTIVE_LOW
- 花屏（颜色错乱）→ COLMOD 不匹配；尝试把 init seq 文件里 `command 0x3A 0x05` 改为 `command 0x3A 0x55`，重 build 重刷
- 显示画面方向不对 → MADCTL；改 `command 0x36 0x70` 的参数（0x00 / 0xC0 / 0xA0 等组合）

- [ ] **evtest 7 键**

```bash
evtest /dev/input/by-path/*keys-st7789vm-hat*event
# 然后逐键按下，观察输出：
#   K1 按下/抬起 → KEY_F1 (59) value=1/0
#   K2          → KEY_F2 (60)
#   K3          → KEY_F3 (61)
#   摇杆 UP     → KEY_UP (103)
#   摇杆 DOWN   → KEY_DOWN (108)
#   摇杆 LEFT   → KEY_LEFT (105)
#   摇杆 PRESS  → KEY_ENTER (28)
#   摇杆 RIGHT  → 无任何事件（intentional，pin 37 = SARADC，不可用）
```

- [ ] **背光默认常亮验证**

```bash
# 屏画面在 modetest 出图时应可见 — BL 默认 ON
# 确认 dts 没误碰 GPIO1_B0
grep -n 'PB0\|GPIO1_B0\|backlight' /sys/firmware/devicetree/base/__overlay__/* 2>/dev/null \
  || dtc -I fs /sys/firmware/devicetree/base 2>/dev/null | grep -E 'PB0|backlight'
# 期望：与 LCD HAT overlay 关联的字符串里都没有 GPIO1_B0 或 backlight 节点
```

- [ ] **既有功能不破回归**

```bash
# AIC8800D80 USB combo 仍然可用
lsusb | grep -i 'AIC\|8800'
iw dev   # 应能看到 wlan0
hciconfig -a | grep -i 'BR/EDR\|UP\|DOWN'

# 6 个 CPU 全 online
nproc   # 期望 6
cat /sys/devices/system/cpu/cpu*/online | sort -u   # 全 1

# adbd 烧录链路（在 host 上 adb devices 应能看到本板）—— 不用真烧，能识别即可
```

### Step 6.5 — 把验证结果记到 wiki/log.md（在 Task 7 中合并提交）

记下日期、构建/在板验证通过项、踩过的坑。**不在本任务 commit。**

---

## Task 7 — Wiki 文档同步（新建板页 + log 条目）

**Goal:** 创建 `wiki/boards/radxa-rock5c-lite.md`（首次创建，commit 725f10e 当时漏建），加 LCD HAT 小节；`wiki/log.md` 加 sync 条目。

**Files:**
- Create: `wiki/boards/radxa-rock5c-lite.md`
- Modify: `wiki/log.md`

### Step 7.1 — 看现有 wiki 板页结构作为模板

- [ ] **看模板**

```bash
cat /Users/eki/Project/Embedded_Project/flange/wiki/boards/radxa-cubie-a7z.md | head -120
ls /Users/eki/Project/Embedded_Project/flange/wiki/boards/
```

照 cubie-a7z 那份的小节顺序（板基本信息 → SoC → 启动链路 → 已启用功能 → 已知限制）写。

### Step 7.2 — 创建 `wiki/boards/radxa-rock5c-lite.md`

- [ ] **新建板页**

骨架（具体小节内容按当前实际 board config 与本 plan 验证结果填）：

```markdown
# Radxa ROCK 5C Lite

## 板基本信息

- SoC：Rockchip **RK3582**（与 RK3588S 同 die、binned；2× Cortex-A76
  + 4× Cortex-A55，Mali-G610 GPU 在 silicon fuse 阶段被禁用）
- Flange platform：`rockchip`，soc：`rk3582`
- Lunch target：`radxa-rock5c-lite-userdebug`
- 与 ROCK 5C 共用 PCB；Radxa rkr5.1 BSP 共用 dts `rk3588s-rock-5c.dts`

## 启动链路

- U-Boot：radxa next-dev-v2024.10，rk3588_defconfig（generic）
- rkbin：`mkimage_chip = rk3588`（同 BootROM）
- Kernel：linux-6.1-stan-rkr5.1，defconfig 合并：
  rockchip_linux_defconfig → case_insensitive_fix.config → panel_mipi_dbi.config
- 调试串口：UART2 / `ttyS2,1500000`

## WiFi/BT — AIC8800D80 USB combo

- Driver：radxa-pkg/aic8800 OOT（commit `7f42b22…`），
  `aic_load_fw.ko` + `aic8800_fdrv.ko` + `aic_btusb.ko`
- Firmware 目录：`/lib/firmware/aic8800D80/`
- BT 子树构建：`KCFLAGS=-Wno-error` 关 Werror

## USB-C OTG

- 默认走 peripheral 模式（`rk3588s-rock-5c-otg-peripheral.dtbo` 自动启用），
  使 adbd / FunctionFS gadget 可用；host-only 用法需从
  `default_overlays` 移除该 overlay

## 1.3″ LCD HAT (ST7789VM 240×240)

直接堆叠 Waveshare 1.3" LCD HAT 在 40-pin GPIO header 上，启用：

- LCD：mainline drm/tiny `panel-mipi-dbi-spi`，`/dev/dri/card*`，分辨率 240×240，
  默认横屏（MADCTL=0x70）
- 7 GPIO 按键：K1-K3 → `KEY_F1`-`F3`，Joy UP/DOWN/LEFT/PRESS → 标准方向键 + `KEY_ENTER`

| HAT 信号 | 物理 pin | RK GPIO | 复用 |
|---|---|---|---|
| MOSI / MISO / SCLK / CS0 | 19 / 21 / 23 / 24 | GPIO1_A1 / A0 / A2 / A3 | SPI4_M2（硬件 CS）|
| DC / RST | 22 / 13 | GPIO1_B5 / GPIO4_B2 | GPIO output（RST 必 ACTIVE_HIGH）|
| BL | 18 | GPIO1_B0 | **不接管**：硬件 R2=10K 上拉默认常亮 |
| K1 / K2 / K3 | 40 / 38 / 36 | GPIO4_B1 / A5 / A2 | GPIO input + pull_up |
| Joy UP / DOWN / LEFT / PRESS | 31 / 35 / 29 / 33 | GPIO1_B1 / GPIO4_A0 / GPIO1_B2 / GPIO1_B4 | GPIO input + pull_up |
| ~~Joy RIGHT~~ | ~~37~~ | ~~SARADC_VIN2~~ | ❌ 物理上无 GPIO mux，不可用 |

启用方式：overlay `rk3588s-rock-5c-st7789vm-lcd-keys.dtbo` 已加入
`default_overlays`，开机即生效。

### 已知限制

- **背光不可调光**：pin 18 (GPIO1_B0) 七个 mux function 无 PWM；用户态写
  `/sys/class/backlight/*/brightness` 也无效（dts 未声明 backlight 节点）
- **摇杆右键不工作**：HAT 的 BCM26 物理上落到 Rock 5C Lite pin 37 = SARADC_VIN2，
  无 GPIO mux

### 文件位置

- DTS overlay 源：
  `components/board/radxa-rock5c-lite/dtso/rk3588s-rock-5c-st7789vm-lcd-keys.dtso`
- Init seq 源：
  `components/board/radxa-rock5c-lite/firmware/panel/st7789vm-240x240.txt`
- 板配置入口：`components/board/radxa-rock5c-lite/config.py`
- SoC 配置（panel fragment 引入处）：
  `components/platform/rockchip/rk3582/config.py`
- Builder fragment 生成器：
  `builder/platforms/rockchip/kernel.py::RockchipKernelBuilder._write_panel_mipi_dbi_fragment`
```

### Step 7.3 — `wiki/log.md` 增条目

- [ ] **看 log.md 现有条目格式**

```bash
tail -30 /Users/eki/Project/Embedded_Project/flange/wiki/log.md
```

按现有格式（日期 + commit hash + 一句话）追加一条，例如：

```markdown
- 2026-05-07 — feat(rock5c-lite): Waveshare 1.3" LCD HAT (ST7789VM) tinydrm
  屏幕 + 7 键支持。SPI4_M2 硬件 CS、drm/tiny panel-mipi-dbi-spi、gpio-keys。
  详见 [boards/radxa-rock5c-lite.md](boards/radxa-rock5c-lite.md#13-lcd-hat-st7789vm-240240)。
```

### Step 7.4 — Commit

- [ ] **commit wiki**

```bash
git -C /Users/eki/Project/Embedded_Project/flange add \
  wiki/boards/radxa-rock5c-lite.md \
  wiki/log.md
git -C /Users/eki/Project/Embedded_Project/flange commit -m "$(cat <<'EOF'
docs(wiki): 新建 radxa-rock5c-lite 板页 + ST7789VM LCD HAT 小节

- 新建 wiki/boards/radxa-rock5c-lite.md（commit 725f10e 当时未建板页）
- 板基本信息、启动链路、AIC8800D80 USB combo、USB-C OTG、1.3" LCD HAT 全套小节
- pin 占用表 + 已知限制（BL 不可调光、摇杆右键不可用的硬件原因）
- wiki/log.md 加本次同步条目

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Self-Review 检查项（实施完毕后跑一次）

- [ ] **Spec 覆盖**：spec §1.1 三个目标、§1.2 五个非目标、§3.1 文件清单全部对应到本 plan 的某 task
- [ ] **占位符扫描**：plan 内无 "TBD/TODO/implement later"
- [ ] **类型一致**：fragment 文件名 `panel_mipi_dbi.config` 在 Task 1 / 2 / 6 / 7 完全一致；overlay 名 `rk3588s-rock-5c-st7789vm-lcd-keys.dtbo` 在 Task 4 / 5 / 7 完全一致；firmware bin 名 `panel-mipi-dbi-spi.bin` 在 Task 3 / 5 / 6 完全一致
- [ ] **关键约束**没漏：RST ACTIVE_HIGH、firmware dest 名固定、BL 不接管、Joy RIGHT 不接 — 这 4 条在 dtso 注释 + commit 信息 + wiki 中重复出现
