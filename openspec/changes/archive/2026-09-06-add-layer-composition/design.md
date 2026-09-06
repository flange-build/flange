## Context

已有工具根/工作区/输出根隔离，但配置、补丁和策略仍从单根发现。
本设计贯彻已确认的多层实施计划，保持 Python、Jsonnet、固定依赖图与容器编译边界。

## Goals / Non-Goals

目标：用户用独立仓库组合板卡、软件与 Linux 系统，能够继续更新基础层。
非目标：远端层管理、独立 RTOS、任意任务图、全发行版支持和实机刷写。

## Decisions

1. 工作区 schema 2 增加 layers 有序本地路径；schema 1 继续可用。基础层名 flange，隐式首层。
   layer.toml schema_version/api_version 均为 1，声明 name、requires 及 providers。
   重复身份、重复路径、依赖缺失和顺序错误在加载时拒绝；不自动排序。
2. LayerStack/ResourceRef 保存物理路径及稳定逻辑身份。Jsonnet 阶段为发行版基线、平台、SoC、板、直接包，
   阶段内按层顺序继承。App/Package/provider 同名整体覆盖。
   本地 import 只查所属配置树；layer://name/path 显式跨层，flange/layer.libsonnet 的 path helper 返回所属层路径。
3. 补丁先平台后板，同作用域低层到高层新增，重名原位替换；overlay 按作用域和层顺序覆盖。
   输入解析与执行共享有序清单，缓存包括顺序，不统一哈希整个层仓库。
4. Provider 通过层清单显式声明受信任 Python 模块，隔离模块命名空间，缓存其代码树及声明的输入。
   平台补齐产物/输入/校验接口；发行版、环境、工具链、包格式及刷写沿用已有执行边界。
5. distro 默认 ubuntu；其他发行版基线单独选择。一个 target 使用一个完整容器环境，
   保留低层 gcc10，与 App 的目标工具链/sysroot 区分。normal/recovery 共享发行版。
   SDK 不依赖成品 rootfs。环境、SDK 和用户态 ABI 身份进入计划及报告，旧无身份报告要求重建。
6. Debian 13/trixie AArch64 为第二验证对象，构建容器使用 linux/amd64，包含低层 gcc10。
   动态链接 libc/zlib 并通过 QEMU/chroot 运行，再成像；不以仅成功编译代替 ABI 验证。
7. layer list/check/show 与 plan/why 输出层和资源来源；仅承诺配置组合链，不冒充字段级 Jsonnet 溯源。

## Risks / Trade-offs

- Python 策略可执行 → 明确受信任代码边界，独立命名空间不等于沙箱。
- 多层路径归属丢失 → 显式层路径 helper，基础层相对路径保持原语义。
- Ubuntu 工具/源泄漏 → 环境显式传递并分隔 APT 缓存，校验实际镜像身份。
- 同架构旧报告跨发行版复用 → 报告保存并校验 distro/ABI 身份。

## Migration Plan

逐步落地且每阶段运行对应回归；旧无层工作区维持原行为。同步项目规格与用户指南。
不归档未验证任务，真实 Docker 验证结果单独记录，不将模拟测试称为完整构建成功。
