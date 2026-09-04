## Why

当前 RootfsBuilder 在默认用户之前以普通 GID 创建 `i2c`、`spi`、`gpio` 等附加组，导致默认用户虽取得 UID 1000，其同名用户私有组却漂移到 GID 1003。flange 的 Ubuntu Desktop 产品应遵循干净安装的账号模型，并把已有的 `/run/user/1000` 运行时假设收敛为明确、可验证的构建契约。

## What Changes

- 将 `rootfs.groups` 中缺失的附加组创建为 system group（系统组），避免占用普通用户的 GID 段。
- 固定 `default_user` 使用 UID 1000，并使用同名、GID 1000 的 user private group（用户私有组）；编号被占用时直接构建失败，禁止静默漂移。
- 其他声明式用户继续由 Ubuntu `useradd` 按普通用户编号范围自动分配。
- 增加最小回归测试并同步账号配置说明。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `rootfs-user-system`：收紧默认用户及附加组的 UID/GID 分配契约，使其对齐 Ubuntu Desktop。

## Impact

- 影响共享实现 `builder/rootfs.py`，因此所有平台下一次 rootfs 构建都会采用新账号编号规则。
- 影响默认用户和顶层附加组的 `/etc/passwd`、`/etc/group` 数值身份；不增加配置字段或外部依赖。
- 更新 OpenSpec、ProjectSpec、rootfs 配置说明及相应测试快照。

## 非目标

- 不兼容 fnOS 的 `Administrators` / `Users` 私有 GID 约定。
- 不迁移已经刷写设备上的存量账号或文件所有权；本变更只约束新构建镜像。
- 不允许 board 自定义默认用户的 UID/GID，也不引入通用 UID/GID 配置接口。
