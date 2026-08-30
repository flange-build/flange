# rockchip-platform Specification

## Purpose

Rockchip 平台层 SoC 配置自动发现契约，以及开源 GPU 驱动 config fragment 按
SoC GPU 架构选型的约束（panfrost/Bifrost 与 panthor/Valhall-CSF 并列）。
## Requirements
### Requirement: Rockchip 平台支持 RK3576 SoC 配置发现

`components/platform/rockchip/rk3576/config.jsonnet` 必须（SHALL）作为合法 SoC 配置
文件必须 manifest 合法 SoC overlay，使 `builder/config/registry.py:_load_soc_config("rk3576")`
成功返回该 object。最终配置 MUST 至少声明：`platform="rockchip"`、`soc="rk3576"`、
`architecture.{userspace,kernel,bootloader}`、`vendor="rockchip"`、`rkbin.{ini_prefix,trust_ini_prefix,mkimage_chip,source}`、
`bootloader.{source,defconfig}`、`kernel.{source,defconfig,device_tree.directory}`、
`boot.kernel_args`、`partitions.entries`。其中内核仓库、分支与 base defconfig
必须（SHALL）与 RK3588 一致（同 argon BSP 全 SoC 树）。

#### Scenario: 自动发现 rk3576

- **WHEN** `components/platform/rockchip/rk3576/config.jsonnet` 存在且 `soc == "rk3576"`
- **THEN** `_discover_soc_configs()` 返回结果包含 key `"rk3576"`
- **AND** `_load_soc_config("rk3576")` 返回字典中 `rkbin.ini_prefix == "RK3576"` 且 `rkbin.trust_ini_prefix == "RK3576"` 且 `rkbin.mkimage_chip == "rk3576"`

#### Scenario: rk3576 内核配置对齐 rk3588

- **WHEN** 比较 RK3576 与 RK3588 board 的最终 `kernel` 块
- **THEN** 两者 `kernel.source.name` 相同，且引用 source 的 branch 均为 `"linux-6.1-stan-rkr5.1"`
- **AND** 两者 `kernel.defconfig` 的 base（list 首项）均为 `"rockchip_linux_defconfig"`
- **AND** rk3576 的 `kernel.defconfig` list 含 `"rk3576_panfrost.config"`（rk3588 对应位置为 `"rk3588_panthor.config"`）

#### Scenario: rk3576 与 rk3588 不互相污染

- **WHEN** 同时解析 RK3576 板与 RK3588 板的合并配置
- **THEN** 两者 `rkbin.mkimage_chip` 分别为 `"rk3576"` 与 `"rk3588"`
- **AND** 两者 GPU fragment 分别为 `"rk3576_panfrost.config"` 与 `"rk3588_panthor.config"`

### Requirement: Rockchip GPU 开源驱动 fragment 按 SoC GPU 架构选型

`builder/platforms/rockchip/kernel.py` 的 `RockchipKernelBuilder` 必须（SHALL）
按 SoC 的 GPU 架构提供独立的开源 GPU config fragment 生成函数：RK3576
（Mali-G52，Bifrost）走 `_write_panfrost_fragment` 生成 `rk3576_panfrost.config`，
RK3588/RK3588S（Mali-G610，Valhall-CSF）走 `_write_panthor_fragment` 生成
`rk3588_panthor.config`。每个 fragment 函数对非目标 SoC 必须（SHALL）写空
fragment（满足 `make <name>.config` 合并要求，且不影响其他 SoC）。
`_write_panfrost_fragment` 对 RK3576 生成的内容 MUST 关闭闭源 mali_kbase
（`CONFIG_MALI_BIFROST`/`CONFIG_MALI_MIDGARD` 等）与 utgard（mali400/450），
并启用 `CONFIG_DRM_PANFROST=m`。

#### Scenario: rk3576 启用 panfrost fragment

- **WHEN** 为 RK3576 SoC 生成 kernel config fragment
- **THEN** `arch/arm64/configs/rk3576_panfrost.config` 含 `CONFIG_DRM_PANFROST=m`
- **AND** 含 `# CONFIG_MALI_BIFROST is not set`（闭源 kbase 被关闭）
- **AND** RK3576 SoC 的 `kernel.defconfig` list 引用了该 fragment

#### Scenario: panfrost fragment 对 RK3588 为空、不污染 panthor

- **WHEN** 当前构建 SoC 为 `rk3588`
- **THEN** 生成的 `rk3576_panfrost.config` 为空 fragment（仅注释）
- **AND** RK3588 的 GPU 路线仍由 `rk3588_panthor.config` 决定，行为不变

#### Scenario: 合并后闭源 kbase 在 RK3576 上确被关闭

- **WHEN** RK3576 完成 `rockchip_linux_defconfig` + 各 fragment 合并
- **THEN** 最终 `.config` MUST NOT 含 `CONFIG_MALI_BIFROST=y`
- **AND** 含 `CONFIG_DRM_PANFROST=m`

### Requirement: Rockchip 平台支持 Radxa ROCK 4D 板级配置（UFS）

`components/board/radxa-rock-4d/config.jsonnet` 必须（SHALL）manifest 合法 board overlay，使 Jsonnet 固定层级组合后产出可构建的 canonical 配置。该 board 配置 MUST 声明 `board="radxa-rock-4d"`、`soc="rk3576"`、`platform="rockchip"`、`kernel.device_tree.name="rk3576-rock-4d"`。

该 board 配置 MUST 走**自编 spi.img**：移除 `bootloader.prebuilt_spi_image`，声明 `flash_spi_loader=True`，使 `builder/flash.py` 经 `build_spi_image` 组装 spi.img（`idbloader.img`@sector 64、`u-boot.itb`@sector 16384）。bootloader 经 self-build 路径产 idbloader + u-boot.itb：idbloader 经 `boot_merger` 装配（见「Rockchip 平台 RK3576 idbloader 经 boot_merger 装配」requirement），含引导级 `rk3576_boost`；u-boot.itb 自编（radxa u-boot proper + rkbin BL31/OP-TEE）。该 board MUST 在 board 层覆盖 `bootloader.defconfig="rock-4d-spi-rk3576_defconfig"`（其 `DEFAULT_DEVICE_TREE="rk3576-rock-4d-spi"`，含 ROCK 4D 的 SPI NOR 控制器 pinmux 与板级节点），**不得**沿用 SoC 层 generic `rk3576_defconfig`（`DEFAULT_DEVICE_TREE="rk3576-evb"`，缺板级节点 → 产「错板」proper u-boot）。该 board MUST 自编 SPL：boot_merger 路径把 `RK3576MINIALL.ini` 副本的 `FlashBoot=` sed 为自编 `spl/u-boot-spl.bin`（boost/DDR 仍取 rkbin），不经 `bootloader.idbloader_spl` 配置项（该键已移除）。

该 board 配置 MUST 在 board 层整块覆盖 `partitions`，其 `partitions.sector_size` 为 `4096`；SoC 层 `rk3576/config.jsonnet` 的 512 字节 eMMC 默认布局保持不变（不得被本变更修改）。

该 board 配置 MUST 声明板载 WiFi/BT 的 AIC8800D80 USB combo 支持，与其他 radxa 板同一 `radxa-pkg/aic8800` OOT 路线：`kernel.oot_sources` 含 `aic8800` 源，`kernel.oot_modules`（合并后）含 WiFi 驱动（`aic_load_fw`+`aic8800_fdrv`）与 BT 驱动（`aic_btusb`），`rootfs.extra_firmware`（合并后）含部署到 `/lib/firmware/aic8800D80/` 的 AIC8800D80 固件。

#### Scenario: ROCK 4D 合并配置可发现且字段正确

- **WHEN** 解析 lunch target `radxa-rock-4d-default-debug` 的合并配置
- **THEN** 合并结果 `soc == "rk3576"` 且 `platform == "rockchip"`
- **AND** `kernel.device_tree.name == "rk3576-rock-4d"`
- **AND** 合并配置不含 `bootloader.prebuilt_spi_image`，且 `flash_spi_loader == True`（自编 spi.img）
- **AND** `bootloader.defconfig == "rock-4d-spi-rk3576_defconfig"`（board 覆盖，DT=rk3576-rock-4d-spi）
- **AND** 合并配置不含 `bootloader.idbloader_spl`（SPL 自编经 boot_merger sed `FlashBoot`，非经该配置项）
- **AND** 合并配置继承 SoC 层 `bootloader.idbloader_method == "boot_merger"`
- **AND** `partitions.sector_size == 4096`

#### Scenario: board 层 UFS 覆盖不污染 SoC 层 eMMC 默认

- **WHEN** 比较 `_load_soc_config("rk3576")` 与 ROCK 4D 的合并配置
- **THEN** SoC 层 `partitions` 不含 `sector_size` 或其值仍为 512（eMMC 默认布局未被改动）
- **AND** 仅 ROCK 4D 合并配置的 `partitions.sector_size` 为 4096

#### Scenario: ROCK 4D 板载 AIC8800D80 USB WiFi/BT

- **WHEN** 解析 ROCK 4D 的合并配置（`resolve_config`）
- **THEN** `kernel.oot_sources` 含 `aic8800`
- **AND** `kernel.oot_modules` 含标签匹配 `aic8800`（WiFi）与 `aic_btusb`（BT）的条目
- **AND** `rootfs.extra_firmware` 含 `name == "aic8800-d80"` 且 `dest` 指向 `lib/firmware/aic8800D80`

### Requirement: Rockchip 镜像组装按 sector_size 支持 4096 字节 UFS 扇区

`builder/platforms/rockchip/image.py` 的 `RockchipImageBuilder` 必须（SHALL）从 `partitions.sector_size` 读取目标逻辑块大小，缺省为 512。当 `sector_size == 512` 时，镜像组装行为 MUST 与本变更前保持一致（现有 eMMC/SD 板产物 byte-identical）。

当 `sector_size != 512`（如 4096）时，`RockchipImageBuilder` MUST 以该扇区大小写出 GPT 与各分区：GPT 必须（SHALL）按目标扇区对齐（通过 `losetup -b <sector_size>` 把镜像挂为报告该 LBA 的 loop 设备后由 `parted` 写入，对齐 qcs6490 范式）；config 中以 512 字节为单位声明的 offset/size 必须（SHALL）重算为目标扇区（`off_512 × 512 ÷ sector_size`）；`dd` 写入 MUST 用 `bs=<sector_size>`。

当 `sector_size == 4096` 时，rootfs 分区的 Type-UUID 必须（SHALL）设为 EFI System Partition GUID `C12A7328-F81F-11D2-BA4B-00A0C93EC93B`（规避 4K rk35xx 的 bootloader quirk）；该改动 MUST NOT 影响 512 字节路径上 rootfs 现有的固定 PARTUUID（`614e0000-...`）。

#### Scenario: 4096 字节路径产出 4K 对齐 GPT

- **WHEN** 以 `partitions.sector_size == 4096` 组装 ROCK 4D 镜像
- **THEN** 生成的 `raw.img` GPT 按 4096 字节 LBA 写入（loop `-b 4096` + parted）
- **AND** 各分区起始扇区为其 512B offset 重算后的 4K 扇区值
- **AND** rootfs 分区 Type-UUID 为 `C12A7328-F81F-11D2-BA4B-00A0C93EC93B`

#### Scenario: 512 字节默认路径行为不变

- **WHEN** 以缺省（未声明 `sector_size`，即 512）组装现有 RK3566/RK3588 板镜像
- **THEN** GPT 与各分区按 512 字节扇区写入，组装逻辑与本变更前一致
- **AND** rootfs 分区仍使用固定 PARTUUID `614e0000-0000-4000-8000-000000000000`

### Requirement: Rockchip 刷写策略按 sector_size 参数化 GPT 写入

`builder/flash.py` 的 `RockchipFlashStrategy.write_gpt` 必须（SHALL）从合并配置的 `partitions.sector_size` 读取扇区大小（缺省 512），并据此计算从 `raw.img` 截取 GPT header/entries 的字节偏移与长度。对未声明 `flash_storage` 的 eMMC/SD 板，`pre_flash`（`upgrade_tool DB`）、`write_partition`（`upgrade_tool WL`）、`reboot`（`upgrade_tool RD`）流程 MUST 保持不变。

> ⚠️ **实施期演进**：对 UFS 板（声明 `flash_storage`，如 ROCK 4D），`write_gpt` MUST 因 `config.storage` 非空直接 return（不截取 raw.img GPT）；分区表改由 `flash_whole_disk` 经 `upgrade_tool DI -p parameter.txt` 建（loader 按设备实际 LBA 落盘），各分区经 `DI -<abbr>` 写入。即本变更**确实引入了** `flash_whole_disk` 路径（原 proposal Non-Goal「不引入」已被实施期推翻），但该路径用 `upgrade_tool DI`、**不使用整盘 `dd`**，与「保留 upgrade_tool 路线」初衷一致。

当 `sector_size == 512` 时，`write_gpt` 行为 MUST 与本变更前一致（现有 Rockchip 板刷写不受影响）。

#### Scenario: ROCK 4D（UFS）经 di -p 建分区表，write_gpt 跳过

- **WHEN** 对已声明 `flash_storage`（UFS/SATA）的 ROCK 4D 刷写
- **THEN** `write_gpt` 因 `config.storage` 非空直接 return（不截取 raw.img GPT）
- **AND** 分区表由 `flash_whole_disk` 经 `upgrade_tool DI -p parameter.txt` 建（loader 按设备 LBA 落盘），各分区经 `DI -<abbr>` 写入，全程不使用整盘 `dd`

#### Scenario: 512 字节默认刷写行为不变

- **WHEN** 对未声明 `sector_size`（512）的现有 Rockchip 板刷写
- **THEN** `write_gpt` 按 512 字节扇区截取并回写，行为与本变更前一致

### Requirement: Rockchip 平台 RK3576 idbloader 经 boot_merger 装配

RK3576 的 idbloader 必须（SHALL）由 `boot_merger` 按 `RK3576MINIALL.ini` 装配，而非 `mkimage -T rksd` —— 因 RK3576 的 stock idbloader 须含引导级 `rk3576_boost`（`RK3576MINIALL.ini` 的 `[LOADER_OPTION]` 成员；armbian `rockchip64_common.inc` 亦专为 RK3576 走此路径），而 `mkimage -T rksd -d ddr:spl` 路径无法携带该组件。（注：UFS 启动崩溃真因经逐次上板 + 反汇编坐实为 `gcc-13` 工具链布局效应，已由全平台默认 `gcc-10` 单独修复；boot_merger 为产出 stock-correct idbloader 所必需，与崩溃真因无因果。）

`builder/platforms/rockchip/bootloader.py` MUST 在 SoC 声明 idbloader 经 boot_merger 时（`bootloader.idbloader_method == "boot_merger"`，声明于 `components/platform/rockchip/rk3576/config.jsonnet`）执行：跑 `boot_merger {ini_prefix}MINIALL.ini`，从该 ini 的 `[OUTPUT] IDB_PATH=` **动态解析** idblock 文件名（含版本号，不得硬编码），将其产物拷为 `idbloader.img`（NEWIDB 格式、含 `rk3576_boost`），并跳过 `mkimage -T rksd`。idbloader 的 DDR/boost MUST 取自 rkbin prebuilt blob（stock ini `[LOADER_OPTION]` 的 `FlashData=`/`FlashBoost=`），SPL MUST 自编：`bootloader.py` 把 ini 副本的 `FlashBoot=` sed 为自编 `spl/u-boot-spl.bin`（需 board defconfig 开 `CONFIG_SPL`），不污染 rkbin 仓库的 stock ini。

未声明 `idbloader_method` 的其他 RK35xx（RK3566/RK3588）idbloader MUST 仍用 `mkimage -n {mkimage_chip} -T rksd -d {ddr}:{spl}`（行为与本变更前一致，不受本约束影响）。

#### Scenario: RK3576 idbloader 经 boot_merger 产出 NEWIDB 格式

- **WHEN** 为声明 `bootloader.idbloader_method == "boot_merger"` 的 RK3576 板构建 bootloader
- **THEN** `bootloader.py` 跑 `boot_merger RK3576MINIALL.ini`，从 `[OUTPUT] IDB_PATH=` 解析出 idblock 文件名（如 `rk3576_idblock_v1.10.108.img`）
- **AND** 将该 idblock 产物拷为 `idbloader.img`，且 NOT 调用 `mkimage -T rksd`
- **AND** 组装出的 spi.img 在 sector 64（0x8000）处为 NEWIDB（`RKNS`）签名、含 `rk3576_boost`

#### Scenario: 其他 RK35xx idbloader 仍走 mkimage

- **WHEN** 为未声明 `idbloader_method` 的 RK3566/RK3588 板构建 bootloader
- **THEN** `bootloader.py` 用 `mkimage -n {mkimage_chip} -T rksd -d {ddr}:{spl}` 产 `idbloader.img`
- **AND** idbloader 为旧 idblock 格式（魔数 `0x0FF0AA55`），行为与本变更前一致

### Requirement: 支持的 RK35xx board SHALL 显式启用本地多媒体 package

现有 RK3566、RK3568、RK3576、RK3582、RK3588 与 RK3588S board MUST 在 board 层通过顶层 `packages` opt-in
`rockchip-multimedia`。对应 SoC 配置 MUST NOT 再注入 `common.multimediaDebs`，共享配置 MUST NOT 保留远程 release DEB、
`force_overwrite` 或 `hold_packages` 描述。

#### Scenario: RK3588 board 解析本地 package

- **WHEN** 解析 `radxa-rock5b-default-debug` 或 `orangepi-5-plus-default-debug`
- **THEN** 顶层 `packages` 含 `rockchip-multimedia`
- **AND** `rootfs.custom_packages` 含其多 DEB 构建 App 与 udev 配置 App
- **AND** `rootfs.extra_debs` 不含旧 `CmST0us/rockchip-multimedia-ubuntu` URL

#### Scenario: 新 board 不隐式继承

- **WHEN** 新增相同 SoC 但未 opt-in `rockchip-multimedia` 的 board
- **THEN** 该 board 不构建或安装多媒体 package

