## Why

flange 目前只支持 Rockchip 与 Allwinner A733 两个 SoC 阵营，缺少 Amlogic 平台支撑。Amlogic S905D3（SM1 family，Cortex-A55 quad-core，Mali-G31 MP2）是 Khadas VIM3L 这块工程板的主控，主线 u-boot 自 v2019.10 起就支持 `khadas-vim3l_defconfig`，主线 kernel 自 5.10 起就有 `meson-sm1-khadas-vim3l.dts`，是引入 Amlogic 平台风险最小的首板。本变更新开 `amlogic` 平台、`s905d3` SoC、`khadas-vim3l` 第一板，并打通 Amlogic 特有的 USB Burning 刷写链路（pyamlboot → fastboot 两段式）。

## What Changes

- **新增 `amlogic` 平台模块** `builder/platforms/amlogic/`：与 `rockchip` / `allwinnera733` 同形，提供 `kernel.py` / `bootloader.py` / `boot.py` / `rootfs.py` / `recovery.py` / `image.py` 与 `__init__.py`（含 `ARTIFACT_NAMES` 与 `create_builder`）。`bootloader.py` 实现 Amlogic 特有的 FIP 打包流程：mainline u-boot 编译产出 `u-boot.bin` 后，调 `aml_encrypt_sm1` 把 `bl2.bin` / `bl30.bin` / `bl301.bin` / `bl31.img` / DDR 固件与 u-boot proper 拼装成 `u-boot.bin.sd.bin`。
- **新增 `amlogic` 平台数据层** `components/platform/amlogic/`：`config.py`（PLATFORM）+ `patches/` 跨 SoC patch + `s905d3/config.py`（SOC，含 mainline u-boot/kernel 仓库声明、`fip_blobs` 仓库声明、`fip_tool="aml_encrypt_sm1"`、`boot.kernel_args="earlycon console=ttyAML0,115200n8"`、`partitions.entries`）。
- **新增 SoC 目录命名约定**：amlogic 平台 SoC 子目录用具体型号名（`s905d3`），与 `rk3566` / `rk3588` 风格一致；不用 family code（`sm1`）。
- **新增 `khadas-vim3l` board** `components/board/khadas-vim3l/`：`config.py`（BOARD：soc=s905d3、`kernel.dts="meson-sm1-khadas-vim3l"`、Wi-Fi/BT 固件 `+extra_firmware`）+ `overlay/etc/{hostname,...}` + `overlay/etc/systemd/system/bluetooth-vim3l.service`（btattach 启动 BCM4359）。
- **新增 `AmlogicFlashStrategy`**：`builder/flash.py` 添加新策略类并注册到 `_FLASH_STRATEGIES["amlogic"]`。两段式：`pre_flash` 调 `pyamlboot` 把 u-boot 推到 SoC DDR；`flash` 主流程通过 host 端 `fastboot` 写入 `bootloader` / `boot` / `recovery` / `rootfs` 各分区，然后 `fastboot reboot`。
- **eMMC 布局采用 boot0 hw 分区模式**：u-boot.bin.sd.bin 写入 eMMC 硬件 boot0 分区（offset 0x200），user area 走 GPT，含 `env` / `boot` / `recovery` / `rootfs` 四个分区，rootfs 启用 `grow_on_first_boot`。
- **Wi-Fi/BT 一并适配**：board config 的 `rootfs.+extra_firmware` 声明 `brcmfmac4359-sdio.bin` / `BCM4359C0.hcd` / `brcmfmac4359-sdio.amlogic,sm1.txt` 三件套，分别从 `LibreELEC/wlan-firmware` 与 Khadas fenix NVRAM 拉取；驱动走 mainline in-tree `brcmfmac` + `hci_uart`，不走 OOT。
- **新增 host 端依赖**：`pyamlboot`（pip 或 git）、`android-tools-fastboot`（Ubuntu 包）。两者均 mainline-friendly，不引入 vendor binary。
- **新增 wiki 条目** `wiki/boards/khadas-vim3l.md` 与 `wiki/boards/index.md` 索引项。

## Capabilities

### New Capabilities
- `amlogic-platform`: Amlogic 平台级构建契约的权威规范，对标 `rockchip-platform` / `allwinnera733-platform`。本变更首次创建该 capability，初始范围聚焦于 amlogic 平台的 SoC 自动发现、FIP 打包流程（mainline u-boot + LibreELEC 预构建 fip blobs + `aml_encrypt_sm1`）、s905d3 SoC 配置、khadas-vim3l 板级最小启动链路（串口 + SSH + Wi-Fi + BT）。
- `amlogic-flash`: Amlogic 平台 USB Burning 刷写契约。规定 `AmlogicFlashStrategy` 在 pre_flash 阶段用 `pyamlboot` 把 u-boot 推到 SoC DDR；正式 flash 阶段通过 host 端 `fastboot` 写入各 GPT 分区与 eMMC boot0 hw 分区。

### Modified Capabilities
（无 — 本变更不修改现有 spec 的 requirement，仅新增两个 capability。`platform-abstraction` 中"自动发现平台"与"FlashStrategy 接口"的现有 requirement 已能覆盖 amlogic 平台的注入，无须修改。）

## Impact

- **代码层**：
  - `builder/platforms/amlogic/` — 新增模块，6 个 builder 文件 + `__init__.py`。
  - `builder/flash.py` — 新增 `AmlogicFlashStrategy` 类，约 80~120 行；`_FLASH_STRATEGIES` 注册一项。
- **内容层**：
  - `components/platform/amlogic/{config.py, patches/, s905d3/{config.py, patches/}}` — 全新目录树。
  - `components/board/khadas-vim3l/{config.py, overlay/, dtso/}` — 全新板目录。
- **外部依赖**（已核实）：
  - `u-boot/u-boot @ v2024.10`（mainline，含 `khadas-vim3l_defconfig`）。
  - `LibreELEC/amlogic-boot-fip`（含 `sm1/` 子目录的 bl2/bl30/bl301/bl31/DDR fw + `aml_encrypt_sm1` 工具，MIT/GPL 兼容）。
  - mainline kernel 6.12 LTS（含 `arch/arm64/boot/dts/amlogic/meson-sm1-khadas-vim3l.dts`，支持到 2030 年）。
  - `LibreELEC/wlan-firmware` 含 `brcm/brcmfmac4359-sdio.bin` 与 `brcm/BCM4359C0.hcd`。
  - `khadas/fenix` 含 `khadas-vim3l` 板级 NVRAM（`brcmfmac4359-sdio.amlogic,sm1.txt`）。
- **host 端依赖**：
  - `pyamlboot`（pip 安装或 git submodule，MIT）—— 推 u-boot 到 MaskROM。
  - `android-tools-fastboot`（Ubuntu apt 包）—— 写各 GPT/boot0 分区。
- **回归范围**：本变更纯增量，不触动现有平台。Rockchip 与 Allwinner A733 的所有 board 不需要回归（无共享代码改动）。
- **Flash 工具链**：`builder/flash.py` 仅新增策略类，现有 `RockchipFlashStrategy` / `AllwinnerA733FlashStrategy` 不变。
- **下游兼容**：lunch target `khadas-vim3l-default-debug` / `khadas-vim3l-default-release` 通过现有 product/variant 机制自动派生，不需 CLI 改动。

## Non-Goals

- **不**启用 GPU (Mali-G31 MP2)：mainline panfrost 驱动支持 G31，但首版聚焦串口 + SSH 链路，GPU 单独成独立变更。
- **不**启用 HDMI 输出 / 显示输出：`meson_drm` 主线驱动支持，但需要额外 `+extra_packages`（`mesa-utils` / `weston` 等），扩大首版风险面。
- **不**启用 VPU 硬解（amvdec）/ NPU：超出"工程验证"首版范围。
- **不**做"全源构建" TF-A：BL31 直接用 LibreELEC 预构建的 `bl31.img`，避免引入 TF-A 仓库与 Amlogic plat patch 链。后续可起独立变更切到 TF-A 上游 `plat/amlogic/g12a`（覆盖 SM1）。
- **不**做 SD 卡启动模式：首版仅 eMMC + USB Burning。SD 启动（user area offset 512 写 u-boot.bin.sd.bin + GPT）作为 future variant。
- **不**做 USB OTG gadget 模式（mass storage / serial）：VIM3L USB-C 在 MaskROM 与刷写时被 host 占用，启动后留给标准 USB host。
- **不**重构现有 `platform-abstraction` / `engine.py` / `config/registry.py` / `config/merge.py`：现有抽象足够承载 amlogic 平台的所有需求，不引入家族中间层。
- **不**适配 S905D3 之外的 SM1/SC2 SoC（S905X3 / S905X4 / A311D2）：本变更仅建立 amlogic 平台 + s905d3 单 SoC，其他 SoC 待真实板适配时再起独立变更。
- **不**支持 PCIe（VIM3L 板上 PCIe 通过 M.2 E-key 暴露，主要用于 Wi-Fi/BT —— VIM3L 的 AP6398S 走 SDIO 不走 PCIe）。
- **不**做 GPIO/I²C/SPI 的板上扩展（GPIO header / mipi-csi 相机）：板载默认外设不在首版交付，后续独立变更。
