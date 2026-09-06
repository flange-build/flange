## MODIFIED Requirements

### Requirement: amlogic bootloader 构建走 FIP 打包流程

`builder/platforms/amlogic/bootloader.py` 的 ComponentBuilder 必须（SHALL）使用 Amlogic 板级工具打包 FIP（Firmware Image Package，固件镜像包）。
在 mainline U-Boot 编译产出 `u-boot.bin` 后，必须通过 `amlogic-boot-fip` source 内的
`build-fip.sh <board_dir> <u-boot.bin> <out>` 调用 board Makefile；该 Makefile 必须使用 board-local
`aml_encrypt_* --bootmk` 一次生成 `u-boot.bin`、`u-boot.bin.sd.bin` 和 USB BL2/TPL，builder 不得重复调用
family-specific 二次派生接口。
`<board_dir>` 必须从 `bootloader.fip_board_dir` 读取，FIP source 必须通过顶层
`sources.amlogic-boot-fip` 获取，工具不得（MUST NOT）从 host `$PATH` 查找。

#### Scenario: VIM3L 使用 G12A FIP 工具

- **WHEN** 构建 khadas-vim3l 的 bootloader 组件
- **THEN** 调用 `build-fip.sh khadas-vim3l <u-boot.bin> <out>`
- **AND** board Makefile 使用 `<amlogic-boot-fip_src>/khadas-vim3l/aml_encrypt_g12a --bootmk`
- **AND** `target/bootloader/u-boot.bin.sd.bin` 存在

#### Scenario: VIM3 使用 G12B FIP 工具

- **WHEN** 构建 khadas-vim3 的 bootloader 组件
- **THEN** 调用 `build-fip.sh khadas-vim3 <u-boot.bin> <out>`
- **AND** board Makefile 使用 `<amlogic-boot-fip_src>/khadas-vim3/aml_encrypt_g12b --bootmk`
- **AND** `target/bootloader/u-boot.bin.sd.bin` 存在

#### Scenario: board 粒度 FIP 子目录与 SoC 粒度工具

- **WHEN** 加载任意 Amlogic board 的完整合并配置
- **THEN** `bootloader.fip_board_dir` 由 board 层声明
- **AND** `bootloader.fip_tool` 由 SoC 层声明

### Requirement: amlogic 平台产物映射

`builder/platforms/amlogic/__init__.py` 的 `ARTIFACT_NAMES` 字典必须（SHALL）声明 kernel、bootloader、boot、
rootfs、recovery 与 image 的 canonical 产物映射。bootloader 必须分别保留裸 FIP、SD/eMMC 和两段 USB
产物，禁止把不同格式折叠到同一个 key。

| (component, key) | 目标文件名 |
|---|---|
| (kernel, dtbos) | overlay |
| (kernel, modules) | modules |
| (bootloader, fip) | u-boot.bin |
| (bootloader, sd) | u-boot.bin.sd.bin |
| (bootloader, usb_bl2) | u-boot.bin.usb.bl2 |
| (bootloader, usb_tpl) | u-boot.bin.usb.tpl |
| (boot, boot) | boot.img |
| (rootfs, rootfs) | rootfs.img |
| (recovery, recovery) | recovery.img |
| (image, image) | raw.img |

#### Scenario: bootloader 四件产物分别落地

- **WHEN** 构建任意受支持 Amlogic board 的 bootloader
- **THEN** `target/bootloader/u-boot.bin` 是 pyamlboot 使用的裸 FIP
- **AND** `target/bootloader/u-boot.bin.sd.bin` 是写入 eMMC boot0 的 SD 格式
- **AND** USB BL2/TPL 分别落为 `u-boot.bin.usb.bl2` 与 `u-boot.bin.usb.tpl`

## ADDED Requirements

### Requirement: a311d SoC 配置完整声明

`components/platform/amlogic/a311d/config.jsonnet` 必须（SHALL）声明 A311D/G12B 的 canonical SoC 配置，
至少包含 identity、三个 source descriptor、bootloader source/FIP tool、kernel source/defconfig/config/Device Tree
目录与启动参数。A311D 必须（MUST）作为独立 SoC 被发现，不得冒用 `s905d3` identity；板载存储分区不得下沉
到 SoC 层。

#### Scenario: 自动发现 a311d SoC

- **WHEN** `_load_soc_config("a311d")` 被调用
- **THEN** 返回配置的 `platform == "amlogic"` 且 `soc == "a311d"`
- **AND** `architecture.userspace == "aarch64"`

#### Scenario: A311D 使用正确的主线源码和 G12B 工具

- **WHEN** 加载 A311D SoC 配置
- **THEN** U-Boot source 为 `https://github.com/u-boot/u-boot.git` 的 `v2024.10`
- **AND** Linux source 为 `https://github.com/torvalds/linux.git` 的 `v6.12`
- **AND** `bootloader.fip_tool == "aml_encrypt_g12b"`
- **AND** `kernel.device_tree.directory == "amlogic"`

#### Scenario: A311D 保持 Amlogic 通用启动输入

- **WHEN** 加载 A311D SoC 配置
- **THEN** `kernel.defconfig == ["defconfig"]`
- **AND** `kernel.config.CONFIG_DRM_GUD == "y"`
- **AND** `boot.kernel_args` 包含 `earlycon` 与 `console=ttyAML0,115200n8`

### Requirement: khadas-vim3 板级配置完整

`components/board/khadas-vim3/config.jsonnet` 必须（SHALL）声明
`board="khadas-vim3"`、`soc="a311d"`、`platform="amlogic"`，并选择
`meson-g12b-a311d-khadas-vim3` DTB、`khadas-vim3_defconfig`、`flange_fastboot.config` 与
`khadas-vim3` FIP board 目录。它必须（SHALL）支持 `default`/`desktop` product 和 `debug`/`release` variant。

#### Scenario: 三层合并产生 VIM3 canonical 配置

- **WHEN** 解析 `khadas-vim3-default-release`
- **THEN** `kernel.device_tree == {"directory": "amlogic", "name": "meson-g12b-a311d-khadas-vim3"}`
- **AND** `bootloader.defconfig == ["khadas-vim3_defconfig", "flange_fastboot.config"]`
- **AND** `bootloader.fip_board_dir == "khadas-vim3"`
- **AND** `bootloader.fip_tool == "aml_encrypt_g12b"`

#### Scenario: lunch target 自动派生

- **WHEN** 枚举全部 lunch target
- **THEN** 结果包含 `khadas-vim3-default-debug`、`khadas-vim3-default-release`、
  `khadas-vim3-desktop-debug` 和 `khadas-vim3-desktop-release`

### Requirement: khadas-vim3 共用板载外设策略

Khadas VIM3 必须（SHALL）复用与 VIM3L 相同的 AP6398S Wi-Fi/BT 固件、板载 eMMC GPT 布局、ADB gadget
配置和 SPICC1 用户态访问。fastboot 必须（MUST）操作 U-Boot 的 `mmc2`，bootloader 写入 eMMC hardware
boot0，boot/rootfs 写入 user-area GPT。

#### Scenario: AP6398S 固件进入 rootfs 配置

- **WHEN** 解析 khadas-vim3 的完整配置
- **THEN** `rootfs.extra_firmware` 包含 fenix `_ap6398s` 的 Wi-Fi firmware、NVRAM 和 BT patchram 三件套
- **AND** `rootfs.packages` 包含 `bluez`
- **AND** 不声明 out-of-tree Wi-Fi/BT 模块

#### Scenario: VIM3 使用板级 fastboot fragment

- **WHEN** 配置 khadas-vim3 U-Boot
- **THEN** 从板级 patches 目录取得 `flange_fastboot.config`
- **AND** fragment 声明 `CONFIG_FASTBOOT_FLASH_MMC_DEV=2`
- **AND** `fastboot flash bootloader` 映射到 eMMC hardware boot0

#### Scenario: VIM3 默认启用 SPICC1 overlay

- **WHEN** 解析 khadas-vim3 的完整配置
- **THEN** `boot.overlays.board` 与 `boot.overlays.enabled` 均包含 `vim3-spidev-spicc1.dtbo`
- **AND** 对应源文件位于 `components/board/khadas-vim3/dtso/`
