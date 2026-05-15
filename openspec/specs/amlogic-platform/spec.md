# amlogic-platform Specification

## Purpose
Amlogic SoC 家族（GXBB / G12A / G12B / SM1 / SC2 等）的平台级构建策略，覆盖 kernel / bootloader / rootfs / boot / image 全套 ComponentBuilder 与 PLATFORM + SOC 两层配置继承。bootloader 走 mainline u-boot + LibreELEC/amlogic-boot-fip 仓库（board-organized） + `aml_encrypt_<family>` 工具的 FIP 打包链路；boot 入口位于 eMMC hw boot0 分区（与 Rockchip / Allwinner 把 bootloader 放 user area 形成对照）。作为 flange 内 `platform = "amlogic"` 的权威规范；首版由 change `add-amlogic-khadas-vim3l` 引入，覆盖 s905d3 SoC 与 khadas-vim3l 板。

## Requirements

### Requirement: amlogic 平台模块自动发现

`builder/platforms/amlogic/__init__.py` 必须（SHALL）导出 `ARTIFACT_NAMES` 字典与 `create_builder(component, docker, source)` 工厂函数，使 `builder/engine.py` 通过 `import builder.platforms.amlogic` 即可获取平台所有 ComponentBuilder。模块布局必须（SHALL）与 `builder/platforms/rockchip/` 同形：`kernel.py` / `bootloader.py` / `boot.py` / `rootfs.py` / `recovery.py` / `image.py` 各自实现一个 ComponentBuilder。

#### Scenario: 引擎自动加载 amlogic 平台

- **WHEN** 任意 board 的 `config["platform"] == "amlogic"`
- **AND** engine 调用 `_create_builder(component)`
- **THEN** `import builder.platforms.amlogic` 成功
- **AND** `ARTIFACT_NAMES` 与 `create_builder` 均可被 engine 调用
- **AND** 不得（MUST NOT）在 engine 中出现 `if platform == "amlogic"` 形式的硬编码分支

#### Scenario: 产物名映射来自 amlogic 模块

- **WHEN** 构建 amlogic 平台某 board 的某组件并把产物收集到 target 目录
- **THEN** engine 使用 `builder.platforms.amlogic.ARTIFACT_NAMES` 中定义的 `(component, key) → 文件名` 映射，不得（MUST NOT）使用其他平台的映射

### Requirement: amlogic 平台 SoC 配置自动发现

`components/platform/amlogic/config.py` 必须（SHALL）导出 `PLATFORM` 字典使 `_load_platform_config("amlogic")` 返回平台级配置；`components/platform/amlogic/<soc>/config.py` 必须（SHALL）导出 `SOC` 字典使 `_load_soc_config(<soc>)` 返回 SoC 级配置。SoC 目录命名采用具体型号风格（如 `s905d3/`），不使用 family code（如 `sm1/`）。

#### Scenario: 自动发现 amlogic 平台

- **WHEN** `components/platform/amlogic/config.py` 存在并导出 `PLATFORM` 变量
- **THEN** `_load_platform_config("amlogic")` 成功返回字典
- **AND** `_discover_platform_configs()` 返回结果包含 key `"amlogic"`

#### Scenario: 自动发现 s905d3 SoC

- **WHEN** `components/platform/amlogic/s905d3/config.py` 存在并导出 `SOC` 变量
- **THEN** `_load_soc_config("s905d3")` 成功返回字典
- **AND** 返回字典中 `platform == "amlogic"` 且 `soc == "s905d3"` 且 `arch == "aarch64"`

#### Scenario: amlogic 与现有平台不互相污染

- **WHEN** 同时合并 amlogic 板（如 khadas-vim3l）与 rockchip 板（如 radxa-rock5b）的配置
- **THEN** 两者解析后的 `platform` 字段分别为 `"amlogic"` 与 `"rockchip"`
- **AND** 任一平台的 PLATFORM/SOC 字典不得（MUST NOT）出现在另一平台的合并结果中

### Requirement: s905d3 SoC 配置完整声明

`components/platform/amlogic/s905d3/config.py` 的 `SOC` 字典必须（SHALL）至少声明以下字段：`platform="amlogic"`、`soc="s905d3"`、`arch="aarch64"`、`vendor="amlogic"`、`repos.{u-boot, linux, amlogic-boot-fip}` 三个仓库声明、`bootloader.{from_repo="u-boot", defconfig_fragments, fip_tool="aml_encrypt_g12a", fip_family_inc="g12a.inc"}`、`kernel.{from_repo="linux", defconfig, dts_dir="amlogic"}`、`boot.{kernel_args, dtb_overlays, default_overlays}`、`partitions.entries`。

注：`fip_board_dir`（amlogic-boot-fip 仓库内的 board 子目录名，如 `khadas-vim3l`）是 board 粒度而非 SoC 粒度，由 board config 声明（同 SoC 不同 board 在 LibreELEC/amlogic-boot-fip 内使用不同 blob 集）。

#### Scenario: SoC 声明 u-boot 主线仓库 + fastboot fragment

- **WHEN** 加载 `_load_soc_config("s905d3")`
- **THEN** 返回字典中 `repos["u-boot"]["repo"] == "https://github.com/u-boot/u-boot.git"`
- **AND** `repos["u-boot"]["branch"]` 为 mainline 标签（如 `"v2024.10"`）
- **AND** `bootloader.defconfig_fragments[0] == "khadas-vim3l_defconfig"`
- **AND** `bootloader.defconfig_fragments` 含 fastboot 相关 fragment（路径由 SoC config 决定，启用 `CONFIG_USB_FUNCTION_FASTBOOT` / `CONFIG_FASTBOOT_FLASH` / `CONFIG_CMD_FASTBOOT`）

#### Scenario: SoC 声明 LibreELEC fip blobs 仓库

- **WHEN** 加载 `_load_soc_config("s905d3")`
- **THEN** 返回字典中 `repos["amlogic-boot-fip"]["repo"] == "https://github.com/LibreELEC/amlogic-boot-fip.git"`
- **AND** `bootloader.fip_family_inc == "g12a.inc"`（SM1 family 复用 G12A 工具链）
- **AND** `bootloader.fip_tool == "aml_encrypt_g12a"`

#### Scenario: SoC 声明 mainline kernel 6.12 LTS

- **WHEN** 加载 `_load_soc_config("s905d3")`
- **THEN** `repos["linux"]["repo"] == "https://github.com/torvalds/linux.git"`
- **AND** `repos["linux"]["branch"]` 为 `"v6.12"` 或后续 6.12.y 维护标签
- **AND** `kernel.dts_dir == "amlogic"`

#### Scenario: SoC kernel_args 包含 ttyAML0 console

- **WHEN** 加载 `_load_soc_config("s905d3")`
- **THEN** `boot.kernel_args` 字符串中包含 `console=ttyAML0,115200`
- **AND** 包含 `earlycon`（具体地址由 dts 决定，可省略地址段）

### Requirement: amlogic bootloader 构建走 FIP 打包流程

`builder/platforms/amlogic/bootloader.py` 的 ComponentBuilder 必须（SHALL）在 mainline u-boot 编译产出 `u-boot.bin` 之后，通过 `LibreELEC/amlogic-boot-fip` 仓库内的 `build-fip.sh <board_dir> <u-boot.bin> <out>` 脚本拼装 FIP 镜像（`<out>/u-boot.bin`），然后调 `aml_encrypt_g12a --bootsd` 派生 SD/eMMC 可启动镜像 `u-boot.bin.sd.bin`。`<board_dir>` 必须（SHALL）从 board config 的 `bootloader.fip_board_dir` 字段读取。所有 fip blobs 与工具必须（SHALL）从 `repos.amlogic-boot-fip` 声明的仓库内对应 board 子目录取得；不得（MUST NOT）在源码或 Docker 镜像中硬编码 blob 内容。

#### Scenario: bootloader 产物为 u-boot.bin.sd.bin

- **WHEN** 构建 khadas-vim3l 的 bootloader 组件
- **THEN** `target/bootloader/u-boot.bin.sd.bin` 存在
- **AND** 该文件由 `aml_encrypt_g12a --bootsd` 派生，是合法的 Amlogic SD/eMMC 启动镜像

#### Scenario: FIP 流程使用 build-fip.sh

- **WHEN** bootloader 构建过程
- **THEN** 调用 `<amlogic-boot-fip_src>/build-fip.sh khadas-vim3l <u-boot.bin> <out>` 完成 FIP 拼装
- **AND** 后续派生步骤使用同仓库内 `khadas-vim3l/aml_encrypt_g12a` 工具（不得（MUST NOT）从 host `$PATH` 查找）

#### Scenario: board 粒度 fip 子目录

- **WHEN** 加载 khadas-vim3l 完整合并配置
- **THEN** `bootloader.fip_board_dir == "khadas-vim3l"`
- **AND** 该字段由 board 层声明（不在 SoC 层）—— 同 SoC 不同 board 在 LibreELEC/amlogic-boot-fip 内使用不同 blob 集

### Requirement: amlogic 平台产物映射

`builder/platforms/amlogic/__init__.py` 的 `ARTIFACT_NAMES` 字典必须（SHALL）至少声明以下映射：

| (component, key) | 目标文件名 |
|---|---|
| (kernel, dtbos) | overlay |
| (kernel, modules) | modules |
| (bootloader, fip) | u-boot.bin.sd.bin |
| (boot, boot) | boot.img |
| (rootfs, rootfs) | rootfs.img |
| (recovery, recovery) | recovery.img |
| (image, image) | raw.img |

#### Scenario: bootloader fip 产物落地

- **WHEN** 构建 khadas-vim3l bootloader
- **THEN** `target/bootloader/u-boot.bin.sd.bin` 存在
- **AND** 该路径由 `ARTIFACT_NAMES[("bootloader", "fip")] == "u-boot.bin.sd.bin"` 决定

#### Scenario: image 产物为 raw.img

- **WHEN** 构建 khadas-vim3l image
- **THEN** `target/raw.img` 存在并包含完整 GPT 与所有分区数据

### Requirement: khadas-vim3l 板级配置完整

`components/board/khadas-vim3l/config.py` 必须（SHALL）作为合法 board 配置文件存在并导出 `BOARD` 字典，使 `_discover_boards()` 返回结果包含 key `"khadas-vim3l"`。该 board 配置必须（SHALL）至少声明：`board="khadas-vim3l"`、`soc="s905d3"`、`platform="amlogic"`、`kernel.dts="meson-sm1-khadas-vim3l"`、`rootfs.+extra_firmware`（含 brcmfmac4359 三件套）。

#### Scenario: 三层合并产生完整配置

- **WHEN** 调用 `get_board_config("khadas-vim3l")`
- **THEN** 返回字典中 `platform == "amlogic"` 且 `soc == "s905d3"` 且 `kernel.dts == "meson-sm1-khadas-vim3l"`
- **AND** `kernel.dts_dir == "amlogic"`（由 SoC 层提供，board 层不覆盖）
- **AND** `bootloader.defconfig == "khadas-vim3l_defconfig"`（由 SoC 层提供）

#### Scenario: lunch target 自动派生

- **WHEN** 执行 `flange` CLI 列举 lunch target
- **THEN** 输出包含 `khadas-vim3l-default-debug` 与 `khadas-vim3l-default-release`

### Requirement: khadas-vim3l Wi-Fi/BT 固件部署

khadas-vim3l 的 `rootfs.+extra_firmware` 必须（SHALL）声明从 `khadas/fenix` 仓库 `archives/hwpacks/wlan-firmware/brcm/` 路径拉取 AP6398S 板级三件套，rename 落地为 mainline 标准通用名：

| 源文件 | 落地名 | 用途 |
|---|---|---|
| `brcmfmac4359-sdio_ap6398s.bin` | `/lib/firmware/brcm/brcmfmac4359-sdio.bin` | WiFi 固件（brcmfmac 主固件加载名）|
| `brcmfmac4359-sdio_ap6398s.txt` | `/lib/firmware/brcm/brcmfmac4359-sdio.txt` | NVRAM（brcmfmac fallback 通用名）|
| `BCM4359C0_ap6398s.hcd` | `/lib/firmware/brcm/BCM4359C0.hcd` | BT patchram（btbcm 标准名）|

平台层（amlogic）不得（MUST NOT）在 `rootfs.+packages` 声明 WiFi/BT 通用固件 apt 包（不同 amlogic 板的 WiFi/BT chip 各异；Ubuntu 24.04 也无 `firmware-brcm80211` 切片包）。

驱动必须（SHALL）使用 mainline in-tree `brcmfmac`（SDIO Wi-Fi）与 `hci_uart` + `btbcm`（BT over UART），不得（MUST NOT）引入 OOT 模块。BT 启动通过 systemd 单元 `bluetooth-vim3l.service` 在 `bluetooth.target` 之前调用 `btattach -B /dev/ttyAML6 -P bcm` 完成。

#### Scenario: rootfs 含三件套固件全集

- **WHEN** 构建 khadas-vim3l rootfs 并解开 rootfs.img
- **THEN** `/lib/firmware/brcm/brcmfmac4359-sdio.bin` 存在（内容来自 fenix `_ap6398s.bin` 源）
- **AND** `/lib/firmware/brcm/brcmfmac4359-sdio.txt` 存在（内容来自 fenix `_ap6398s.txt` 源）
- **AND** `/lib/firmware/brcm/BCM4359C0.hcd` 存在（内容来自 fenix `_ap6398s.hcd` 源）

#### Scenario: 平台层不挂通用固件 apt 包

- **WHEN** 加载 amlogic 平台配置 `_load_platform_config("amlogic")`
- **THEN** `rootfs.+packages` 不得包含 `firmware-brcm80211` 或其他 WiFi/BT 固件 apt 包名

#### Scenario: BT systemd 单元随 rootfs 部署

- **WHEN** 构建 khadas-vim3l rootfs 并解开 rootfs.img
- **THEN** `/etc/systemd/system/bluetooth-vim3l.service` 存在
- **AND** 单元内 ExecStart 调用 `btattach -B /dev/ttyAML6 -P bcm`
- **AND** 单元 Before=bluetooth.target

#### Scenario: 不引入 OOT 模块

- **WHEN** 加载 khadas-vim3l 完整合并配置
- **THEN** `kernel.oot_sources` 与 `kernel.+oot_modules` 均为空
- **AND** Wi-Fi/BT 驱动完全由 mainline 6.12 in-tree 模块提供

### Requirement: khadas-vim3l 首版启动验证链路

khadas-vim3l 第一版本必须（SHALL）通过以下端到端流程：MaskROM (按住 KEY1，1b8e:c003) → pyamlboot 推 u-boot → u-boot 自动进 fastboot → host fastboot 写入 bootloader (eMMC boot0) / boot / recovery / rootfs → fastboot reboot → UART_AO（ttyAML0，115200bps）输出 U-Boot 与 Linux kernel banner → systemd 启动至 multi-user.target → 板载 GbE 获取 IP → ssh 连接成功 → `iw wlan0 scan` 返回结果 → `bluetoothctl scan on` 检出至少一个邻近设备。

#### Scenario: 串口可见 U-Boot 与内核 banner

- **WHEN** khadas-vim3l 完成全分区刷写并上电（KEY1 已松开）
- **THEN** ttyAML0（115200bps）依次输出 BL2 banner、BL31 banner、U-Boot proper banner、Linux kernel banner

#### Scenario: SSH 登录成功

- **WHEN** khadas-vim3l 完成首次启动且板载 GbE 接入网络
- **THEN** 主机端 `ssh root@<vim3l-ip>` 连接成功
- **AND** `uname -r` 输出与 mainline 6.12 LTS 版本一致

#### Scenario: Wi-Fi 关联成功

- **WHEN** khadas-vim3l 启动后执行 `iw wlan0 scan`
- **THEN** 输出包含至少一个 BSS（前提：测试环境有可见 SSID）
- **AND** `dmesg | grep brcmfmac` 显示 firmware 加载成功，无 `brcmf_attach: brcmf_busif failed` 类错误

#### Scenario: BT 设备启动成功

- **WHEN** khadas-vim3l 启动后执行 `hciconfig`
- **THEN** 输出包含 `hci0: BR/EDR/LE`（不为 DOWN 状态）
- **AND** `bluetoothctl scan on` 启动后能检出至少一个邻近 BT 设备

#### Scenario: 不在范围的硬件首版不验收

- **WHEN** khadas-vim3l 完成首版验证
- **THEN** GPU (Mali-G31) / HDMI / VPU / NPU / USB OTG gadget 不纳入验收范围
- **AND** 这些硬件的支持由后续独立变更逐项添加

### Requirement: khadas-vim3l SPI 用户态访问
khadas-vim3l 板必须（SHALL）通过板私有 DT overlay `vim3l-spidev-spicc1.dtbo` 在首启即 enable SPICC1 控制器（`spi@ffd15000`），并通过 spidev 框架在用户态暴露至少一颗 `/dev/spidev*` 节点。

overlay 源文件 `components/board/khadas-vim3l/dtso/vim3l-spidev-spicc1.dtso` 必须（MUST）满足：

- 通过 `&spicc1` 把控制器 `status` 设为 `"okay"`
- `pinctrl-names = "default";` 与 `pinctrl-0 = <&spicc1_pins>, <&spicc1_ss0_pins>;`（引用 g12-common.dtsi 中预定义的 pinmux group）
- 包含一个 `spidev@0` 子节点：`compatible = "rohm,dh2228fv";`（mainline `drivers/spi/spidev.c` of_match_table 既有项；裸 `linux,spidev` 自 v5.18 起被拒绝）、`reg = <0>;`、`spi-max-frequency = <24000000>;`
- 不引入 `#include <dt-bindings/...>`（保持源文件 cpp 阶段 no-op，编译路径最短）

`components/board/khadas-vim3l/config.py` 必须（SHALL）在 `BOARD["boot"]` 中声明：

- `"board_overlays": ["vim3l-spidev-spicc1.dtbo"]`
- `"default_overlays": ["vim3l-spidev-spicc1.dtbo"]`

使该 overlay 默认进入 extlinux `fdtoverlays` 行、首启即生效。

不得（MUST NOT）启用 `spicc0`（与 eMMC 数据线物理冲突）。不得（MUST NOT）修改 mainline `drivers/spi/spidev.c` 的 `of_match_table`（借壳法是稳态约定俗成解）。

#### Scenario: VIM3L 默认配置含 SPI overlay
- **WHEN** 调用 `get_board_config("khadas-vim3l")` 取得合并后的配置
- **THEN** `boot.board_overlays == ["vim3l-spidev-spicc1.dtbo"]`
- **AND** `boot.default_overlays == ["vim3l-spidev-spicc1.dtbo"]`

#### Scenario: dtso 源文件存在并满足契约
- **WHEN** 检视 `components/board/khadas-vim3l/dtso/vim3l-spidev-spicc1.dtso`
- **THEN** 文件存在
- **AND** 文件首行包含 `/dts-v1/;`
- **AND** 文件包含 `/plugin/;` 指令
- **AND** 文件包含 `&spicc1` 引用块
- **AND** 文件包含 `status = "okay";`
- **AND** 文件包含 `compatible = "rohm,dh2228fv";`
- **AND** 文件包含 `spi-max-frequency = <24000000>;`

#### Scenario: VIM3L 启动后 spidev 节点出现
- **WHEN** khadas-vim3l 完成全分区刷写并上电启动至 multi-user.target
- **THEN** 至少存在一个 `/dev/spidev*` 字符设备节点
- **AND** `cat /sys/class/spi_master/spi*/of_node/compatible` 包含 `amlogic,meson-g12a-spicc`
- **AND** 该 spi_master 下子设备 `of_node/compatible` 包含 `rohm,dh2228fv`

#### Scenario: 自环验证（loopback）
- **WHEN** 将 spicc1 的 MOSI 与 MISO 在 40-pin header 上短接，执行 `spidev_test -D /dev/spidev<N>.0 -s 1000000 -v`
- **THEN** spidev_test 退出码为 0
- **AND** 输出的 RX 缓冲与 TX 缓冲完全一致
