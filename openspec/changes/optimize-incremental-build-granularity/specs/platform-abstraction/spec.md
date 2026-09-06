## ADDED Requirements

### Requirement: rootfs 构造编排 SHALL 只有一份实现

rootfs 的四相编排（Phase 1 base 快照 → Phase 2 customize → fstab 与 API 挂载点 → 成像）SHALL 由 `RootfsBuilder` 基类唯一实现。平台 MUST NOT 复制整段 `compile` / `_build_phase1` / `_build_phase2`，差异一律通过声明位表达：

- `FSTAB_MOUNTS` / `_fstab_mounts(config)`：挂载项；空表示该 rootfs 不由 fstab 挂载
- `_post_customize(rootfs_dir, config)`：Phase 2 之后、写 fstab 之前的钩子
- `_build_image(rootfs_dir, config)`：成像方式，默认 ext4

抄件漂移的代价不是重复，而是基类新增的能力接不上抄件 —— 曾出现 `rootfs.emulator`、`rootfs.extra_apt_sources`、API 挂载点三项在多数平台上静默无操作：配置写了不报错，也不生效。

#### Scenario: 新增平台

- **WHEN** 新平台的 rootfs 构造与默认编排一致
- **THEN** 它的 rootfs builder 只需声明组件身份，不需要实现任何编排方法

#### Scenario: 基类新增能力

- **WHEN** 基类新增一项 rootfs 能力
- **THEN** 全部平台自动获得该能力，不需要逐个平台补接线

#### Scenario: 平台有真实差异

- **WHEN** 平台需要不同的挂载模型或成像方式（如 UBI 由 kernel bootargs 挂载 root）
- **THEN** 通过覆写对应声明位表达，而不是复制整段编排

### Requirement: 产物目录 SHALL 以注入的 cache 为锚点

构造器解析 target 产物目录（app deb、内核模块等上游产物）时 MUST 使用 engine 注入的 cache，MUST NOT 使用 cwd 相对字面量或模块级路径常量 —— 前者只在仓库根启动时才正确，后者不跟随注入的 project_root。缺少该锚点 SHALL 明确失败，而不是回退到某个可能为空的路径：app deb 与内核模块都从这里取，静默取不到会产出缺少它们的残缺镜像。

#### Scenario: 非仓库根启动

- **WHEN** 构建在非仓库根目录发起
- **THEN** 上游产物仍被正确定位

#### Scenario: 缺少 cache 注入

- **WHEN** 构造器未被注入 cache 而尝试解析产物目录
- **THEN** 构建以明确的错误终止，而不是产出残缺镜像

### Requirement: 额外 APT 源 SHALL 先安装 CA 证书

启用 `rootfs.extra_apt_sources` 时，框架 SHALL 先用官方源在 chroot 内安装 `ca-certificates` 并生成证书 bundle，再写入额外源并重新 `apt-get update`。ubuntu-base 最小系统不带 CA 证书，直接写 HTTPS 源会让后续 update 卡在证书验证上。该行为 SHALL 对全部平台一致。

#### Scenario: 声明 HTTPS 额外源

- **WHEN** 任一平台的配置声明了 `rootfs.extra_apt_sources`
- **THEN** 构建先安装 CA 证书，再写入源并重新 update，随后的包安装可用该源

### Requirement: 整盘镜像装配 SHALL 只有一份实现

按分区表把前序产物装配成整盘镜像的逻辑（算总容量 → 建空镜像 → 写 GPT → 逐分区 dd）SHALL 由 `GptImageBuilder` 基类唯一实现。平台差异通过三个声明位表达：`PARTITION_IMAGES` / `_partition_images(config)`（分区名到产物路径的映射与按配置的路由）、`ROOTFS_PARTUUID`（供 kernel cmdline 引用的固定 PARTUUID）、`_gpt_partition_ops(...)`（ESP 标记、Type-UUID 伪装等启动固件 quirk）。

`raw` 类型的分区表示"这块区域不是文件系统，直接 dd 裸数据"，因此 MUST NOT 进入 GPT 分区表 —— 这条规则对所有平台一致。

分区镜像 dd MUST 使用稀疏写入：rootfs 镜像的声明尺寸远大于实占，写全零块既慢又让整盘镜像失去稀疏性。

#### Scenario: raw 分区

- **WHEN** 分区表含 `raw` 类型条目
- **THEN** 该条目不出现在 GPT 分区表中，但其镜像仍按偏移 dd 进整盘镜像

#### Scenario: 非 512 字节扇区

- **WHEN** `partitions.sector_size` 声明为 4096
- **THEN** GPT 经 loop 设备按目标 LBA 写入，且 config 中以 512B 为单位的偏移被换算到目标扇区

#### Scenario: 不产整盘镜像的介质

- **WHEN** 目标是 SPI NAND（OOB / ECC / 坏块无法用整片镜像表达）
- **THEN** 平台改为产出分区表与具名分区刷写清单，而不是 raw.img
