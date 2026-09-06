## Why

当前平台、SoC、板级和产品配置对相同构建动作存在多套语义参数，例如 Kernel Kconfig 同时使用 `defconfig` raw option、`enable_configs` 和 `disable_configs`，设备树同时使用 `dts` 与 `dtb`。现有 Python `deep_merge` 还通过 `+key`、`:product`、`:variant` 等私有语法表达组合，导致参数语义、实际消费者和层级继承不能稳定一一对应，需要在继续扩展平台前统一配置语言与最终 JSON 契约。

## What Changes

- 引入 Jsonnet 作为平台、SoC、板级和产品配置的声明与组合语言，使用其原生对象继承、数组拼接和条件表达式。
- 定义唯一的 canonical JSON（规范化 JSON）契约；Jsonnet 求值完成后由 Python validator 校验，所有 builder 只消费该 JSON。
- 统一 Kernel 与 Bootloader Kconfig：`defconfig` 只描述有序 target/fragment，显式符号状态统一进入 `config` 对象，不再区分 enable/disable 数组。
- 统一设备树、源码引用和外部下载产物的字段语义；同一功能在所有平台层级使用相同路径与类型。
- 用 Jsonnet 条件表达式替代 `+key:<product|variant>`，消除 `product`、`variant` 向嵌套对象泄漏。
- 增加未知字段、无消费者字段、类型冲突、未带 SHA256 的外部下载和非法跨层策略的校验。
- 为全部 lunch target 建立旧配置与 canonical JSON 的迁移对照及行为级交叉验证，确认 Kconfig、源码版本、设备树、overlay、软件包和镜像输入保持一致。
- **BREAKING**：迁移完成后删除 Python 配置模块、私有 `+key`/条件后缀合并语法，以及 `enable_configs`、`disable_configs`、raw inline `defconfig` 等旧参数；不提供长期双语义兼容层。

## Capabilities

### New Capabilities

- `jsonnet-config-evaluation`: 定义 Jsonnet 配置入口、受限 import、product/variant 参数传递、确定性求值及 plain JSON 输出契约。
- `canonical-config-semantics`: 定义跨平台统一的配置字段、Kconfig 状态、数组增删、设备树、源码和下载产物语义，以及未知/无效字段校验。

### Modified Capabilities

- `config-deep-merge`: 由 Jsonnet 继承与组合语义替代 Python `deep_merge` 和私有操作符。
- `config-registry`: 注册表发现并求值 Jsonnet 配置，为 board/product/variant 返回 canonical JSON。
- `board-config`: 板级配置改用统一 Jsonnet 契约，只声明板级事实和策略覆盖。
- `platform-abstraction`: 平台与 SoC 自动发现从 Python 配置模块迁移到 Jsonnet 配置入口。
- `shared-repo-references`: 独立源码与命名共享仓库使用同一 canonical source descriptor，不再要求消费者识别多套来源字段。

## Impact

- 配置内容：`components/rootfs/`、`components/platform/`、`components/board/` 下现有 `config.py` 将分批迁移为 Jsonnet。
- 构建代码：影响 `builder/config/`、`builder/source.py`、Kernel/Bootloader 基类及仍自行翻译配置的各平台 builder。
- 测试：增加全部 lunch target 的配置求值、schema 校验、golden diff 和行为级交叉验证；同步更新依赖旧配置语法的测试与规格引用。
- 依赖：新增一个固定版本的 Jsonnet 求值运行时；宿主侧 `flange lunch/build` 不要求用户自行安装 Jsonnet CLI。
- 缓存：内容哈希基于求值后的 canonical JSON 和被 import 的 Jsonnet 文件，保持确定性增量构建。

## 非目标

- 不改变现有平台的编译命令、镜像格式、刷写协议或硬件功能。
- 不借迁移重新设计所有 builder，也不引入通用插件、schema 代码生成或多套配置后端。
- 不把构建实现逻辑放入 Jsonnet；Jsonnet 只负责声明、组合和求值配置。
- 不长期保留 Python/Jsonnet 双栈或旧参数 alias；兼容只用于迁移期对照验证。

## 归档时的 delta 核对（2026-08-30）

本变更的任务在实现侧已全部完成，但归档被 spec delta 卡住：其中两份 delta
声明 MODIFIED 的 requirement 标题在 live spec 中已不存在 —— 后续变更把同一
片语义用更好的模型重写并先行归档了。逐条核对结果：

- `board-config`：「板级配置文件声明完整构建参数」的内容已由 live 的
  「板级配置身份」+「板级硬件事实使用 canonical 字段」覆盖，删除。
- `shared-repo-references`：delta 描述的是 `from_repo` 这一中间设计，live
  已改为 `sources.<name>` + `source.name` 模型（「顶层命名 source」
  「组件使用统一 source 引用」「checkout 身份隔离」），四条全部被取代，
  整份 delta 删除。
- `config-deep-merge`：delta 声明 REMOVED 的两条 `deep_merge` 要求在 live
  spec 中已经不存在 —— 该 spec 已整份重写为 Jsonnet 组合语义，删除动作事实上
  已经完成，整份 delta 删除。
- 「板级配置声明 rootfs 基线版本」在任何 live spec 中都没有对应要求，
  确属遗漏，改为 ADDED 保留。

这类"delta 挂在已被重写的标题上"是变更长期不归档的直接后果 —— 见
`repository-quality-gate` 中新增的归档时效要求。
