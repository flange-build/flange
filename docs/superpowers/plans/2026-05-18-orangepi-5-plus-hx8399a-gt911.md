# OrangePi 5 Plus HX8399-A 1080×1920 DSI 屏 + GT911 触摸 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 OrangePi 5 Plus 上落地 HX8399-A 1080×1920 portrait DSI 面板 +
GT911 5-point 电容触摸适配，开机即点亮、触摸事件 5 点可用、HDMI 不受影响。

**Architecture:** board overlay (`.dtso → .dtbo`) 走 extlinux fdtoverlays 路径；
panel driver 复用 BSP `simple-panel-dsi` + `panel-init-sequence` 字节流；触摸
走 mainline `goodix.c` 并通过 `request_firmware("goodix_911_cfg.bin")` 加载
cfg；cfg blob 通过 board `overlay/lib/firmware/` 现成 cp -a 机制部署，**零
内核 patch、零 driver 新增、零 builder 改动**。

**Tech Stack:**

- argon BSP `linux-6.1-stan-rkr5.1` kernel + `drivers/gpu/drm/panel/panel-simple.c`（BSP fork）
- mainline `drivers/input/touchscreen/goodix.c`
- DTC overlay + cpp preprocessor
- 仓库现有 `components/board/<board>/{dtso,overlay}/` 机制（无需扩 builder/source.py）

**spec 精化说明（与 `docs/superpowers/specs/2026-05-18-orangepi-5-plus-hx8399a-gt911-design.md` 的差异）：**

- spec §5 试图通过 `rootfs.+extra_firmware` 加 `source: "board"` 部署 cfg blob，
  但实测 `builder/source.py:ensure_extra_firmware()` 仅支持 `"repo"` / `"kernel"`
  / `"bootloader"` / `"oot:<name>"` 四类 source。spec 同节已留兜底脚注。
- 实施期精化：改走 `components/board/orangepi-5-plus/overlay/lib/firmware/goodix_911_cfg.bin`，
  由现有 `_install_overlays` (`builder/rootfs.py:42-50`) 整棵子树 cp -a 到
  rootfs。零 builder 改动；与 board 自有 `overlay/etc/hostname` 同模式。
- 其他章节（dtso 内容、init-sequence 字节流、风险列表等）原样落地。

---

## File Structure

**新增文件：**

```
components/board/orangepi-5-plus/
├── dtso/
│   └── rk3588-orangepi-5-plus-hx8399a-gt911.dtso         # 整 overlay 单文件
├── firmware/
│   └── touch/
│       └── goodix_911_cfg.cfg                            # 原 ASCII cfg，review 用
└── overlay/
    └── lib/
        └── firmware/
            └── goodix_911_cfg.bin                        # 186B 二进制，部署用
```

**修改文件：**

```
components/board/orangepi-5-plus/config.py                # +boot.board_overlays / default_overlays
tests/config/test_orangepi_5_plus.py                       # +board_overlays 测试
```

**职责划分：**

- `dtso/*.dtso`：单文件描述全部硬件接线（dsi1 enable / panel override / i2c7 + GT911）
- `firmware/touch/*.cfg`：原 ASCII 文本，仅供 review；不被 build 系统读取
- `overlay/lib/firmware/*.bin`：二进制，build 时 cp 到 rootfs `/lib/firmware/`
- `config.py`：声明 board overlay 名 + 默认应用
- `tests/config/test_orangepi_5_plus.py`：合并配置 invariants（新增 board_overlays 字段）

---

## Task 1: 落 GT911 cfg ASCII 源（review 可读）

**Files:**
- Create: `components/board/orangepi-5-plus/firmware/touch/goodix_911_cfg.cfg`

这个文件**不参与 build**，仅作为 `.bin` 的可读 source of truth（与 wiki rock5c-lite `st7789vm-240x240.txt` 同模式但选择各自的二进制策略）。内容直接抄用户提供的 `/Users/eki/Downloads/触摸驱动IC/GT911_Config_20240308_111925-PP.cfg`。

- [ ] **Step 1: 新建文件并写入 186 hex tokens 的 ASCII 源**

```bash
mkdir -p components/board/orangepi-5-plus/firmware/touch
```

Write `components/board/orangepi-5-plus/firmware/touch/goodix_911_cfg.cfg` with the exact content of the user-supplied file:

```
0x47,0x38,0x04,0x80,0x07,0x05,0x35,0x00,0x01,0x08,0x28,0x05,0x50,0x32,0x03,0x05,
0x00,0x00,0x00,0x00,0x11,0x11,0x00,0x16,0x1A,0x20,0x14,0x8B,0x2B,0x0C,0x35,0x37,
0x7C,0x06,0x00,0x00,0x00,0x9B,0x02,0x1C,0x00,0x00,0x00,0x00,0x00,0x03,0x64,0x32,
0x00,0x00,0x00,0x32,0x87,0x94,0xC5,0x02,0x07,0x00,0x00,0x04,0x7B,0x37,0x00,0x67,
0x43,0x00,0x55,0x52,0x00,0x47,0x64,0x00,0x3C,0x7A,0x00,0x3C,0x00,0x00,0x00,0x00,
0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,
0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,
0x18,0x16,0x14,0x12,0x10,0x0E,0x0C,0x0A,0x08,0x06,0x04,0x02,0xFF,0xFF,0xFF,0xFF,
0xFF,0xFF,0xFF,0xFF,0xFF,0xFF,0xFF,0xFF,0xFF,0xFF,0xFF,0xFF,0xFF,0xFF,0x26,0x24,
0x22,0x21,0x20,0x1F,0x1E,0x1D,0x1C,0x18,0x16,0x13,0x12,0x10,0x0F,0x0C,0x0A,0x08,
0x06,0x04,0x02,0x00,0xFF,0xFF,0xFF,0xFF,0xFF,0xFF,0xFF,0xFF,0xFF,0xFF,0xFF,0xFF,
0xFF,0xFF,0xFF,0xFF,0xFF,0xFF,0xFF,0xFF,0x80,0x01
```

- [ ] **Step 2: 验证 token 数 = 186**

```bash
grep -oE '0x[0-9A-Fa-f]{2}' components/board/orangepi-5-plus/firmware/touch/goodix_911_cfg.cfg | wc -l
```
Expected output: `     186`（macOS `wc` 前导空白可能不同，重点是数字 186）

- [ ] **Step 3: Commit**

```bash
git add components/board/orangepi-5-plus/firmware/touch/goodix_911_cfg.cfg
git commit -m "chore(board/orangepi-5-plus): 入库 GT911 186B cfg ASCII 源

source of truth (review 可读)：mainline goodix.c request_firmware 实际
读取 binary 形态 goodix_911_cfg.bin（下一 commit 落 overlay 树）。"
```

---

## Task 2: 生成并落 GT911 cfg 二进制部署 blob

**Files:**
- Create: `components/board/orangepi-5-plus/overlay/lib/firmware/goodix_911_cfg.bin`

mainline `goodix.c:1402` 读 `/lib/firmware/goodix_<id>_cfg.bin`，GT911 chip `id="911"` → 文件名 `goodix_911_cfg.bin`。

- [ ] **Step 1: 建目录**

```bash
mkdir -p components/board/orangepi-5-plus/overlay/lib/firmware
```

- [ ] **Step 2: 从 ASCII 源生成 186B binary**

```bash
python3 -c "
import re, pathlib
src = pathlib.Path('components/board/orangepi-5-plus/firmware/touch/goodix_911_cfg.cfg').read_text()
data = bytes(int(t, 16) for t in re.findall(r'0x([0-9A-Fa-f]{2})', src))
assert len(data) == 186, f'expected 186 bytes, got {len(data)}'
pathlib.Path('components/board/orangepi-5-plus/overlay/lib/firmware/goodix_911_cfg.bin').write_bytes(data)
print(f'wrote {len(data)} bytes')
"
```
Expected output: `wrote 186 bytes`

- [ ] **Step 3: 校验文件大小与首尾字节**

```bash
ls -l components/board/orangepi-5-plus/overlay/lib/firmware/goodix_911_cfg.bin
xxd components/board/orangepi-5-plus/overlay/lib/firmware/goodix_911_cfg.bin | head -1
xxd components/board/orangepi-5-plus/overlay/lib/firmware/goodix_911_cfg.bin | tail -1
```
Expected:
- size = 186
- 首行起始：`00000000: 4738 0480 0705 3500 0108 2805 5032 0305`（即 `0x47 0x38 0x04 0x80 ...`）
- 末行末尾以 `8001` 结尾

- [ ] **Step 4: Commit**

```bash
git add components/board/orangepi-5-plus/overlay/lib/firmware/goodix_911_cfg.bin
git commit -m "feat(board/orangepi-5-plus): 部署 GT911 186B cfg blob 到 rootfs

放在 board overlay/lib/firmware/，由 builder/rootfs.py _install_overlays
机制 cp -a 到 rootfs；mainline goodix.c probe 时
request_firmware('goodix_911_cfg.bin') 拉文件，按 chip 内 cfg version 与
host (0x47) 比对，host 高即下发覆盖 chip flash 默认。"
```

---

## Task 3: 写 board overlay dtso

**Files:**
- Create: `components/board/orangepi-5-plus/dtso/rk3588-orangepi-5-plus-hx8399a-gt911.dtso`

dtso 内容来源 spec §2/§3，下面是完整文件。关键注意：

- 全部 `&label{}` fragment，**不引入根级裸节点**（wiki orangepi-cm4 教训 #5）
- 不使用 `MIPI_DSI_MODE_EOT_PACKET`（spec §6 R1：argon BSP 6.1 头文件已只剩新名 `MIPI_DSI_MODE_NO_EOT_PACKET`，不引用旧名即可走"默认发 EOT"路径）
- 覆盖 base dtsi 钉死的 `compatible = "innolux,afj101-ba2131"`
- VOP3 → DSI1 路由独立，不影响 HDMI0(VP0) / HDMI1(VP1)

- [ ] **Step 1: 建目录**

```bash
mkdir -p components/board/orangepi-5-plus/dtso
```

- [ ] **Step 2: 写 dtso 文件（完整内容）**

Write `components/board/orangepi-5-plus/dtso/rk3588-orangepi-5-plus-hx8399a-gt911.dtso`:

```dts
/*
 * OrangePi 5 Plus 板载 30-pin DSI FPC 接 HX8399-A 1080×1920 portrait 4-lane
 * MIPI DSI 面板 + GT911 5-point 电容触摸 overlay。
 *
 * 接线（依据 vendor BSP rk3588-orangepi-5-plus-lcd.dtsi）：
 *   - DSI 控制器：&dsi1（4-lane，VOP3 → dsi1_in_vp3）
 *   - Panel reset：GPIO2_C1 active-low
 *   - Panel VCC_LCD EN：GPIO1_D2 active-high
 *   - Panel backlight：&backlight_1（base dtsi 已存在的 PWM-backlight）
 *   - Touch I2C：i2c7 @ 0x14
 *   - Touch INT：GPIO2_B2 rising edge（与 cfg byte6=0x35 bit[0]=1 一致）
 *   - Touch RST：GPIO2_B5 active-high
 *
 * Panel driver：BSP simple-panel-dsi（drivers/gpu/drm/panel/panel-simple.c），
 * 通过 panel-init-sequence 字节流喂 16 条 DCS 命令（来源：LCD 厂提供的
 * LCD初始化代码.c，PacketHeader/wait/dlen/Payload 与 dts 字节格式 1:1 对应）。
 *
 * Touch driver：mainline drivers/input/touchscreen/goodix.c。compatible
 * "goodix,gt911" 命中 mainline；vendor gt9xx 仅匹配 "goodix,gt9xx"，不抢
 * 本节点。driver 启动时 request_firmware("goodix_911_cfg.bin") 拉 186B cfg
 * 下发到 chip。
 *
 * 不使用 MIPI_DSI_MODE_EOT_PACKET 旧名宏：argon BSP linux-6.1-stan-rkr5.1
 * 头文件已只剩 MIPI_DSI_MODE_NO_EOT_PACKET（新名、反语义）。不引用旧名
 * 即走"默认发 EOT"路径，与新 6.x 默认行为一致；HX8399-A 实测发 EOT 兼容。
 *
 * 全部 fragment 走 &label{} target，根级 / 仅含 metadata，不新增根级节点
 * （规避 wiki orangepi-cm4 屏适配踩过的 dtso 根级裸节点 → FDT_ERR_BADOVERLAY
 *  在 u-boot fdt_overlay_apply 阶段失败）。
 */

/dts-v1/;
/plugin/;

#include <dt-bindings/gpio/gpio.h>
#include <dt-bindings/pinctrl/rockchip.h>
#include <dt-bindings/interrupt-controller/irq.h>
#include <dt-bindings/display/drm_mipi_dsi.h>

/ {
    compatible = "rockchip,rk3588";

    metadata {
        title = "HX8399-A 1080x1920 MIPI-DSI panel + GT911 capacitive touch on 30-pin DSI FPC";
        compatible = "xunlong,orangepi-5-plus";
        category = "display";
        exclusive = "&dsi1", "&i2c7";
        description = "Drive DSI1 with HX8399-A 4-lane 1080x1920 portrait panel; GT911 5-point touch on i2c7 @0x14.";
    };
};

&dsi1 {
    status = "okay";
};

&dsi1_in_vp3 {
    status = "okay";
};

&route_dsi1 {
    status = "okay";
    connect = <&vp3_out_dsi1>;
};

&dsi1_panel {
    status = "okay";
    /* 覆盖 base dtsi 钉死的 "innolux,afj101-ba2131"（1280x800 横屏）。 */
    compatible = "simple-panel-dsi";

    reset-gpios  = <&gpio2 RK_PC1 GPIO_ACTIVE_LOW>;
    enable-gpios = <&gpio1 RK_PD2 GPIO_ACTIVE_HIGH>;
    pinctrl-names = "default";
    pinctrl-0 = <&lcd_rst_gpio>;
    backlight = <&backlight_1>;

    dsi,flags  = <(MIPI_DSI_MODE_VIDEO | MIPI_DSI_MODE_VIDEO_BURST | MIPI_DSI_MODE_LPM)>;
    dsi,format = <MIPI_DSI_FMT_RGB888>;
    dsi,lanes  = <4>;

    /*
     * 16 条 DCS 命令，字节格式 [data_type, delay_ms, payload_length, payload...]
     * 与 LCD 厂 .c 文件 {PacketHeader, wait, dlen, Payload[]} 1:1 对应。
     * 总字节 = 3*16 + Σpayload_length = 48 + 271 = 319。
     */
    panel-init-sequence = [
        /* 1.  EXTC password           */ 39 00 04  B9 FF 83 99
        /* 2.  MIPI control, 4-lane    */ 15 00 02  BA 43
        /* 3.  Reserved D2             */ 15 00 02  D2 44
        /* 4.  Power control B1        */ 39 00 0D  B1 00 7C 34 34 44 09 22 22 71 F1 B2 4A
        /* 5.  Display control B2      */ 39 00 0B  B2 00 80 00 7F 05 07 23 4D 21 01
        /* 6.  Timing control B4 (41B) */ 39 00 29  B4 00 FF 02 40 02 40 00 00 06 00 01 02 00 0F 01 02 05 20 00 04 44 02 40 02 40 00 00 06 00 01 02 00 0F 01 02 05 00 00 04 44
        /* 7.  GIP1 (D3) + 5ms wait    */ 39 05 20  D3 00 01 00 00 00 06 00 00 10 04 00 04 00 00 00 00 00 00 00 00 00 00 01 05 05 07 00 00 00 05 08
        /* 8.  GIP2 (D5) + 5ms         */ 39 05 21  D5 18 18 19 19 18 18 21 20 01 00 07 06 05 04 03 02 18 18 18 18 18 18 30 30 31 31 32 32 18 18 18 18
        /* 9.  GIP3 (D6) + 5ms         */ 39 05 21  D6 18 18 19 19 40 40 20 21 06 07 00 01 02 03 04 05 40 40 40 40 40 40 30 30 31 31 32 32 40 40 40 40
        /* 10. GIP4 (D8) 49 bytes      */ 39 00 31  D8 A2 AA 02 A0 A2 A8 02 A0 B0 00 00 00 B0 00 00 00 B0 00 00 00 B0 00 00 00 E2 AA 03 F0 E2 AA 03 F0 00 00 00 00 00 00 00 00 E2 AA 03 F0 E2 AA 03 F0
        /* 11. VCOM (B6)               */ 39 00 03  B6 29 29
        /* 12. Gamma (E0) 43 bytes     */ 39 00 2B  E0 01 06 06 2A 2F 3E 0F 3A 05 09 0F 13 15 14 15 12 18 07 16 07 14 01 06 06 2A 2F 3E 0F 3A 05 09 0F 13 15 14 15 12 18 07 16 07 14
        /* 13. Display inversion ON    */ 05 00 01  21
        /* 14. MADCTL = 0x02           */ 15 00 02  36 02
        /* 15. SLPOUT  + 255ms         */ 05 FF 01  11
        /* 16. DISPON  + 255ms         */ 05 FF 01  29
    ];

    disp_timings: display-timings {
        native-mode = <&dsi1_timing0>;
        dsi1_timing0: timing0 {
            clock-frequency = <148500000>;
            hactive  = <1080>;
            vactive  = <1920>;
            hback-porch  = <50>;
            hfront-porch = <100>;
            hsync-len    = <30>;
            vback-porch  = <14>;
            vfront-porch = <8>;
            vsync-len    = <2>;
            hsync-active = <0>;
            vsync-active = <0>;
            de-active    = <1>;
            pixelclk-active = <0>;
        };
    };
};

&i2c7 {
    status = "okay";

    touchscreen@14 {
        compatible = "goodix,gt911";
        reg = <0x14>;
        interrupt-parent = <&gpio2>;
        interrupts = <RK_PB2 IRQ_TYPE_EDGE_RISING>;
        irq-gpios   = <&gpio2 RK_PB2 GPIO_ACTIVE_HIGH>;
        reset-gpios = <&gpio2 RK_PB5 GPIO_ACTIVE_HIGH>;
        touchscreen-size-x = <1080>;
        touchscreen-size-y = <1920>;
        status = "okay";
    };
};
```

- [ ] **Step 3: 静态校验 panel-init-sequence 总字节数 = 319**

```bash
python3 -c "
import re, pathlib
src = pathlib.Path('components/board/orangepi-5-plus/dtso/rk3588-orangepi-5-plus-hx8399a-gt911.dtso').read_text()
# 提取 panel-init-sequence = [ ... ] 中的字节
m = re.search(r'panel-init-sequence\s*=\s*\[(.*?)\];', src, re.DOTALL)
assert m, 'panel-init-sequence not found'
body = re.sub(r'/\*.*?\*/', '', m.group(1), flags=re.DOTALL)
tokens = re.findall(r'\b[0-9A-Fa-f]{2}\b', body)
print(f'total bytes: {len(tokens)}')
# 校验每条命令 payload_length 与实际后续字节匹配
i = 0
cnt = 0
while i < len(tokens):
    dtype = int(tokens[i], 16)
    delay = int(tokens[i+1], 16)
    plen = int(tokens[i+2], 16)
    payload = tokens[i+3:i+3+plen]
    assert len(payload) == plen, f'cmd {cnt}: header.payload_length={plen} but got {len(payload)} bytes'
    cnt += 1
    i += 3 + plen
assert cnt == 16, f'expected 16 cmds, got {cnt}'
assert len(tokens) == 319, f'expected 319 total bytes, got {len(tokens)}'
print(f'cmd count: {cnt}, OK')
"
```
Expected:
```
total bytes: 319
cmd count: 16, OK
```

- [ ] **Step 4: Commit**

```bash
git add components/board/orangepi-5-plus/dtso/rk3588-orangepi-5-plus-hx8399a-gt911.dtso
git commit -m "feat(board/orangepi-5-plus): 新增 HX8399-A 1080×1920 DSI 屏 + GT911 触摸 overlay

dtso 单文件描述 30-pin DSI FPC 接 HX8399-A 4-lane MIPI DSI + GT911 5-point
触摸（接线参考 vendor rk3588-orangepi-5-plus-lcd.dtsi）。Panel 走 BSP
simple-panel-dsi + panel-init-sequence 16 条 DCS 命令（转自 LCD 厂提供 .c
init code）；触摸走 mainline goodix.c（与 vendor gt9xx 不撞 compatible）。

全部 &label{} fragment，规避 wiki orangepi-cm4 屏适配踩过的根级裸节点
FDT_ERR_BADOVERLAY 坑。"
```

---

## Task 4: 更新 `config.py` 接入 board overlay

**Files:**
- Modify: `components/board/orangepi-5-plus/config.py`

在既有 `BOARD` dict 中追加 `boot` 键（与 rock5b/rock5c-lite 同结构）。**不动** `kernel` / `rootfs` 既有内容。

- [ ] **Step 1: 当前 config.py 文件读一次确认锚点**

```bash
cat components/board/orangepi-5-plus/config.py | head -90
```
Expected: 看到 `BOARD = { ... }` 结构，末尾 `"rootfs": { "+extra_firmware": [...] },` 块结束、`}` 闭合 dict。

- [ ] **Step 2: 在 `"kernel"` 块与 `# 账号体系沿用 ...` 注释之间插入 `boot` 块**

修改 `components/board/orangepi-5-plus/config.py`，把当前

```python
        ],
    },
    # 账号体系沿用 components/rootfs/config.py base 层默认：root 完全锁定
```

改为

```python
        ],
    },
    "boot": {
        # 30-pin DSI FPC 板载接口的 HX8399-A 1080×1920 portrait 面板 +
        # GT911 5-point 电容触摸 overlay。默认即应用（写进 extlinux.conf
        # 的 fdtoverlays）。
        # rollback：改 /boot/extlinux/extlinux.conf 去掉 fdtoverlays 一行，
        # 或重刷无此 overlay 的镜像。
        # 接线依据 vendor rk3588-orangepi-5-plus-lcd.dtsi；触摸 cfg blob
        # 通过 board overlay/lib/firmware/goodix_911_cfg.bin 走 _install_overlays
        # 现成 cp -a 机制部署，mainline goodix.c 启动时 request_firmware
        # 拉文件下发。
        "board_overlays": [
            "rk3588-orangepi-5-plus-hx8399a-gt911.dtbo",
        ],
        "default_overlays": [
            "rk3588-orangepi-5-plus-hx8399a-gt911.dtbo",
        ],
    },
    # 账号体系沿用 components/rootfs/config.py base 层默认：root 完全锁定
```

- [ ] **Step 3: 语法静态校验**

```bash
python3 -c "
import importlib.util, pathlib
spec = importlib.util.spec_from_file_location('cfg', 'components/board/orangepi-5-plus/config.py')
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
b = mod.BOARD
assert 'boot' in b, 'missing boot key'
assert b['boot']['board_overlays'] == ['rk3588-orangepi-5-plus-hx8399a-gt911.dtbo']
assert b['boot']['default_overlays'] == ['rk3588-orangepi-5-plus-hx8399a-gt911.dtbo']
# 既有字段不动
assert b['kernel']['dts'] == 'rk3588-orangepi-5-plus'
assert any(o['name']=='rkwifibt-rtl8852be' for o in b['rootfs']['+extra_firmware'])
print('config.py 校验通过')
"
```
Expected: `config.py 校验通过`

- [ ] **Step 4: 跑既有板配置测试看是否被破坏**

```bash
cd /Volumes/bsp/flange && python3 -m pytest tests/config/test_orangepi_5_plus.py -v
```
Expected:
- 大多数原测试 PASS
- 可能 fail 的：测"无板级 overlay"的那一条（在合并后断言 `board_overlays == []` 之类）。FAIL 是预期 —— 下一 Task 5 重写它

- [ ] **Step 5: 暂不 commit，依赖 Task 5 测试一起 commit**

---

## Task 5: 更新 `test_orangepi_5_plus.py` 反映新 board_overlays

**Files:**
- Modify: `tests/config/test_orangepi_5_plus.py`

测试用例需要更新两处：一是模块顶 docstring 提到的"无板级 dtso/board_overlays"，二是若有原"无 overlay"的断言用例需要改成新 overlay。

- [ ] **Step 1: 先 grep 原测试找需要改的位置**

```bash
grep -nE 'board_overlays|无.*overlay|无板级|default_overlays' tests/config/test_orangepi_5_plus.py
```
记录所有命中行号。

- [ ] **Step 2: 改 docstring（顶部）**

把模块 docstring 中"无板级 dtso/board_overlays"措辞改为"HX8399-A DSI 屏 + GT911 触摸 board overlay"。例：

```python
"""OrangePi 5 Plus 板级配置三层合并验证。

覆盖 rockchip-orangepi-5-plus spec 中的 board 字段、SoC 层不被覆盖、
RTL8852BE OOT 链路、HX8399-A + GT911 board overlay、lunch target
自动生成五项 requirement。WiFi/BT OOT 链路与 radxa-rock5b 逐字段等价
（按值比较）。
"""
```

- [ ] **Step 3: 在 `TestOrangePi5PlusMergedConfig` 类中增加 board_overlays 测试**

在该类末尾追加：

```python
    def test_board_overlays_hx8399a_gt911(self, merged):
        """HX8399-A 1080×1920 DSI 屏 + GT911 触摸 overlay 列表正确。"""
        overlays = merged["boot"]["board_overlays"]
        default_overlays = merged["boot"]["default_overlays"]
        assert "rk3588-orangepi-5-plus-hx8399a-gt911.dtbo" in overlays
        assert "rk3588-orangepi-5-plus-hx8399a-gt911.dtbo" in default_overlays

    def test_board_overlay_dtso_source_exists(self):
        """对应 .dtso 源文件必须存在，否则 device-tree-overlay 编不出 dtbo。"""
        from pathlib import Path
        src = Path(
            "components/board/orangepi-5-plus/dtso/"
            "rk3588-orangepi-5-plus-hx8399a-gt911.dtso"
        )
        assert src.is_file(), f"缺失 dtso 源: {src}"

    def test_gt911_cfg_blob_in_overlay_tree(self):
        """GT911 cfg blob 必须放在 board overlay/lib/firmware/，否则
        rootfs cp -a 不会带它进 /lib/firmware/，goodix.c request_firmware
        会失败。文件大小必须 = 186 字节（cfg 寄存器区 186B）。"""
        from pathlib import Path
        blob = Path(
            "components/board/orangepi-5-plus/overlay/"
            "lib/firmware/goodix_911_cfg.bin"
        )
        assert blob.is_file(), f"缺失 cfg blob: {blob}"
        assert blob.stat().st_size == 186, (
            f"GT911 cfg 必须 186 字节，实际 {blob.stat().st_size}")
```

- [ ] **Step 4: 若有"无板级 overlay"原断言，删除/改写**

```bash
grep -nE 'board_overlays.*==.*\[\]|no.*board.*overlay|board_overlays.*not in' tests/config/test_orangepi_5_plus.py
```
若有命中，将相关测试方法整段删除（已被 Step 3 新增的 test_board_overlays_hx8399a_gt911 取代）。

- [ ] **Step 5: 跑测试**

```bash
cd /Volumes/bsp/flange && python3 -m pytest tests/config/test_orangepi_5_plus.py -v
```
Expected: 全部 PASS（含 3 个新增）

- [ ] **Step 6: Commit `config.py` + 测试**

```bash
git add components/board/orangepi-5-plus/config.py tests/config/test_orangepi_5_plus.py
git commit -m "feat(board/orangepi-5-plus): 接入 HX8399-A DSI 屏 + GT911 触摸 overlay

config.py 加 boot.board_overlays / default_overlays 指向新 dtbo；
test 加 3 项断言：overlay 列表、dtso 源文件存在、GT911 cfg blob 186B
正确部署在 overlay/lib/firmware/。"
```

---

## Task 6: 端到端构建烟测

**Files:** 无（只 build）

到这一步所有源码改动已 commit；跑 `flange build` 看 boot 分区与 rootfs 是否含全部新文件。

- [ ] **Step 1: lunch 一个 orangepi-5-plus target**

```bash
cd /Volumes/bsp/flange && source envsetup.sh && lunch orangepi-5-plus-default-debug
```
Expected: lunch 输出 board=orangepi-5-plus，无 error。

> 实际 product/variant 名按本仓 `target/` 现有定义；若 `default-debug` 不存在用 `flange lunch list` 查看可用 target。

- [ ] **Step 2: 触发 device-tree-overlay 组件构建**

```bash
flange build device-tree-overlay
```
Expected: 看到日志含 `rk3588-orangepi-5-plus-hx8399a-gt911.dtso → .dtbo`，cpp+dtc 无 syntax error，特别注意**不**出现：
- `MIPI_DSI_MODE_EOT_PACKET undeclared`
- `cannot find label dsi1_panel`
- `FDT_ERR_BADOVERLAY`

若出现 `MIPI_DSI_MODE_EOT_PACKET undeclared` → 已规避（dtso 不引用旧名）；若仍出现则说明用错 header，回查 dtso include。

- [ ] **Step 3: 验证 dtbo 落在 boot 分区目录**

```bash
find .build -name 'rk3588-orangepi-5-plus-hx8399a-gt911.dtbo' -ls
```
Expected: 至少一条命中，路径含 `dtbs/rockchip/overlay/`。

- [ ] **Step 4: 跑完整 image build**

```bash
flange build image
```
Expected: 构建成功，最终产出 image 文件。

- [ ] **Step 5: 校验 rootfs 内 GT911 cfg blob 存在**

定位最终 rootfs 落盘目录（按 builder 现有惯例在 `.build/rootfs/<lunch_target>/` 或类似），然后：

```bash
ROOTFS_DIR=$(find .build -type d -name 'rootfs*' | head -1)
find "$ROOTFS_DIR" -name 'goodix_911_cfg.bin' -ls
```
Expected: 命中 `lib/firmware/goodix_911_cfg.bin`，size = 186。

- [ ] **Step 6: 校验 extlinux.conf 含 fdtoverlays**

```bash
find .build -name extlinux.conf -exec grep -l 'hx8399a-gt911' {} \;
```
Expected: 至少一条 extlinux.conf 命中。

---

## Task 7: 实机点屏 + 触摸验收（需要硬件）

**Files:** 无（人工验收）

将 Task 6 产出的镜像刷到 OrangePi 5 Plus + 实际接 HX8399-A 屏 + GT911 触摸 + 通过 USB-Serial 连 UART2 console。

- [ ] **Step 1: 刷镜像**

```bash
flange flash --image .build/<image_path>
```
（具体参数按 builder/platforms/rockchip/flash.py 既有 CLI）

- [ ] **Step 2: 串口看 kernel boot 日志**

UART2 1500000 baud 连接。Expected：
- u-boot 阶段无 `FDT_ERR_BADOVERLAY`
- kernel 阶段无 `mipi_dsi_detach+0x14` NULL deref 指纹（spec §6 R2；若出现则补 cherry-pick 上游 `7977c539e9b1` 等价 patch）
- panel-simple probe 成功（`dmesg | grep -i panel-simple`），无 `failed to parse init sequence`

- [ ] **Step 3: 验 panel 出图**

```bash
ls /dev/dri/
# 期望见 card0 / card1 等
modetest -M rockchip | grep -A 5 'DSI'
# 期望见 1080x1920@60 mode
```

- [ ] **Step 4: 验 touch**

```bash
dmesg | grep -i goodix
# 期望见: Goodix-TS ...: firmware loaded; New device registered
ls /dev/input/event*
evtest /dev/input/eventN   # N = goodix-ts 对应设备
```
触摸面板，期望见 5 点 ABS_MT_POSITION_X/Y 事件，坐标 ∈ [0,1080] × [0,1920]。

- [ ] **Step 5: 双显回归（不在本 plan 关键路径但需验证）**

接 HDMI 同时启动；期望 HDMI 输出与 DSI 屏均工作。

- [ ] **Step 6: 把实机验收结果记到 wiki/log.md**

按 wiki/log.md 既有 `## [YYYY-MM-DD] sync | ...` 模式追加一条记录：通过/失败现象/调试过程/最终 commit hash。若发现 timing 需调整（spec §6 R4），把 dtso 中 `disp_timings` 改好、commit 进同一 PR。

---

## Self-Review

| Spec 章节/Requirement | Plan 任务 |
|---|---|
| §1 总览：board overlay 路径 | Task 3-5 |
| §2 dtso 内容（5 个 &label fragment） | Task 3 |
| §3 panel-init-sequence + display-timings | Task 3 + Task 3 Step 3 校验 |
| §4 GT911 cfg ASCII + bin + 文件命名 | Task 1 + Task 2 |
| §4.5 部署到 /lib/firmware/ | Task 2（实施期精化为 overlay/lib/firmware/）|
| §5 config.py 增量 | Task 4 |
| §6 R1 EOT_PACKET 兜底 | Task 3 dtso 不引用旧名（dtso 注释 + dsi,flags 行已落实）|
| §6 R3 init-sequence 字节校验 | Task 3 Step 3 |
| §6 验收 checklist | Task 6 + Task 7 |

**占位符扫描**：plan 中无 TBD/TODO/"implement later"。
- Task 6 Step 1 的 "default-debug" 名是 best-effort，若 lunch target 不存在 plan 已说明回退方式（`flange lunch list`），不算占位符
- Task 7 Step 1 的 `--image .build/<image_path>` 是 builder/platforms/rockchip/flash.py CLI 已知占位，与既有 board 实操 README 一致

**类型/名字一致性**：
- `goodix_911_cfg.bin` 在 Task 1/2/3/5 一致
- `rk3588-orangepi-5-plus-hx8399a-gt911.dtso` / `.dtbo` 在 Task 3/4/5/6 一致
- `panel-init-sequence` 字节总数 319 在 Task 3 Step 3 与 dtso 注释一致

无 issue 发现。
