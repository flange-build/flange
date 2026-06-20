---
title: radxa-rock-4d
type: board
status: wip
sources:
  - components/board/radxa-rock-4d/config.py
  - components/platform/rockchip/rk3576/config.py
  - builder/platforms/rockchip/image.py
  - builder/flash.py
related:
  - "[[rockchip 平台]]"
  - "[[lunch-build-flash 流程]]"
  - "[[新增板级支持]]"
updated: 2026-06-19
---

## TL;DR

Radxa ROCK 4D，RK3576 SoC（4×A72 + 4×A53，Mali-G52），项目首块 RK3576 适配板，
也是 Rockchip 平台首次落地 **UFS 存储（4096 字节逻辑块）**。目标：UFS 启动 +
UART0 串口 + SSH + AIC8800D80 USB WiFi/BT。HDMI / NPU / VPU / eMMC/SD 不在首版范围。

## product / variant

继承平台默认：`products: [default]`，`variants: [debug, release]`。
lunch target：`radxa-rock-4d-default-debug` / `radxa-rock-4d-default-release`。

## 关键配置

| 维度 | 取值 | 说明 |
|---|---|---|
| SoC | rk3576 | 复用 SoC 层 `rk3576/config.py`（内核 rkr5.1 + panfrost） |
| dts | `rk3576-rock-4d` | rkr5.1 树内已含，`&ufs status="okay"` + reset-gpio |
| bootloader.defconfig | `rock-4d-rk3576_defconfig` | **board 层覆盖** SoC 通用 `rk3576_defconfig`；后者不开 UFS |
| 存储 | UFS，`sector_size=4096` | board 层整块覆盖 `partitions`；SoC 层保持 512B eMMC 默认 |
| 串口 | UART0 1500000bps | 沿用 SoC 层 `console=ttyS0,1500000` |
| WiFi/BT | AIC8800D80 USB | radxa-pkg/aic8800 OOT（`aic_load_fw`+`aic8800_fdrv`+`aic_btusb`），固件 `/lib/firmware/aic8800D80/`，与 rock5c-lite 同源 |
| root 口令 | 1234 | 开发期调试便利，与其他 rockchip bring-up 板一致 |

## UFS 4096 字节扇区是怎么打通的

内核侧零改动（rkr5.1 已自带 rk3576-rock-4d.dts + `rockchip,rk3576-ufs` 驱动 +
defconfig 已开 `CONFIG_SCSI_UFSHCD/_PLATFORM/SCSI_UFS_ROCKCHIP`）。框架侧两处
按 `partitions.sector_size` 参数化（缺省 512，现有 eMMC/SD 板零影响）：

- `builder/platforms/rockchip/image.py`：4K 路径走 `losetup -b 4096` + parted 写
  4K 对齐 GPT（参照 qcs6490），config 的 512B 单位 offset/size 按
  `off_512 × 512 ÷ 4096` 重算；rootfs Type-UUID 伪装成 EFI System GUID
  `C12A7328-…`（4K rk35xx bootloader quirk，Armbian 实证）。
- `builder/flash.py`：`FlashConfig.sector_size` + `RockchipFlashStrategy.write_gpt`
  的 `_gpt_slice(sector)` 按扇区截取 primary GPT（header + 16KiB entries array）。

rkbin 无 UFS 专用 loader，通用 RK3576 loader/SPL/usbplug 内含 UFS 初始化，
`bootloader.py` 无须改。

## ⚠️ 上板实测 open risk（固件构建后回填）

以下三点公开资料无定论，须用 ROCK 4D 实板 + UFS 模组实测校准（详见变更
`add-rk3576-radxa-rock-4d-ufs` 的 design.md）：

1. **`upgrade_tool WL <offset>` 在 4096B UFS 上的 offset 单位**（512 扇区 vs 4K
   LBA / 是否自适应查询 LBA 大小）——决定 `write_gpt` 4K 截取与 idbloader/uboot
   落位是否正确。首版按 "WL offset 即设备 LBA" + "保持字节偏移" 假设落地。
2. **maskrom + `rk3576_usbplug` 经 USB 写 UFS 是否真能成功**（无公开成功先例）。
   若失败，回退 SD 启动后 `dd /dev/sda`（另起变更引入 `flash_whole_disk`）。
3. **4096B + rootfs EFI Type-UUID 的 raw.img 板上 GPT 能否被 BootROM/U-Boot/内核
   正确识别**，以及 idbloader/uboot 是否需改用 Rockchip "LBA 64 / 16384 恒定"
   约定（即 config offset 改 `0x200` / `0x20000`）。

## 验收路径

1. `flange build radxa-rock-4d-default-debug` → 产出 4096B `raw.img`
2. maskrom → `flange flash radxa-rock-4d-default-debug`
3. 串口（UART0）观察 U-Boot 枚举 UFS + kernel banner
4. 内核挂载 UFS rootfs → systemd → sshd 登录
