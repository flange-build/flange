## ADDED Requirements

### Requirement: Rootfs Phase 2 APT 包声明
rootfs SHALL 支持 `phase2_packages`（字符串数组，默认空），用于依赖 Phase 2 平台前置条件、不能进入共享 Phase 1 的 APT 包；
元素 MAY 使用 `name=version` 固定版本。它 SHALL 在 Phase 2 外部 deb 之后、内核模块之前，使用 Phase 1 已配置的 APT 源、
共享 AptCache 与 `install_recommends` 设置执行 `apt-get install`。该字段 SHALL 进入 rootfs 组件指纹，
SHALL NOT 进入 Phase 1 基础快照身份。未声明或为空时，Phase 2 行为与引入该字段前一致。recovery 不接受该字段。

#### Scenario: 固定版本安装
- **WHEN** rootfs 声明 `phase2_packages: ['nvidia-l4t-core=32.7.6-20241104234601']` 且对应 APT 源已配置
- **THEN** Phase 2 安装该版本，`packages.manifest` 记录同一版本

#### Scenario: 修改不影响基础快照
- **WHEN** 只修改 `phase2_packages`
- **THEN** rootfs 组件重建，Phase 1 基础快照命中复用

#### Scenario: 类型错误
- **WHEN** `phase2_packages` 写成单个字符串
- **THEN** 配置校验失败，错误指出字段路径与期望的数组类型

#### Scenario: recovery 声明该字段
- **WHEN** recovery 配置声明 `phase2_packages`
- **THEN** 配置校验以未知字段拒绝
