## Context

flange RK3576 SoC 配置已就位（`components/platform/rockchip/rk3576/config.py`，内核 `linux-6.1-stan-rkr5.1` + panfrost、bootloader `radxa/u-boot next-dev-v2026.01` + 通用 `rk3576_defconfig`、rkbin `develop-v2026.01`、`mkimage_chip=rk3576`、UART0 console），但其 `partitions` 沿用 RK3588 的 **512 字节扇区 eMMC 布局**。

Radxa ROCK 4D 实板用 **UFS 存储**，逻辑块大小 **4096 字节**。这与两处平台代码的硬编码冲突：

- `builder/platforms/rockchip/image.py`：`SECTOR_SIZE = 512` 写死，GPT 用 `parted` 直接对 regular file 操作（默认 512-LBA）。
- `builder/flash.py` `RockchipFlashStrategy.write_gpt`：`sector = 512` 写死，从 `raw.img` 的 `LBA 1 × 512` 截 `33 × 512` 字节回写 `WL 1`。

同平台的 Qualcomm qcs6490 已有 UFS 4K 先例可借鉴：`builder/platforms/qualcommqcs6490/image.py` 用 `losetup -b <sector_size> -f --show` 把 `raw.img` 挂成报告 4K LBA 的 loop 设备，`parted`/`sgdisk` 据此写 4K 对齐 GPT；并把 config 中以 512 字节为单位的 offset/size 重算为目标扇区（`off_512 × 512 ÷ sector_size`）。

外部依赖（两个 Spike 已核实）：

| 资源 | 仓库@分支 | 关键事实 |
|---|---|---|
| kernel | `argon/kernel.git @ linux-6.1-stan-rkr5.1` | 含 `rk3576-rock-4d.dts`（已入 Makefile，`&ufs status="okay"` + reset-gpio）；`rk3576.dtsi` 含 `ufs@2a2d0000` / `rockchip,rk3576-ufs`（SoC 默认 disabled）；base defconfig `rockchip_linux_defconfig` 已开 `CONFIG_SCSI_UFSHCD/_PLATFORM/SCSI_UFS_ROCKCHIP/_BSG/_HWMON`；UFS 无独立 regulator 依赖 |
| u-boot | `radxa/u-boot @ next-dev-v2026.01` | 板级 `rock-4d-rk3576_defconfig` 含 `CONFIG_UFS/ROCKCHIP_UFS/SPL_UFS_SUPPORT` + `drivers/ufs/ufs-rockchip*.c`；通用 `rk3576_defconfig` 不开 UFS |
| rkbin | `radxa/rkbin @ develop-v2026.01` | 无 UFS 专用 loader；通用 `rk3576_spl_loader`/SPL/usbplug 内含 UFS 初始化 |

实板硬件：Radxa ROCK 4D（RK3576，4×A72 + 4×A53，Mali-G52，板载 64-pin eMMC/UFS combo 模组槽，本变更只走 UFS 模组，UART0 调试串口 1500000bps）。

## Goals / Non-Goals

**Goals:**

- 新增 board `radxa-rock-4d`，绑定 `soc=rk3576`、`dts=rk3576-rock-4d`，board 层覆盖 `bootloader.defconfig=rock-4d-rk3576_defconfig` 与 `sector_size=4096` 的 UFS 分区布局。
- 让 Rockchip 镜像组装与刷写按 `partitions.sector_size` 参数化，4096B UFS 与 512B eMMC/SD 共存，默认 512 保持现有板产物/行为不变。
- 完成 ROCK 4D 首版"串口 + SSH"验证链路（maskrom → 刷写 → U-Boot/kernel 串口 banner → systemd → sshd）。

**Non-Goals:**

- 不动内核源/分支、SoC defconfig、`rk3576/config.py`、`bootloader.py`。
- 不新增整盘 `dd`/`flash_whole_disk` 策略（保留 `upgrade_tool` 路线，上板实测后再定）。
- 不为 ROCK 4D 验收 HDMI/NPU/VPU；不支持 eMMC/SD/SPI 启动。板载 WiFi/BT 走
  AIC8800D80 USB（radxa-pkg/aic8800 OOT，与 rock5c-lite/cubie 同源），纳入范围。
- 不引入 storage 维度抽象或 SoC 家族中间层。

## Decisions

### Decision 1: UFS-ness 放 board 层 `partitions` 覆盖，SoC 层保持 eMMC 默认

**选择**：`rk3576/config.py` 的 `partitions`（512B eMMC 布局）不动；`radxa-rock-4d/config.py` 整块覆盖 `partitions` 为 `sector_size=4096` 的 UFS 布局。

**理由**：

- 存储介质是**板级**属性 —— 同一 RK3576 SoC 既可挂 UFS 也可挂 eMMC（ROCK 4D 是 combo 槽）。把 4K 布局钉死在 SoC 层会污染未来的 eMMC 板。
- flange 的 deep_merge 三层继承（platform → SoC → board）天然支持 board 整块覆盖 `partitions`，无需新机制。
- 避免引入显式 "storage" 维度（如 variant/product）—— 当前只有一种介质需求，YAGNI。

**备选**：

- *SoC 层改成 UFS* — 破坏 SoC 通用性，未来 eMMC 板被迫再覆盖回去。
- *新增 storage 维度（如 `radxa-rock-4d-ufs` product）* — 过度设计；单介质场景下 product 笛卡尔积纯属负担。

### Decision 2: image.py 扇区参数化 —— 移植 qcs6490 的 `losetup -b` + offset 重算范式

**选择**：`RockchipImageBuilder` 把 `SECTOR_SIZE = 512` 类常量改为 `self._sector = int(partitions.get("sector_size", 512))`；当 `sector != 512` 时走 `losetup -b <sector> -f --show` + `parted`（参照 qcs6490 `image.py`），并把 config 的 512B 单位 offset 重算为目标扇区；`dd` 用 `bs=<sector>`、`seek=<重算后扇区>`。默认 512 路径**保持现有 `parted ... <byte>B` + `dd bs=512` 不变**，现有板 byte-identical。

**理由**：

- qcs6490 已验证此范式能在 4K UFS 上产出 BootROM/UEFI 可识别的 GPT；同仓库内一致优于另造轮子。
- `sector_size` 缺省 512 是天然的向后兼容开关，回归面收敛到"config 不声明 sector_size 即旧行为"。

**备选**：

- *为 rockchip 单独写一个 UFS image builder 子类* — 与 qcs6490 重复，且 `image_select_routing` 已按 platform 选 builder，难以再按 SoC/storage 二次分发。
- *`sgdisk --sector-size`* — 实测 util-linux 2.39 / sgdisk 1.0.10 不支持（qcs6490 注释已记录），故走 loop 设备。

### Decision 3: rootfs 分区 Type-UUID 在 4K 路径设为 EFI System GUID

**选择**：当 `sector == 4096` 时，把 rootfs 分区的 **Type-UUID** 设为 `C12A7328-F81F-11D2-BA4B-00A0C93EC93B`（EFI System Partition GUID）。现有 512B 路径用的固定 **PARTUUID** `614e0000-...`（供 kernel cmdline `root=PARTUUID=` 引用）保持不变。

**理由**：

- Armbian 在 rk35xx + 4096B 扇区上实证：rootfs Type-UUID 须伪装成 EFI System GUID 才能规避 bootloader quirk（否则工具/固件"看不到目标"）。
- Type-UUID（分区类型）与 PARTUUID（分区唯一标识）是两个独立字段；改 Type-UUID 不影响 `root=PARTUUID=` 的引用路径。

**风险关联**：board 的 `kernel_args` rootfs 引用方式须与之自洽 —— 详见 Open Questions。

### Decision 4: flash 保留 `upgrade_tool` WL/write_gpt，仅参数化扇区（不新增 dd 策略）

**选择**：`RockchipFlashStrategy.write_gpt` 的 `sector = 512` 改为读 `config.partitions.sector_size`，GPT header/entries 截取偏移按该扇区重算；`pre_flash`（DB miniloader）、`write_partition`（WL）、`reboot`（RD）流程不变。**不**覆盖 `flash_whole_disk`。

**理由**：

- 用户决策：`upgrade_tool` 理论上支持 UFS，固件构建出来后上板实测即可，不预先引入 dd 整盘策略增加范围。
- 保留单一 Rockchip 策略，避免现在就给 flash 注册表加 SoC/board 粒度分发（那是 dd 方案才需要的结构改动）。

**备选**（仅作记录，本变更不实施）：

- *仿 qcs6490 覆盖 `flash_whole_disk` 走 dd /dev/sda* — 有公开成功先例，但需 flash 注册表加 SoC/board 粒度 + 先 SD 启动 + 防误写宿主盘。留作 `upgrade_tool` 实测失败后的回退变更。

### Decision 5: board defconfig 覆盖为 `rock-4d-rk3576_defconfig`；dts 直接用 `rk3576-rock-4d`

**选择**：board 层 `bootloader.defconfig` 覆盖 SoC 层通用 `rk3576_defconfig` 为板级 `rock-4d-rk3576_defconfig`；`kernel.dts = "rk3576-rock-4d"`。

**理由**：通用 `rk3576_defconfig` 不含 UFS（`CONFIG_UFS/ROCKCHIP_UFS/SPL_UFS_SUPPORT`），SPL 无法从 UFS 加载 u-boot proper；板级 defconfig 已含全套。dts Spike A 已确认在内核树且 UFS 已 okay。

> ⚠️ **本 Decision 已被 Decision 6 实板推翻** —— defconfig/自编路线无法产出能读 UFS 的 u-boot；改用 bsp 预编 spi.img。

### Decision 6: bootloader 改用 radxa bsp 预编 spi.img —— 自编拼装无法复现官方可用整体（实板推翻 Decision 5）

**实板结论（6 次上板坐实）**：flange 用 `bootloader.py` 逐件拼装 u-boot 组件，u-boot proper 读 UFS 一律在 `part_get_info_efi` 崩（`GPT signature wrong` + `Synchronous Abort`；UFS link up 到 gear3 但 SCSI READ 数据没 DMA 进 buffer、读到内存残渣 `0xFDC1xxxx`）。注：5 个 v2026.01 变体崩在 **EL2**（PC `40226fa8`，BL31 在位、问题在 UFS 数据通路）；唯一的 v2024.10 变体（④）因 `decode_bl31.py` python2 shebang 致 BL31 拆解失败、漏出 itb，崩在 **EL3**（PC `40226bf4`）——两类崩溃**机理不同**，早期把它们混为「同一个 PC」是误读。逐变量排除：

| 变量 | 试过的值 | 结果 |
|---|---|---|
| UFS 驱动代码 | v2026.01 vs v2024.10（对 Samsung 仅差 2 行无关厂商 quirk） | 同源，非根因 |
| u-boot 分支 | v2026.01 / v2024.10 | v2026.01 崩 EL2；v2024.10(④) 崩 EL3（BL31 漏，非同一故障）→ 分支轴被污染、不可判定 |
| defconfig | rock-4d-rk3576 / rock-4d-spi（disable sdhci） | 均崩（sdhci 与 ufs 时钟/复位/电源/引脚独立） |
| OP-TEE | 有 / 无（patch 0006 toggle） | 均崩 |
| BL31 | v1.24 / v1.20 / **真 v1.19** | 均崩 |
| DDR | 三者同 v1.10 | — |
| **idbloader 打包** | 6 变体**全部** `mkimage -T rksd`（缺 `rk3576_boost`） | **从未变更 —— 与上表所有变量正交，这才是真正的共因** |

**连与官方 spi.img sha256（`252c9db0…`）/版本串（`gf3570ca5d`）完全一致的 v1.19 BL31（radxa/rkbin `e8ded82`）配 flange v2026.01 拼装仍崩**；而官方 radxa bsp 整体编的 spi.img（u-boot v2024.10 rk2410 + BL31 v1.19）能正常启动同一块板上 flange 刷的 UFS 镜像。

**根因（构建链路审计定位，2026-06 复盘）**：RK3576 的 idbloader **必须**用 `boot_merger` 按 `RK3576MINIALL.ini` 装配（含 `rk3576_boost` / `usbplug` 组件）；flange 通用路径用 `mkimage -T rksd -d ddr:spl` —— 而 RK35xx 里 **RK3576 是唯一不走 mkimage** 的 SoC（armbian `rockchip64_common.inc:232-247` 对 `BOOT_SOC==rk3576` 专走 boot_merger 分支，其余 RK35xx 才走 else 的 mkimage rksd）。flange 自编 idbloader **缺 boost**、头布局非 BootROM 对 RK3576 的预期 → SPL 运行环境不完整 → UFS 链路能 up 到 gear3 但 SCSI 不回数据。上表 6 次上板**全部建立在这条 mkimage 路径上（从未变更）**，与所有被扰动的变量正交——这才是真正的共因，与 BL31/OPTEE/分支均无关。

**选择**：理论上在 flange 复刻 boot_merger + `rk3576_boost` 的打包流程即可自编（列为 future work，见 proposal 后续）；当前先用已验证可用的 board 级 `bootloader.prebuilt_spi_image`：flange 不自编 u-boot，直接刷 radxa bsp 预编的 spi.img。`bootloader.py` configure/compile/collect 在 prebuilt 时跳过自编、只产 DB 用 miniloader；`flash.py` 直接刷预编 spi.img（`flash_spi_loader`/`bl31_override`/`idbloader_spl` 等自编调试键全部撤除）。**Decision 5 的 board defconfig 自编路线作废。**

**预编来源**：spi.img 构建期从 radxa 官方下载（`bootloader.prebuilt_spi_image = {url, sha256}`，`SourceManager.ensure_prebuilt_image` 原子下载 + sha256 校验、缓存到 `.build/sources/prebuilt`，**不入库 16MB blob**）。URL `https://dl.radxa.com/rock4/4d/images/rock-4d-spi-flash-image.img`（下载页 docs.radxa.com/en/rock4/rock4d/download），sha256 `b4f3686a…`（实测与本地验证可用产物逐字节一致）。**复现/自编**：`./bsp u-boot rk2410 rock-4d-spi`（其 rkbin 须含 v1.19 BL31，commit `e8ded82`；当前 bsp pin 已 v1.24，须手动回退——但 BL31 版本不影响能否启动）。

**正面收获**：这一长串排除反证 **UFS 侧 flange 全对** —— image / 4K·512 GPT / extlinux / `root=PARTLABEL=rootfs`（实板验证可用，关闭 Open Question 1）/ kernel / rootfs / dwc3-otg overlay，官方 spi.img 能完整启动它们。问题收敛在 bootloader 的 idbloader 打包（boot_merger / `rk3576_boost`，见上）—— 已非黑盒。

## Risks / Trade-offs

- **`upgrade_tool WL <offset>` 在 4K UFS 上的 offset 单位 —— 实板已定论：恒为 512 字节。** 首版 `write_gpt` 误把 GPT 逻辑 LBA(1) 当 WL 偏移，4K 上 header 被写到 byte 512，u-boot 在 byte 4096(4K-LBA1) 读到垃圾 → `GPT Header signature is wrong` → abort（实板日志佐证：BL31/OP-TEE/u-boot/UFS link 全 OK，唯 GPT 解析炸）。已修：`_gpt_wl_offset(sector) = GPT_HEADER_LBA × sector ÷ 512`（512→1 回归安全，4096→8=byte 4096）。逐分区 WL（idbloader 0x40→byte32K 等）本就是 512 单位，无需改。待重烧验证。
- **maskrom + `rk3576_usbplug` 经 USB 写 UFS 无公开成功先例** → 先按现有 DB→WL 链路实测；失败转 SD 启动 + dd /dev/sda。
- **4096B + rootfs EFI Type-UUID 的 raw.img 板上 GPT 能否被 BootROM/U-Boot/内核识别** → 依赖 Decision 2/3 与 Armbian 实证一致；上板验证 U-Boot 能枚举 UFS、内核能挂 rootfs。
- **回归：image.py / flash.py 改动波及所有 Rockchip 板** → `sector_size` 缺省 512 保持旧路径；用现有 RK3566/RK3588 板的 image 单测 + 产物对比兜底。

## Migration Plan

1. 实施 image.py / flash.py 扇区参数化（默认 512 不变），单测覆盖 512 与 4096 两条路径。
2. 新增 `radxa-rock-4d/config.py`，`flange build radxa-rock-4d-default-debug` 产出 4096B `raw.img`。
3. 上板：maskrom → `flange flash` → 串口观察 U-Boot/kernel banner → systemd → sshd。
4. **回滚**：本变更对现有板零行为改变（`sector_size` 缺省 512）；ROCK 4D 失败仅影响该新板，不波及其他平台/板。

## Open Questions

- ROCK 4D 的 `boot.kernel_args` 中 rootfs 引用：沿用 SoC 层 `root=PARTUUID=614e...`（需镜像端把该 PARTUUID 写到 rootfs 分区，与 Decision 3 的 Type-UUID 伪装并存），还是改用 `root=PARTLABEL=rootfs`？上板前需确认 U-Boot extlinux 解析与 4K GPT 下 PARTUUID/PARTLABEL 的可用性。
- UFS 分区布局的 boot/recovery/rootfs 起始扇区与大小：先按 SoC 层 512B 布局等比例换算到 4K（保持字节偏移一致），还是采用 Radxa `_4096` 官方镜像的布局？倾向前者（最小改动），实测确认。
- recovery 分区是否在 ROCK 4D 首版保留（SoC/platform 默认 `recovery.enabled=True`，需 partitions 提供 recovery entry）—— 保留以满足 `validate_config`，除非存储紧张。
