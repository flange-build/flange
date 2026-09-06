## Why

系统配置、平台策略和内容发现仍绑定 flange 工具仓库，产品无法通过独立仓库跟随基础层迭代。
需要把已有 out-of-tree App 工作区扩展为统一多层组合，并贯通不同 Linux 发行版的构建环境。

## What Changes

- 增加显式有序本地 Layer（扩展层）、依赖校验和统一资源解析；基础层隐式启用。
- 按配置作用域优先、作用域内上层优先组合 Jsonnet；App/Package/策略整体覆盖。
- 开放平台、发行版、环境、工具链、打包与刷写策略，执行和缓存共用来源身份。
- 增加层诊断与来源记录，保证跨层路径、补丁顺序、容器挂载及缓存一致。
- 增加 Debian 13 AArch64 示例层，验证 App 编译、DEB、rootfs 和运行闭环。
- **BREAKING**：缺少发行版/ABI 身份的旧 App 报告需重建；旧工作区配置继续兼容。

## Capabilities

### New Capabilities
- `layer-composition`: 层模型、资源组合、策略接口、来源诊断与发行版扩展。

### Modified Capabilities
- `workspace-lifecycle`: 工作区承载启用层、环境和输入来源。
- `config-registry`: 注册表从所有启用层发现目标。
- `jsonnet-config-evaluation`: 多根受限 import、阶段内层组合和发行版基线。

## Impact

涉及 builder 配置、workspace、来源解析、平台策略、构建计划、Docker、App、rootfs、刷写和测试。
保持固定组件依赖图、目标字符串、Docker 编译及宿主机刷写边界；同步 ProjectSpec 和用户文档。

## 非目标

不管理远端层仓库同步或锁定，不增加独立 RTOS 目标、任意任务图、自动支持全部发行版，
不批量搬迁现有产品，也不执行真实设备刷写。
