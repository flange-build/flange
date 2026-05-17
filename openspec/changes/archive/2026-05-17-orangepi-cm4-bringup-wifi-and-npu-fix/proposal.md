## Why

`orangepi-cm4` board 当前的 lunch 目标（`orangepi-cm4-default-release`）刷出来后会在 NPU power domain ack 超时后触发 BSP `panic_on_set_idle`，根本起不到 rootfs；即便启动起来也连不上 WiFi（rootfs 没有 AP6256 固件、bcmdhd 的 `FW_AMPAK_PATH` 也没启用），并且 dtsi 硬编码的 `root=PARTUUID=614e0000-0000` 会覆盖 flange normal/recovery 双 extlinux label 切换。本 change 把这三类"开机即用"的基础阻断点一次性补齐，使该 board 默认无屏可稳定启动 + WiFi/BT 硬件就绪。

DSI 屏适配（实机用的 Waveshare CM4-DISP-BASE-5A 5" 屏走 Chipone ICN6211 桥芯片）在尝试推进过程中暴露了多层 BSP 缺陷（panel driver 错抄 RPi 模板 / ICN6211 driver 未编入 / `enable-gpios` 强约束 / dtso 根级节点必须 fragment-wrap 等），单 change 难以闭环，且尝试启用过 overlay 后实机不能正常启动。屏适配从本 change 撤回，留作未来单独 change 推进。

复用已有机制：`rootfs.+extra_firmware`、tspi-rk3566 已实战验证的 bcmdhd / bootargs kernel patch，以及 neons-core3566-nanob / rp-pro-rk3568-h 已采用的 rknpu / rknpu_mmu 禁用模式。

## What Changes

- `components/board/orangepi-cm4/config.py` 追加 `rootfs.+extra_firmware`：从 `radxa-pkg/radxa-firmware` 仓拉 AP6256 三件套 `brcm/fw_bcm43456c5_ag.bin`、`brcm/nvram_ap6256.txt`、`brcm/BCM4345C5.hcd` → `/lib/firmware/`。
- 新增三条 board 私有 kernel patch（与既有 RK 板同类，按 board 各自一份）：
  - `patches/kernel/0001-dts-orangepi-cm4-bootargs-fix.patch`：改 `rk3566-orangepi-cm4.dtsi` 的 `chosen.bootargs`，删 `root=PARTUUID=614e0000-0000`（避免覆盖 extlinux APPEND、断 normal/recovery 切换），加 `firmware_class.path=/lib/firmware`。
  - `patches/kernel/0002-bcmdhd-set-fw-ampak-path-brcm.patch`：启用 `drivers/net/wireless/rockchip_wlan/rkwifi/bcmdhd/Makefile` 中的 `DHDCFLAGS += -DFW_AMPAK_PATH="\"brcm\""`，让 bcmdhd 在 `fw_bcm43456c5_ag.bin` 前自动拼 `brcm/` 前缀。
  - `patches/kernel/0003-dts-orangepi-cm4-disable-rknpu.patch`：把 `rk3566-orangepi-cm4.dtsi` 中 `&rknpu` / `&rknpu_mmu` 改回 `status = "disabled"`，避免 NPU PD ack 超时触发 boot panic。
- 新增 spec `rockchip-orangepi-cm4`：锁定该板"NPU 不阻断启动、WiFi/BT 固件到位（AP6256 / BCM4345C5）、bcmdhd 与 extlinux 路径打通、base.dts 不被改动"的契约。

## 非目标

- 不动 `rk3566-orangepi-cm4-base.dts`（保持空壳）。
- **不做 DSI 屏适配**（dsi1 维持 dtsi 默认 disabled；ICN6211 driver / dtso / defconfig 启用 / DSI defer cleanup NULL deref 修复 等屏链路相关改动全部不在本轮范围，下次开 change 推进，见 `wiki/log.md` 中的踩坑记录）。
- 不引入 product / variant 维度（本轮只是补"开机即用"，不分裂 lunch 矩阵）。
- 不抽公共 patch 仓——tspi-rk3566 已定下"板 patch 各自一份"的现状，本轮不做跨板 patch 复用重构。
- 不预装 `bluez` / `bluetoothctl` 等 BT 用户态包——本轮 BT 仅做"硬件就绪 + 固件到位"，应用层栈由产品方自取。
- 不动 base bootargs 的 console / earlycon 设置（仅删 root= 与加 firmware_class.path 两处必要修改）。

## Capabilities

### New Capabilities

- `rockchip-orangepi-cm4`：固化 Orange Pi CM4 板的"无屏可启动 + WiFi/BT 硬件就绪"契约——NPU 不阻断启动、AP6256 三件套到位、bcmdhd 路径打通、extlinux 双 label 切换不被 dtsi 覆盖、base.dts 保持空壳；与 `amlogic-platform`、`allwinnera733-platform` 中的板级 requirement 风格对齐，是 Rockchip 平台下首个 board 级 spec。

### Modified Capabilities

无。

## Impact

- **新增文件**：
  - `components/board/orangepi-cm4/patches/kernel/0001-dts-orangepi-cm4-bootargs-fix.patch`
  - `components/board/orangepi-cm4/patches/kernel/0002-bcmdhd-set-fw-ampak-path-brcm.patch`
  - `components/board/orangepi-cm4/patches/kernel/0003-dts-orangepi-cm4-disable-rknpu.patch`
  - `openspec/specs/rockchip-orangepi-cm4/spec.md`（由本 change 归档时落地）
- **修改文件**：
  - `components/board/orangepi-cm4/config.py`（追加 `rootfs.+extra_firmware`、重写 docstring 反映"无屏适配"边界）
  - `wiki/boards/orangepi-cm4.md`（写实差异点 + 屏适配踩坑指针）
  - `wiki/log.md`（一条 sync 条目）
- **不动**：所有 `builder/` 代码、其它 board / SoC / platform 配置、其它 spec 文件、rockchip 平台层 boot.py / kernel.py。
- **运行时影响**：刷写后首启不再因 NPU PD ack 超时 panic；`ip link` 出现 `wlan0`、`hciconfig` 出现 `hci0`；`/lib/firmware/brcm/` 含三件套；`recoveryctl reboot recovery` 双 label 切换可用。无 DSI 屏显示（dsi1 disabled），HDMI 出图链路不受影响。
- **构建影响**：kernel patch 触发 orangepi-cm4 板 kernel 内容哈希变化，首次构建会重编 kernel；extra_firmware 走 SourceManager 独立 clone 与 rootfs 组装，命中后续构建 cache。
