---
title: amlogic 平台
type: platform
status: wip
sources:
  - builder/platforms/amlogic/__init__.py
  - builder/platforms/amlogic/kernel.py
  - builder/platforms/amlogic/bootloader.py
  - builder/platforms/amlogic/rootfs.py
  - builder/platforms/amlogic/boot.py
  - builder/platforms/amlogic/recovery.py
  - builder/platforms/amlogic/image.py
  - components/platform/amlogic/config.py
  - components/platform/amlogic/s905d3/config.py
  - openspec/changes/add-amlogic-khadas-vim3l/design.md
related:
  - "[[khadas-vim3l]]"
  - "[[bootloader 构建器]]"
  - "[[USB 线刷协议]]"
  - "[[FlashStrategy 抽象]]"
updated: 2026-05-10
---

## TL;DR

Amlogic 平台（vendor-wide，对标 [[rockchip 平台]]，区别于 family-narrow 的 [[allwinnera733 平台]]）；status: wip。当前 SoC 范围仅 s905d3（SM1 family），首板 [[khadas-vim3l]]。引导链与刷写工具是三家平台中最厚的：**FIP 多 blob 拼装** + **eMMC hw boot0 分区写入** + **pyamlboot/fastboot 两段式刷写**。

## 关键设计要点

**策略类布局（`builder/platforms/amlogic/`）**

与 Rockchip / Allwinner 同形：6 个策略文件（`kernel.py` / `bootloader.py` / `rootfs.py` / `boot.py` / `recovery.py` / `image.py`）+ `__init__.py:create_builder()` 工厂分发。`recovery.py` 直接 3 行 shim 复用 `RecoveryBuilder`。`ARTIFACT_NAMES` 9 个 entry，bootloader 含 `fip` / `usb_bl2` / `usb_tpl` 三个产物名。

**vendor-wide 命名**

`amlogic/` + SoC 子目录 `s905d3/`，而非 family-narrow 的 `amlogicsm1/`。理由：Amlogic 各 family（G12A / SM1 / SC2）的 FIP 流程顶层一致，靠 SoC config 注入 `fip_tool` / `fip_family_inc` 两个字段即可切换 family；后续若加 S905X4 (SC2) / A311D2 (T7) 仅需加 SoC 子目录（详见 design Decision 1 / 8）。

**FIP 打包链路**

mainline u-boot 不含 SoC 厂商私有 blob（与 Rockchip 同样情况），blob 由 SoC 层 `repos.amlogic-boot-fip` 独立声明，bootloader builder 在 u-boot 编完后调外挂工具拼装：

```
u-boot 源码 (mainline v2024.10)
  │ make ARCH=arm64 CROSS_COMPILE=... <defconfig fragments 合并>
  │ make
  ▼
u-boot.bin (proper)
  │ ./build-fip.sh <board_dir> u-boot.bin out/   (LibreELEC 官方脚本)
  │   ├─ BL2 SIG / BL30+BL301 拼接 (blx_fix.sh) / BL3X 加密
  │   ├─ DDR fw 嵌入 (ddr3_1d / ddr4_1d/2d / lpddr3_1d / lpddr4_1d/2d / piei)
  │   └─ FIP 封装
  ▼
out/u-boot.bin  (FIP 已封装但还不是 SD 可启动镜像)
  │ aml_encrypt_g12a --bootsd --infile out/u-boot.bin --output out/u-boot.bin.sd.bin
  ▼
out/u-boot.bin.sd.bin   (SD/eMMC 可启动)
  │ 可选 aml_encrypt_g12a --bootusb ...
  ▼
out/u-boot.bin.usb.bl2 + out/u-boot.bin.usb.tpl   (pyamlboot USB 推送用)
```

**fip blobs 与工具来源**

`LibreELEC/amlogic-boot-fip @ master`，被 LibreELEC / CoreELEC / Armbian 共用，MIT/GPL 兼容。仓库**按 board 而非 family 分目录**（`khadas-vim3l/` / `aml-s905d3-cc/` / `khadas-vim3/` / ...），每个 board 目录独立完整 blob 集 + `aml_encrypt_<family>` 工具 + `Makefile`（`include ../<family>.inc`）。SM1 family 实际**复用 G12A 工具链**（同代加密协议 v3，工具名为 `aml_encrypt_g12a`）。

**字段分层**：

- SoC 层：`bootloader.fip_family_inc = "g12a.inc"` + `bootloader.fip_tool = "aml_encrypt_g12a"`
- board 层：`bootloader.fip_board_dir = "khadas-vim3l"`（board 子目录名）

**与其他平台的关键差异**

| 维度 | Rockchip | A733 | **Amlogic** |
|---|---|---|---|
| 第一阶段 blob | `idbloader.img`（rkbin DDR + miniloader） | `boot0_*.bin`（eGON header） | `bl2.bin` + `bl30/bl301`（SCP） + `bl31.img`（TF-A） + DDR fw |
| 拼装工具 | `mkimage -T rksd -n <chip>` | `boot_package_create.py` | `build-fip.sh` + `aml_encrypt_g12a` |
| 写入位置 | LBA 64 of user area | offset 16 KiB of user area | **eMMC hw boot0 分区 offset 0x200** |
| 主刷写工具 | `upgrade_tool` | 当前 `dd`，FEL 待实现 | `pyamlboot` + `fastboot` |

Amlogic 把 BootROM 入口完全放进 hw boot0 分区，user area 仅承载内容分区（`boot` / `recovery` / `rootfs`）；与 Rockchip / Allwinner 都把 bootloader 放 user area 形成对照。详见 design Decision 4。

**AmlogicFlashStrategy 两段式 + 自动化路径**

```
pre_flash:
  - device.mode == "maskrom": 调 boot-g12.py 推裸 FIP u-boot.bin 到 DDR
                              u-boot 板级 init setenv boot_source=usb
                              PREBOOT 检 boot_source → 自动 fastboot usb 0
  - device.mode == "fastboot": SKIP（u-boot 已在 DDR 跑着，省 pyamlboot 推送）

flash 主流程 (host fastboot 写各分区):
  fastboot oem format       → u-boot gpt write，按 mmc2 实际容量重建 GPT
  fastboot flash bootloader → eMMC hw boot0 (mmc2 boot0) offset 0x200
  fastboot flash boot       → GPT boot 分区
  fastboot flash rootfs     → GPT rootfs 分区
  fastboot reboot
```

**全自动化关键**：mainline u-boot `arch/arm/mach-meson/board-common.c:meson_set_boot_source()` 在 `board_late_init` 已暴露 `${boot_source}` env，板级 fragment `flange_fastboot.config` 的 `CONFIG_PREBOOT` 据此条件进 fastboot —— USB MaskROM 加载触发，eMMC 冷启动不触发，**无需用户接串口手动 `fastboot usb 0`**。

USB vid/pid `1b8e:c003`（MaskROM），host 端依赖 `pip install pyamlboot` + `apt install android-tools-fastboot`（macOS 还需 `brew install libusb`）。详见 design Decision 5 + `wiki/boards/khadas-vim3l.md` 的"重刷工作流"段。

**为何不用 Khadas 下游 u-boot**

Khadas `khadas/u-boot` 历史含 multi-boot button + Android-style 启动逻辑（固定 bootargs），易复刻 RK3588 板级 defconfig 绕 extlinux 的坑（详见 [[radxa-rock5b]] BSP 分支差异）。mainline `khadas-vim3l_defconfig`（自 v2019.10 起）走标准 Generic Distro Boot（extlinux.conf），与 flange 全平台 boot 入口约定完全对齐。详见 design Decision 2。

## 易踩坑

- mainline `khadas-vim3l_defconfig` v2024.10 **不默认开 fastboot**：仅有 `CONFIG_USB_GADGET=y` + `CONFIG_USB_GADGET_DOWNLOAD=y` + Amlogic ADNL VID/PID（0x1b8e:0xfada）+ `CONFIG_CMD_DFU=y`。需在 SoC 层挂 `flange-fastboot.config` fragment 启 `CONFIG_USB_FUNCTION_FASTBOOT=y` / `CONFIG_FASTBOOT=y` / `CONFIG_FASTBOOT_FLASH_MMC_DEV=1` / `CONFIG_FASTBOOT_GPT_NAME="gpt"`，与 a733 的 defconfig+`bsp_defconfig`+...config 合并机制同形
- `aml_encrypt_sm1` **不存在**：仓库 board-organized，工具实际名 `aml_encrypt_g12a`（SM1 复用 G12A 工具链），位于 `<board_dir>/aml_encrypt_g12a`。design 早期版本的 `aml_encrypt_sm1` 是误判，已修正
- LibreELEC/amlogic-boot-fip 内的 `aml_encrypt_g12a` 是 **x86_64 二进制**，非 x86_64 host / ARM Docker 容器内不能跑；flange 构建已要求 x86_64 host（envsetup.sh），ARM host 暂不支持
- **fastboot reboot 之前必须松开 KEY1**，否则板会反复回到 MaskROM；`flange flash` CLI 提示语带此一行
- BootROM 默认从 eMMC 启动，但若用户测试时把 SD 卡插上会优先尝试 SD（影响刷写后启动验证），刷写后拔 SD
