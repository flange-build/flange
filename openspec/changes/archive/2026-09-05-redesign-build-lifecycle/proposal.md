## Why

设计评审已发现执行、缓存、配置和部署对同一事实各自解释，导致错误架构 App、漏失效、共享目录污染与不完整外部开发流程。
用户授权破坏性重构；本变更以显式工作区、构建计划和产物契约统一生命周期，不为旧 CLI 或缓存格式保留兼容分支。

## What Changes

- **BREAKING**：Python 提供可安装 CLI，Shell 缩减为环境引导，工作区独立保存目标与输出路径。
- **BREAKING**：App 构建按完整依赖闭包执行，原生构建状态与产物按工作区、target、资源身份隔离。
- **BREAKING**：旧缓存成功记录不再作为可信依据；统一树摘要与产物清单，验证内容、权限、链接和必需输出。
- 显式构建计划定义输入、上游依赖和输出，执行/缓存/why 共用同一契约；引入锁与原子发布。
- 严格校验系统/App/Package 配置并兑现字段消费者，纠正工具链、Phase 1、modules 和禁用组件语义。
- 部署消费准确产物，提供设备身份检查、验证记录及可诊断的调试会话。
- 同步 CLI、工作区、产物与开发文档，修复 CI 工具及 target 解析，增加真实产物与故障路径验证。
- 按完整用户旅程重做 CLI 交互审查：命令发现、目标选择、只读计划、可执行诊断、终端降级与稳定机器输出。

## Capabilities

### New Capabilities

- `workspace-lifecycle`: 工具、内容、外部项目、目标状态和输出目录的明确边界及独立 CLI。
- `build-plan-artifacts`: 构建计划、统一输入摘要、依赖闭包、完整产物清单、锁与发布契约。
- `device-development-session`: 基于准确产物的部署、调试、验证与结果记录。
- `cli-experience`: 可发现、可组合、可诊断的命令行及终端视觉规范。

### Modified Capabilities

- `cli-envsetup`: 将命令解析与业务编排移入 Python，状态以当前工作区为准。
- `cli-subcommands`: 资源优先命令成为正式入口，系统构建与 App 开发共用上下文。
- `build-cache`: 计划输入与产物清单双重判定，补全快照和文件元数据语义。
- `python-app-packaging`: 完整依赖闭包、工具链与隔离目录、严格配置和精确产物集。
- `package-development-workflow`: Package 的独立动作、产物与开发会话使用相同的工作区契约。
- `build-output`: 系统与独立资源共享输出级别、目标日志和终端能力降级规则。
- `repo-layout`: 所有运行目录从显式工作区派生，移除全局输出和软链接契约。
- `local-source`: 用户源码只读，工作树按目标隔离，并以内容判断增量构建。
- `shared-repo-references`: 共享下载存储与独立工作树各有锁和身份边界。
- `boot-partition-rule`: boot 组件以实际产物清单验证成功。
- `amp-firmware-build`: AMP 使用统一输入与依赖契约，SDK 和内核消费进入计划。
- `allwinnera733-platform`: 平台源码位置通过组件上下文获取。
- `repository-quality-gate`: 缓存测试必须构造并验证真实产物契约。
- `canonical-config-semantics`: 相同验证边界覆盖所有调用入口。
- `config-deep-merge`: 移除无消费者的旧合并行为，明确 Jsonnet 求值边界。
- `config-registry`: 配置注册与工作区目标状态职责分离。
- `jsonnet-config-evaluation`: 作者输入、派生结果和严格字段验证各有明确步骤。
- `app-registry`: 工作区注册、直接路径和工具内容使用统一资源解析。
- `docker-build-env`: 显式工具链与镜像身份、统一挂载，以及干净环境的镜像准备。

## Impact

涉及 builder、Shell 引导、模板、配置校验、CI、测试、当前规格和文档。
允许迁移或删除旧入口与旧缓存；已有平台硬件规则在新边界内保留并验证，用户源码内容不得丢失。

## 非目标

- 不引入新的系统构建语言，不按外观模仿品牌；质量以模块契约、默认路径与验证证据衡量。
- 不自动刷写用户设备，不以模拟测试代替未具备设备条件的实机验收。
- 本变更不构建 OTA/A/B 升级服务器、远程构建集群或完整商业设备实验室。
