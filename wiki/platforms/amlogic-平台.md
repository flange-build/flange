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
  - builder/flash/plan.py
  - builder/flash/strategy.py
  - components/platform/amlogic/config.jsonnet
  - components/platform/amlogic/a311d/config.jsonnet
  - components/platform/amlogic/s905d3/config.jsonnet
  - components/platform/amlogic/s905y2/config.jsonnet
  - components/config/khadas-vim3-common.libsonnet
  - components/board/khadas-vim3/config.jsonnet
  - components/board/khadas-vim3/patches/bootloader/flange_fastboot.config
  - components/board/khadas-vim3l/config.jsonnet
  - components/platform/amlogic/s905d3/patches/bootloader/flange_fastboot.config
  - openspec/specs/amlogic-flash/spec.md
  - openspec/changes/archive/2026-09-05-add-a311d-khadas-vim3/design.md
  - openspec/changes/archive/2026-05-15-add-amlogic-khadas-vim3l/design.md
  - docs/development-guide.md
  - docs/extension-guide.md
related:
  - "[[khadas-vim3]]"
  - "[[khadas-vim3l]]"
  - "[[bootloader 构建器]]"
  - "[[USB 线刷协议]]"
  - "[[FlashStrategy 抽象]]"
updated: 2026-09-05
---

> 阅读前提：先读[架构总览](../concepts/架构总览.md)，并从[板卡索引](../boards/index.md)确认型号。
> 本页保留平台机制与历史适配记录；芯片支持、产物可构建和实机验收是不同边界。
> 当前操作见[开发指南](../../docs/development-guide.md)，扩展步骤见[扩展指南](../../docs/extension-guide.md)。

## TL;DR

Amlogic 平台（vendor-wide，对标 [[rockchip 平台]]，区别于 family-narrow 的 [[allwinnera733 平台]]）；status: wip。当前覆盖 S905Y2/G12A、A311D/G12B 与 S905D3/SM1，板卡包括 [[radxa-zero]]、[[khadas-vim3]] 和 [[khadas-vim3l]]。引导链统一复用 **FIP（Firmware Image Package，固件镜像包）多 blob 拼装** + **eMMC hw boot0 分区写入** + **pyamlboot/fastboot（快速刷写协议）两段式刷写**。

## 关键设计要点

**策略类布局（`builder/platforms/amlogic/`）**

与 Rockchip / Allwinner 同形：6 个策略文件（`kernel.py` / `bootloader.py` / `rootfs.py` / `boot.py` / `recovery.py` / `image.py`）+ `__init__.py:create_builder()` 工厂分发。`recovery.py` 直接 3 行 shim 复用 `RecoveryBuilder`。`ARTIFACT_NAMES` 有 10 个 entry，bootloader 含 `fip` / `sd` / `usb_bl2` / `usb_tpl` 四个产物名。

**vendor-wide 命名**

`amlogic/` 下使用具体型号 SoC 子目录（`s905y2/`、`a311d/`、`s905d3/`），不用 family code。Amlogic 各 family 的 FIP 流程顶层一致；SoC config 的 `fip_tool` 记录 G12A/G12B 工具身份，board config 的 `fip_board_dir` 选择实际 Makefile 与专属 blob。

**FIP 打包链路**

mainline u-boot 不含 SoC 厂商私有 blob（与 Rockchip 同样情况），blob 由 SoC 层 `sources.amlogic-boot-fip` 声明、bootloader 通过 source 引用复用，builder 在 u-boot 编完后调外挂工具拼装：

```
u-boot 源码 (mainline v2024.10)
  │ make ARCH=arm CROSS_COMPILE=... <defconfig fragments 合并>
  │ make
  ▼
u-boot.bin (proper)
  │ ./build-fip.sh <board_dir> u-boot.bin out/   (LibreELEC 官方脚本)
  │   ├─ BL2 SIG / BL30+BL301 拼接 (blx_fix.sh) / BL3X 加密
  │   ├─ DDR fw 嵌入 (ddr3_1d / ddr4_1d/2d / lpddr3_1d / lpddr4_1d/2d / piei)
  │   └─ aml_encrypt_<family> --bootmk 一次生成全部格式
  ▼
out/u-boot.bin             (裸 FIP，pyamlboot 推送用)
out/u-boot.bin.sd.bin      (SD/eMMC 可启动)
out/u-boot.bin.usb.bl2     (旧式 USB BL2)
out/u-boot.bin.usb.tpl     (旧式 USB TPL)
```

**fip blobs 与工具来源**

`LibreELEC/amlogic-boot-fip @ master` 按 board 而非 family 分目录，每个目录带独立 blob 和工具。VIM3L/SM1 使用 `khadas-vim3l/aml_encrypt_g12a`；VIM3/A311D 使用 `khadas-vim3/aml_encrypt_g12b`，两者 blob 不可互换。

**字段分层**：

- SoC 层：`bootloader.fip_tool` 记录预期 family 工具（S905D3/S905Y2 为 `aml_encrypt_g12a`，A311D 为 `aml_encrypt_g12b`）；实际调用由 board Makefile 完成
- board 层：`bootloader.fip_board_dir`（如 `khadas-vim3l` / `khadas-vim3`）

**与其他平台的关键差异**

| 维度 | Rockchip | A733 | **Amlogic** |
|---|---|---|---|
| 第一阶段 blob | `idbloader.img`（rkbin DDR + miniloader） | `boot0_*.bin`（eGON header） | `bl2.bin` + `bl30/bl301`（SCP） + `bl31.img`（TF-A） + DDR fw |
| 拼装工具 | `mkimage -T rksd -n <chip>` | `boot_package_create.py` | `build-fip.sh` + `aml_encrypt_<family>` |
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

Khadas `khadas/u-boot` 历史含 multi-boot button + Android-style 启动逻辑（固定 bootargs），易复刻 RK3588 板级 defconfig 绕 extlinux 的坑（详见 [[radxa-rock5b]] BSP 分支差异）。mainline `khadas-vim3_defconfig` / `khadas-vim3l_defconfig` 走标准 Generic Distro Boot（extlinux.conf），与 flange 全平台 boot 入口约定对齐。

## 易踩坑

- mainline VIM3/VIM3L defconfig v2024.10 **不默认开 fastboot**。需叠加 `flange_fastboot.config` 启用 gadget、GPT 与 `CONFIG_FASTBOOT_FLASH_MMC_DEV=2`；VIM3 的 fragment 位于 board 层，因为 mmc 编号是板级存储拓扑。
- VIM3 必须使用 `aml_encrypt_g12b`；VIM3L/SM1 才使用 `aml_encrypt_g12a`。
- `build-fip.sh` 的 `--bootmk` 已生成四件产物；不得再调用 G12A 私有的 `--bootsd` / `--bootusb` 形式，G12B 工具不支持这组参数。
- `aml_encrypt_sm1` **不存在**：仓库 board-organized，工具实际名 `aml_encrypt_g12a`（SM1 复用 G12A 工具链），位于 `<board_dir>/aml_encrypt_g12a`。design 早期版本的 `aml_encrypt_sm1` 是误判，已修正
- LibreELEC/amlogic-boot-fip 内的 `aml_encrypt_g12a` 是 **x86_64 二进制**，非 x86_64 host / ARM Docker 容器内不能跑；当前构建镜像使用 `linux/amd64`；ARM 宿主需 Docker 提供相应执行支持，不能直接在 ARM 容器执行此二进制。宿主准备见[开发指南](../../docs/development-guide.md)
- 若使用“按住按键”方式进 MaskROM，推送后必须松开按键；VIM3/VIM3L 推荐的 TST 流程是在两秒内按 Function 三次后立即松开。
- BootROM 默认从 eMMC 启动，但若用户测试时把 SD 卡插上会优先尝试 SD（影响刷写后启动验证），刷写后拔 SD
