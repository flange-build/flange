## ADDED Requirements

### Requirement: Rockchip 平台支持 Radxa ROCK 4D 板级配置（UFS）

`components/board/radxa-rock-4d/config.py` 必须（SHALL）作为合法 board 配置文件存在并导出 `BOARD` 字典，使 `平台 → SoC → board` 三层 deep_merge 后产出可构建的合并配置。该 board 配置 MUST 声明 `board="radxa-rock-4d"`、`soc="rk3576"`、`platform="rockchip"`、`kernel.dts="rk3576-rock-4d"`。

该 board 配置 MUST 在 board 层声明 `bootloader.prebuilt_spi_image`（`{url, sha256}` 字典，构建期从 radxa 官方下载预编整体 spi.img、sha256 校验后缓存，不入库），flange 不自编 u-boot。根因：RK3576 的 idbloader 须用 `boot_merger` 按 `RK3576MINIALL.ini` 装配（含 `rk3576_boost`/`usbplug`），而 flange 通用 `mkimage -T rksd` 路径缺 `rk3576_boost` → 自编 u-boot 读 UFS 崩（6 次上板坐实，与 BL31/OPTEE/分支无关，见 design Decision 6）。board SHALL NOT 覆盖 `bootloader.defconfig`（prebuilt 路径不使用 defconfig，沿用 SoC 层 `rk3576_defconfig`）。

该 board 配置 MUST 在 board 层整块覆盖 `partitions`，其 `partitions.sector_size` 为 `4096`；SoC 层 `rk3576/config.py` 的 512 字节 eMMC 默认布局保持不变（不得被本变更修改）。

该 board 配置 MUST 声明板载 WiFi/BT 的 AIC8800D80 USB combo 支持，与其他 radxa 板同一 `radxa-pkg/aic8800` OOT 路线：`kernel.oot_sources` 含 `aic8800` 源，`kernel.oot_modules`（合并后）含 WiFi 驱动（`aic_load_fw`+`aic8800_fdrv`）与 BT 驱动（`aic_btusb`），`rootfs.extra_firmware`（合并后）含部署到 `/lib/firmware/aic8800D80/` 的 AIC8800D80 固件。

#### Scenario: ROCK 4D 合并配置可发现且字段正确

- **WHEN** 解析 lunch target `radxa-rock-4d-default-debug` 的合并配置
- **THEN** 合并结果 `soc == "rk3576"` 且 `platform == "rockchip"`
- **AND** `kernel.dts == "rk3576-rock-4d"`
- **AND** `bootloader.prebuilt_spi_image` 为含 `url`/`sha256` 的字典（构建期下载，不自编 u-boot；`bootloader.defconfig` 沿用 SoC 层 `rk3576_defconfig`）
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
