# layer-composition Specification

## Purpose
定义 flange 基础层与多个独立本地扩展层的组合契约，统一配置、内容和策略来源，明确工作区隔离、发行版/环境/SDK 扩展以及可解释缓存和报告身份的边界。
## Requirements
### Requirement: 显式本地层组合
工作区 MUST 按声明顺序启用本地层，隐式基础层先于用户层；MUST 校验唯一身份、API、依赖存在及顺序，不自动排序。

#### Scenario: 三层产品
- **WHEN** 产品工作区按依赖顺序声明三个外部层
- **THEN** 所有层资源进入同一目标发现与构建上下文，状态和产物仍归工作区

#### Scenario: 无效依赖
- **WHEN** 依赖不存在、存在环或依赖位于上层
- **THEN** 加载失败并指出层和依赖，不启动构建

### Requirement: 确定性资源覆盖
系统 MUST 按作用域优先、作用域内层优先组合配置和 overlay；同名 App、Package 和策略 MUST 整体取最高层。
补丁 MUST 有序追加并对同作用域同相对路径原位替换；执行和缓存 MUST 使用同一顺序。

#### Scenario: 上层板级定制
- **WHEN** 上层为已有板追加 product、配置和补丁
- **THEN** lunch 可发现新目标，保留下层未覆盖配置且按解析后的补丁顺序执行

### Requirement: 层资源路径与策略隔离
资源 MUST 保留所属层、相对路径及实际路径。Python 策略 MUST 按工作区隔离加载，不能遮蔽 builder。
Jsonnet import MUST 限制在已启用配置根，跨层引用 MUST 明确标识层。

#### Scenario: 不同工作区同名策略
- **WHEN** 同一进程先后加载两个工作区的同名策略
- **THEN** 各自使用正确实现、资源和配方输入，无全局注册污染

### Requirement: 发行版与构建环境
系统 MUST 支持外部发行版、完整 Docker 环境和用户态 SDK/sysroot；默认 Ubuntu。
一个目标 MUST 使用一个完整环境，SDK MUST 独立于最终 rootfs，低层工具链要求 MUST 保留。

#### Scenario: Debian App 与镜像
- **WHEN** 目标选择 Debian 13 环境和 AArch64 SDK
- **THEN** App 使用对应 libc/目标库编译为 DEB，装入 Debian rootfs 并能在该系统用户态运行

### Requirement: 可解释输入与报告身份
层资源、策略依赖、镜像和 SDK 身份及资源应用顺序 MUST 进入相关任务指纹；无关层内容 MUST NOT 导致全量失效。
App 报告 MUST 带发行版和 ABI 身份，安装与 no-build MUST 校验，缺失身份 MUST 要求重建。
层 CLI 与 plan/why MUST 能显示启用顺序、配置链、胜出资源和补丁序列。

#### Scenario: 跨发行版旧报告
- **WHEN** 同一 target 的 App 报告来自另一发行版或没有 ABI 身份
- **THEN** no-build 和 rootfs 安装拒绝报告并要求重新构建
