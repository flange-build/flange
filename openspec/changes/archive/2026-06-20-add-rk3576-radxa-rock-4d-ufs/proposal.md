## Why

flange 的 RK3576 SoC 配置（`components/platform/rockchip/rk3576/config.py`）已就位且测试绿，但其 `partitions` 沿用 RK3588 的 512 字节扇区 eMMC 布局，且平台层 `image.py` / `flash.py` 把扇区写死 512。Radxa ROCK 4D 实板用 **UFS 存储（4096 字节 LBA）**，与该假设根本冲突 —— 必须打通 4K 扇区的镜像组装与刷写通路，并落地第一块 RK3576 实板的最小启动验证（串口 + SSH）。这也是 flange "支持 UFS 存储介质" 核心目标在 Rockchip 平台上的首次兑现。

> ⚠️ **实施期演进（2026-06，以 [design.md](./design.md) Decision 6 为最终权威）**：bootloader 路线在实施期重大变更 —— 自编 u-boot 因 **RK3576 的 idbloader 须用 `boot_merger` 装配（含 `rk3576_boost`），而 flange 通用 `mkimage -T rksd` 路径缺该组件**，6 次上板均崩在 u-boot 读 UFS（与 BL31/OPTEE/分支无关）；最终改用 **board 级 `bootloader.prebuilt_spi_image`** 直刷 radxa bsp 预编 spi.img，`bootloader.py` 加 prebuilt 分支。UFS 刷写也落地了 `flash_whole_disk`（`upgrade_tool di -p`）路径。下文 What Changes / Non-Goals 中「自编 defconfig」「不动 bootloader.py」「不新增 dd 策略」等条目均已被取代（逐条标注）。

## What Changes

- **新增 board `radxa-rock-4d`**：`components/board/radxa-rock-4d/config.py`，绑定 `soc=rk3576`、`platform=rockchip`、`kernel.dts=rk3576-rock-4d`；~~board 层覆盖 `bootloader.defconfig` 为板级 `rock-4d-rk3576_defconfig`~~（**实施期改为 `bootloader.prebuilt_spi_image`**，见上方演进说明）；board 层覆盖 `partitions` 为 `sector_size=4096` 的 UFS 布局（rootfs 分区 Type-UUID 设为 EFI System GUID，规避 4K rk35xx 的 bootloader quirk）。
- **板载 WiFi/BT 走 AIC8800D80 USB**：board 配置带 `radxa-pkg/aic8800` OOT 驱动（WiFi `aic_load_fw`+`aic8800_fdrv`、BT `aic_btusb`）+ AIC8800D80 全套固件部署到 `/lib/firmware/aic8800D80/`，与其他 radxa 板（rock5c-lite / cubie-a7z/a7a）同一路线、锁同一 commit。
- **Rockchip 镜像组装支持 4K 扇区**：`builder/platforms/rockchip/image.py` 的 `SECTOR_SIZE=512` 硬编码改为读 `partitions.sector_size`（默认 512，保持现有 eMMC/SD 板 byte-identical），移植 qcs6490 的 `losetup -b <sector_size>` + offset 重算范式，在 4K 路径上把 rootfs 分区 Type-UUID 设为 EFI System GUID。
- **Rockchip 刷写策略扇区参数化**：`builder/flash.py` 的 `RockchipFlashStrategy.write_gpt` 把 `sector=512` 改为读 `partitions.sector_size`，GPT header/entries 截取偏移按 4K 重算；保留 `upgrade_tool DB→WL→write_gpt` 流程不变（不新增整盘 dd 策略）。
- **新增知识库条目** `wiki/boards/radxa-rock-4d.md`（项目惯例）。
- **不动内核与 SoC 层**：Spike A 已确认 `linux-6.1-stan-rkr5.1` 树内含 `rk3576-rock-4d.dts`（已 `&ufs status="okay"`）、`rk3576.dtsi` 含 `rockchip,rk3576-ufs` 节点、base defconfig `rockchip_linux_defconfig` 已开 `CONFIG_SCSI_UFSHCD/_PLATFORM/SCSI_UFS_ROCKCHIP/_BSG/_HWMON`，board 层只需写 dts 名，内核与 SoC defconfig 零改动。
- ~~**不动 bootloader 构建**：`builder/platforms/rockchip/bootloader.py` 无须改动。~~ **（实施期已推翻）** 自编 idbloader 缺 `rk3576_boost` 导致崩 UFS，`bootloader.py` 新增 `prebuilt_spi_image` 分支（prebuilt 时跳过自编、只产 DB 用 miniloader）；详见 design Decision 6。

## Capabilities

### New Capabilities
（无 —— 不引入新 capability。ROCK 4D 板级支持与 UFS 4K 扇区行为均归入既有 `rockchip-platform` 契约，与 RK3576 SoC 发现、GPU fragment 选型同处一篇规范。）

### Modified Capabilities
- `rockchip-platform`: 新增三条 requirement —— (1) Rockchip 平台支持 Radxa ROCK 4D 板级配置（UFS、板级 UFS defconfig、UFS 分区布局）；(2) Rockchip 镜像组装按 `partitions.sector_size` 支持 4096 字节 UFS 扇区（含 rootfs EFI Type-UUID 规避）；(3) Rockchip 刷写策略按 `partitions.sector_size` 参数化 GPT 写入。

## Impact

- **代码层**：
  - `builder/platforms/rockchip/image.py` — 扇区从写死 512 改读 `partitions.sector_size`，移植 `losetup -b` + offset 重算 + rootfs EFI Type-UUID（约 30 行，参照 `qualcommqcs6490/image.py`）。
  - `builder/flash.py` `RockchipFlashStrategy.write_gpt` — `sector` 改读 config，GPT 截取按 4K 重算（约 10 行）。
- **内容层**：
  - 新增 `components/board/radxa-rock-4d/config.py`。
  - 不改 `components/platform/rockchip/rk3576/config.py`（SoC 层仍为 eMMC 默认布局，UFS 由 board 层覆盖；未来可挂 eMMC 板）。
- **外部依赖**（Spike 已核实）：
  - argon kernel `linux-6.1-stan-rkr5.1` 含 `rk3576-rock-4d.dts`（已入 Makefile，UFS 已 okay）与 `rockchip,rk3576-ufs` 驱动。
  - `radxa/u-boot next-dev-v2026.01` 含板级 `rock-4d-rk3576_defconfig`（UFS 全套）+ `drivers/ufs/ufs-rockchip*.c`。
  - `radxa/rkbin develop-v2026.01` 通用 RK3576 loader 内含 UFS 初始化。
- **回归范围**：现有 RK3566/RK3588 等 eMMC/SD 板必须验证 `image.py` 默认 512B 路径产物与 `write_gpt` 行为不变（`sector_size` 缺省即 512）。
- **下游兼容**：lunch target `radxa-rock-4d-default-debug` / `-release` 经现有 product/variant 机制自动生成，无 CLI 改动。

## Non-Goals

- **不**为 ROCK 4D 启用 HDMI / GPU (Mali-G52, panfrost 已在 SoC fragment) / NPU / VPU 之外的显示与多媒体验收：首版只做"串口 + SSH"最小启动。
- **不**支持 eMMC / SD / SPI NOR 启动：本次仅 UFS（用户明确 UFS-only）；SoC 层 eMMC 默认布局保留但不在本变更验收。
- **不**适配 M.2 / PCIe 等 AIC8800 以外的无线方案：板载 WiFi/BT 已纳入（AIC8800D80 USB，见 What Changes）；其余无线外设后续按需。
- ~~**不**新增整盘 `dd` 刷写策略~~ **（实施期已变更）**：UFS 走 `upgrade_tool di -p parameter.txt`（让 loader 按设备 LBA 建 GPT），`flash.py` 已落地 `flash_whole_disk` 路径（非 dd，仍是 `upgrade_tool`）；与「保留 upgrade_tool 路线」初衷一致。
- ~~**不**改 `builder/platforms/rockchip/bootloader.py`、`rk3576/config.py`~~ **（实施期已变更）**：两者均有改动（bootloader prebuilt 分支、SoC 注释订正）；内核源/分支、SoC defconfig 仍零改动。
- **不**引入 SoC 家族中间继承层或 storage 维度抽象：UFS-ness 以 board 层 `partitions` 覆盖表达，deep_merge 已足够。

## Open Risks（须上板实测，不阻塞实施）

- `upgrade_tool WL <offset>` 在 4096B UFS 设备上的 offset 单位（512 扇区 vs 4K LBA）/ 是否自适应查询 LBA 大小 —— 决定 `write_gpt` 4K 重算是否正确。
- maskrom + `rk3576_usbplug` 经 USB 写 UFS 是否真能成功（无公开成功先例）；若失败则回退 SD 启动后 `dd /dev/sda` 路径（另起变更）。
- 按 4096B + rootfs EFI Type-UUID 构建的 `raw.img` 在板上 GPT 能否被 BootROM/U-Boot/内核正确识别。
