## MODIFIED Requirements

### Requirement: Rockchip 平台支持 Radxa ROCK 4D 板级配置（UFS）

`components/board/radxa-rock-4d/config.py` 必须（SHALL）作为合法 board 配置文件存在并导出 `BOARD` 字典，使 `平台 → SoC → board` 三层 deep_merge 后产出可构建的合并配置。该 board 配置 MUST 声明 `board="radxa-rock-4d"`、`soc="rk3576"`、`platform="rockchip"`、`kernel.dts="rk3576-rock-4d"`。

该 board 配置 MUST 走**自编 spi.img**：移除 `bootloader.prebuilt_spi_image`，声明 `flash_spi_loader=True`，使 `builder/flash.py` 经 `build_spi_image` 组装 spi.img（`idbloader.img`@sector 64、`u-boot.itb`@sector 16384）。bootloader 经 self-build 路径产 idbloader + u-boot.itb：idbloader 经 `boot_merger` 装配（见「Rockchip 平台 RK3576 idbloader 经 boot_merger 装配」requirement），含引导级 `rk3576_boost`；u-boot.itb 自编（radxa u-boot proper + rkbin BL31/OP-TEE）。该 board MUST 在 board 层覆盖 `bootloader.defconfig="rock-4d-spi-rk3576_defconfig"`（其 `DEFAULT_DEVICE_TREE="rk3576-rock-4d-spi"`，含 ROCK 4D 的 SPI NOR 控制器 pinmux 与板级节点），**不得**沿用 SoC 层 generic `rk3576_defconfig`（`DEFAULT_DEVICE_TREE="rk3576-evb"`，缺板级节点 → 产「错板」proper u-boot）。该 board MUST 自编 SPL：boot_merger 路径把 `RK3576MINIALL.ini` 副本的 `FlashBoot=` sed 为自编 `spl/u-boot-spl.bin`（boost/DDR 仍取 rkbin），不经 `bootloader.idbloader_spl` 配置项（该键已移除）。

该 board 配置 MUST 在 board 层整块覆盖 `partitions`，其 `partitions.sector_size` 为 `4096`；SoC 层 `rk3576/config.py` 的 512 字节 eMMC 默认布局保持不变（不得被本变更修改）。

该 board 配置 MUST 声明板载 WiFi/BT 的 AIC8800D80 USB combo 支持，与其他 radxa 板同一 `radxa-pkg/aic8800` OOT 路线：`kernel.oot_sources` 含 `aic8800` 源，`kernel.oot_modules`（合并后）含 WiFi 驱动（`aic_load_fw`+`aic8800_fdrv`）与 BT 驱动（`aic_btusb`），`rootfs.extra_firmware`（合并后）含部署到 `/lib/firmware/aic8800D80/` 的 AIC8800D80 固件。

#### Scenario: ROCK 4D 合并配置可发现且字段正确

- **WHEN** 解析 lunch target `radxa-rock-4d-default-debug` 的合并配置
- **THEN** 合并结果 `soc == "rk3576"` 且 `platform == "rockchip"`
- **AND** `kernel.dts == "rk3576-rock-4d"`
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

## ADDED Requirements

### Requirement: Rockchip 平台 RK3576 idbloader 经 boot_merger 装配

RK3576 的 idbloader 必须（SHALL）由 `boot_merger` 按 `RK3576MINIALL.ini` 装配，而非 `mkimage -T rksd` —— 因 RK3576 的 stock idbloader 须含引导级 `rk3576_boost`（`RK3576MINIALL.ini` 的 `[LOADER_OPTION]` 成员；armbian `rockchip64_common.inc` 亦专为 RK3576 走此路径），而 `mkimage -T rksd -d ddr:spl` 路径无法携带该组件。（注：UFS 启动崩溃真因经逐次上板 + 反汇编坐实为 `gcc-13` 工具链布局效应，已由全平台默认 `gcc-10` 单独修复；boot_merger 为产出 stock-correct idbloader 所必需，与崩溃真因无因果。）

`builder/platforms/rockchip/bootloader.py` MUST 在 SoC 声明 idbloader 经 boot_merger 时（`bootloader.idbloader_method == "boot_merger"`，声明于 `components/platform/rockchip/rk3576/config.py`）执行：跑 `boot_merger {ini_prefix}MINIALL.ini`，从该 ini 的 `[OUTPUT] IDB_PATH=` **动态解析** idblock 文件名（含版本号，不得硬编码），将其产物拷为 `idbloader.img`（NEWIDB 格式、含 `rk3576_boost`），并跳过 `mkimage -T rksd`。idbloader 的 DDR/boost MUST 取自 rkbin prebuilt blob（stock ini `[LOADER_OPTION]` 的 `FlashData=`/`FlashBoost=`），SPL MUST 自编：`bootloader.py` 把 ini 副本的 `FlashBoot=` sed 为自编 `spl/u-boot-spl.bin`（需 board defconfig 开 `CONFIG_SPL`），不污染 rkbin 仓库的 stock ini。

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
