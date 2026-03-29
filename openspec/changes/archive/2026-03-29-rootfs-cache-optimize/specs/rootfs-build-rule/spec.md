## REMOVED Requirements

### Requirement: rootfs_build 框架 rule 定义
**Reason**: 原 `rootfs_build` 单体 rule 已拆分为 `rootfs_base`（base 系统构建）和 `rootfs_customize`（定制化）两个独立 rule
**Migration**: 使用 `rootfs_base` + `rootfs_customize` 替代

### Requirement: rootfs_build 环境变量契约
**Reason**: 环境变量契约已分别由 `rootfs_base` 和 `rootfs_customize` 各自定义
**Migration**: 参见 rootfs-base-rule 和 rootfs-customize-rule 的环境变量契约

### Requirement: rootfs_build 产出 rootfs.tar.gz
**Reason**: 产出由 `rootfs_customize` rule 负责
**Migration**: `rootfs_customize` rule 产出 `rootfs.tar.gz`

### Requirement: rootfs_build 使用 no-sandbox 执行
**Reason**: 执行要求已分别在两个新 rule 中定义
**Migration**: `rootfs_base` 和 `rootfs_customize` 均使用 `no-sandbox` 执行

### Requirement: rootfs_source repository rule
**Reason**: rootfs_source 不变，保留原样
**Migration**: 无需迁移
