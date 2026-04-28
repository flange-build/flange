## MODIFIED Requirements

### Requirement: A733 Rootfs 构建
`AllwinnerA733RootfsBuilder` 必须（SHALL）复用 `RootfsBuilder` 基类的通用能力（overlay、firmware、两阶段缓存），
生成 ext4 rootfs.img。若 rootfs 分区 entry 声明 `image_size`，构建器必须（MUST）使用 `image_size`
作为 rootfs.img 的初始大小；若未声明，则保持现有兼容大小策略。

#### Scenario: rootfs 构建流程
- **WHEN** 执行 `allwinnera733` 平台的 rootfs 构建
- **THEN** 完成 Phase 1 (base tarball + apt install) 和 Phase 2 (custom deb + overlay + firmware + 密码设置)，输出 ext4 rootfs.img

#### Scenario: rootfs 使用 image_size
- **WHEN** `allwinnera733` 平台 rootfs 分区配置为 `size: "remaining"` 且 `image_size: "2G"`
- **THEN** `AllwinnerA733RootfsBuilder` 生成 2GB 的 ext4 rootfs.img

### Requirement: A733 整盘镜像组装
`AllwinnerA733ImageBuilder` 必须（SHALL）将 bootloader 固件和分区镜像按 SD 卡分区表布局组装成 raw.img。
若 rootfs 分区 entry 声明 `image_size`，raw.img 中 rootfs GPT 分区初始大小必须（MUST）使用 `image_size`；
`size: "remaining"` 仅表示设备首次启动扩容后的最终容量语义。

#### Scenario: SD 卡镜像组装
- **WHEN** 执行 `allwinnera733` 平台的 image 构建
- **THEN** raw.img 中 boot0_sdcard.bin 写入 sector 256，boot_package.fex 写入 sector 24576，boot.img 和 rootfs.img 写入对应分区 offset

#### Scenario: GPT 分区表
- **WHEN** raw.img 生成完成
- **THEN** 非 raw 类型分区在 GPT 分区表中有对应条目

#### Scenario: rootfs GPT 分区使用 image_size
- **WHEN** `allwinnera733` 平台 rootfs 分区配置为 `size: "remaining"` 且 `image_size: "2G"`
- **THEN** raw.img 中 rootfs GPT 分区初始大小为 2GB
- **AND** raw.img 总大小按初始分区布局计算
