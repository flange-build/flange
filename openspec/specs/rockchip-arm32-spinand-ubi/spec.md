# rockchip-arm32-spinand-ubi Specification

## Purpose
TBD - created by archiving change add-rk3506b-atk-rk3506b. Update Purpose after archive.
## Requirements
### Requirement: Rockchip 组件架构与交叉编译器由配置决定

Rockchip kernel 与 bootloader builder SHALL 从 FINAL_CONFIG 读取组件 `arch`、
`cross_compile`、内核 image 名称和 DTS 目录，不得把 AArch64 路径作为所有 Rockchip SoC 的
固定值。未声明新字段的既有配置 MUST 保持 `arm64`、AArch64 gcc-10、`Image` 和
`arch/arm64/boot/dts/rockchip` 的现有行为。

#### Scenario: ARM32 配置选择正确工具链与路径
- **WHEN** 合并配置包含 `arch=armhf`、`kernel.arch=arm`、
  `kernel.cross_compile=/opt/arm-linux-gcc10/bin/arm-none-linux-gnueabihf-` 和空
  `kernel.dts_dir`
- **THEN** kernel builder 使用 `ARCH=arm` 和配置声明的固定 gcc-10.3.1 前缀
- **AND** 从 `arch/arm/boot` 与 `arch/arm/boot/dts` 构建并收集目标文件

#### Scenario: 既有 ARM64 默认行为不变
- **WHEN** 构建未声明组件架构覆盖的现有 Rockchip ARM64 target
- **THEN** 其 make 参数、DTS 路径和 `Image` 产物与变更前一致

### Requirement: ARM32 vendor FIT boot 可配置构建

当 `kernel.boot_format=fit` 时，Rockchip kernel builder SHALL 使用内核仓库声明的
`kernel.boot_its` 和目标 DTS 调用 vendor FIT 生成路径，产出包含 ARM32 `zImage`、FDT 与
resource 的 `boot.img`。该模式 SHALL NOT 生成 extlinux 配置或 ext4 boot 文件系统。

#### Scenario: RK3506 ARM32 FIT 产出正确
- **WHEN** 构建启用 `kernel.boot_format=fit`、`kernel.image=zImage` 和
  `kernel.boot_its=boot.its` 的 target
- **THEN** `boot.img` 是合法 FIT
- **AND** FIT kernel 节点架构为 `arm`，FDT 为所选 RK3506B DTB

#### Scenario: FIT 模式保留 DTS bootargs
- **WHEN** FIT target 的 DTS `chosen.bootargs` 声明 UBI rootfs
- **THEN** 平台补丁不得抑制或覆盖该 bootargs
- **AND** extlinux 专用 bootargs merge 策略不应用于该 target

### Requirement: armhf rootfs 可打包为 UBI

当 `rootfs.image_format=ubi` 时，rootfs builder SHALL 注入 `qemu-arm-static` 构建 armhf
Ubuntu Base，并使用 `mkfs.ubifs` 和 `ubinize` 生成 `rootfs.ubi`。配置 MUST 显式提供
`min_io_size`、`peb_size`、`subpage_size`、`vid_hdr_offset` 与 volume 容量；缺失或不自洽时
配置校验 MUST 失败。若布尔配置 `rootfs.ubi.space_fixup=true`，builder SHALL 向
`mkfs.ubifs` 追加 `-F`，用于无法跳过全 `0xFF` page 的 NAND 刷写器。

#### Scenario: UBI volume 名与内核参数一致
- **WHEN** UBI rootfs 构建成功
- **THEN** UBI 内包含名为 `rootfs` 的 UBIFS volume
- **AND** 该 volume 可由 `root=ubi0:rootfs rootfstype=ubifs` 挂载

#### Scenario: 禁止猜测 NAND 几何
- **WHEN** target 选择 UBI 但未声明完整 NAND 几何
- **THEN** 构建在调用 `mkfs.ubifs` 前失败
- **AND** 错误列出缺失的几何字段

#### Scenario: UBI 镜像容量越界被拒绝
- **WHEN** UBIFS/UBI 产物超过 rootfs MTD 分区的可用容量或预留余量
- **THEN** 构建失败且不得截断镜像

#### Scenario: SPI NAND 首次挂载修复空闲空间
- **WHEN** ATK-RK3506B 声明 `rootfs.ubi.space_fixup=true`
- **THEN** `mkfs.ubifs` 命令包含 `-F`
- **AND** 刷入镜像后首次挂载可完成 free-space fixup 并保持可写

### Requirement: Ubuntu systemd 具备最小 API 文件系统支持

使用 Ubuntu Base/systemd 的 rootfs builder SHALL 创建 `/proc`、`/sys`、`/sys/fs/cgroup`、
`/dev`、`/run` 与 `/tmp` 等启动早期挂载点；对应 target kernel SHALL 至少启用
`CONFIG_CGROUPS=y`。512 MiB target MAY 不启用 `MEMCG`，以控制常驻内存开销。

#### Scenario: systemd 挂载 API 文件系统
- **WHEN** Linux 已从 `ubi0:rootfs` 启动 `/sbin/init`
- **THEN** systemd 可挂载 cgroup API 文件系统
- **AND** 不因 `Failed to mount API filesystems` 冻结执行

### Requirement: SPI NAND 复用 GPT 配置并按分区安全刷写

当 `storage.type=spinand` 时，board SHALL 使用与既有 RK3566 一致的
`partitions.format=gpt`/`partitions.entries` 模型。构建系统 SHALL 从这些 entries 生成
`TYPE: GPT` 的 `parameter.txt` 与具名刷写 manifest；刷写系统 MUST 使用 `DI -p` 与具名 DI
分区写入，不得生成或写入整片 `raw.img`。`flash_storage`
SHALL 仅用于支持 `SSD` 的多介质 loader；单介质 SPI NAND loader MAY 不配置该 selector。

#### Scenario: GPT 配置生成 SPI NAND parameter
- **WHEN** 完整构建 SPI NAND target
- **THEN** `parameter.txt` 由最终 `partitions.entries` 生成
- **AND** 其分区名称、offset 与 size 和 FINAL_CONFIG 一致

#### Scenario: GPT 分区超出 512 MiB 被拒绝
- **WHEN** 生成 parameter 的末分区边界超过板级 512 MiB 存储容量
- **THEN** 配置或构建校验失败并报告越界分区

#### Scenario: SPI NAND 不生成逻辑 raw.img
- **WHEN** 对 SPI NAND target 执行 `flange flash`
- **THEN** 构建产物使用 parameter、manifest 与具名分区镜像
- **AND** 不存在整片 `raw.img`，也不调用 NAND `dd` 或等价 raw 写入

#### Scenario: 单介质 SPI NAND 无需存储 selector
- **WHEN** `storage.type=spinand` 且未配置 `flash_storage`
- **THEN** 仍生成 parameter 并进入具名 DI 路由
- **AND** 不因缺少 `upgrade_tool SSD` capability 而拒绝刷写

### Requirement: 产物缓存按构建路由校验

缓存系统 SHALL 根据最终配置解析每个组件的必需产物。ext4 与 UBI rootfs 路径 SHALL 使用
不同的 rootfs 必需产物集合；块设备 GPT image 要求 `raw.img`，SPI NAND image 要求
`mtd-bundle.json` 与 `parameter.txt`。FIT kernel SHALL 要求精确目标 DTB 与 `boot.img`。
任一路径缺失其必需文件时缓存 MUST 判定为失效。

#### Scenario: UBI target 缺 rootfs.ubi 时重建
- **WHEN** UBI target 的缓存元数据存在但 `rootfs.ubi` 缺失
- **THEN** rootfs 缓存判定失效并重新构建

#### Scenario: ARM64 target 仍要求既有产物
- **WHEN** 检查现有 GPT/ext4 Rockchip target 缓存
- **THEN** 仍按现有契约校验 `Image`、`rootfs.img` 与 `raw.img`
