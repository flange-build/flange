# jsonnet-config-evaluation Specification

## Purpose

定义 Jsonnet 配置的求值契约：层次顺序、product/variant 作为显式参数、import 的根限制、求值结果的确定性，以及依赖如何参与配置内容哈希。

## Requirements
### Requirement: Jsonnet 配置源声明中文职责注释

每个 `*.jsonnet` 和 `*.libsonnet` 配置源的第一条非空内容 MUST 是中文注释，并 MUST 说明该文件所属层级或共享范围、适用对象和配置职责。硬件限制、magic value、workaround 与 product/variant 条件原因 MUST 在对应字段旁说明；从其他配置格式迁移时 MUST 保留有效语义注释，并按 canonical 字段改写过时参数名。

#### Scenario: 扫描 Jsonnet 配置源
- **WHEN** 扫描 `components/` 下全部 `*.jsonnet` 和 `*.libsonnet` 文件
- **THEN** 每个文件都以包含中文的职责注释开头

#### Scenario: 配置格式迁移包含原有设计依据
- **WHEN** 将带有硬件约束、workaround 或条件原因注释的配置迁移为 Jsonnet
- **THEN** 对应 Jsonnet 字段旁保留按 canonical 语义改写后的说明
- **AND** 注释不再引用已删除的 alias 或私有合并语法

### Requirement: Jsonnet 配置按固定层次求值

配置系统 SHALL 以 `components/rootfs/config.jsonnet`、`components/platform/<platform>/config.jsonnet`、`components/platform/<platform>/<soc>/config.jsonnet`、`components/board/<board>/config.jsonnet` 为层级 overlay，并 MUST 按 rootfs → platform → SoC → board 的固定顺序通过 Jsonnet 对象继承求值。每个 overlay MUST 使用相同的 canonical 字段，不得由注册表按平台改写字段。

#### Scenario: 板级覆盖 SoC 配置
- **WHEN** SoC overlay 声明一个 canonical 字段，board overlay 通过 Jsonnet 继承覆盖同一字段
- **THEN** 求值结果包含 board 值
- **AND** 其他未覆盖的 platform 与 SoC 字段保持不变

#### Scenario: 数组使用原生继承追加
- **WHEN** board overlay 通过 Jsonnet `field+: [...]` 向 SoC 数组追加元素
- **THEN** 最终 JSON 按继承顺序包含原数组和追加元素
- **AND** 最终 key 不包含 `+` 前缀

### Requirement: product 与 variant 作为显式求值参数

Jsonnet evaluator SHALL 只通过名为 `product` 和 `variant` 的外部参数传入 lunch target 维度。配置条件 MUST 使用 Jsonnet 条件表达式；不得支持 `+key:<condition>`、`key:<condition>` 或把 product/variant 注入任意嵌套对象的旧机制。

#### Scenario: debug 条件包
- **WHEN** 某 overlay 声明 `if std.extVar("variant") == "debug" then ["gdb"] else []`
- **THEN** debug target 的最终数组包含 `gdb`
- **AND** release target 的最终数组不包含 `gdb`

#### Scenario: product 与 variant 同名
- **WHEN** 某 board 的 product 名称与合法 variant 名称字符串相同
- **THEN** 配置仍分别通过 `product` 和 `variant` 变量判定
- **AND** 不发生条件命名空间碰撞

### Requirement: Jsonnet import 受配置根限制

Evaluator MUST 使用受限 import callback。规范化后的 import 路径 MUST 位于项目 `components/` 配置根内，且扩展名 MUST 为 `.jsonnet` 或 `.libsonnet`；绝对路径、路径越界、符号链接越界和其他扩展名 MUST 被拒绝，并给出包含原始 import 的错误信息。

#### Scenario: 合法公共库 import
- **WHEN** 配置 import `components/config/lib.libsonnet` 内的公共函数
- **THEN** evaluator 成功加载并记录该依赖文件

#### Scenario: 路径越界 import
- **WHEN** 配置尝试 import `../../../../etc/passwd`
- **THEN** evaluator 在读取文件前失败
- **AND** 错误信息指出 import 越过允许根目录

### Requirement: 求值结果为确定性的 plain JSON

同一组配置文件内容、board、product 和 variant MUST 生成字节规范化后相同的 plain JSON。最终结果 MUST 能直接解析为 Python `dict`，不得包含 Jsonnet function、hidden field、操作符 key 或未求值表达式。

#### Scenario: 重复求值结果一致
- **WHEN** 对同一 target 连续求值两次且输入文件未变化
- **THEN** 两次规范化 JSON 完全一致

#### Scenario: 非 JSON 值拒绝
- **WHEN** 最终可见字段包含 function 或其他无法 manifest 为 JSON 的值
- **THEN** evaluator 失败并指出对应 Jsonnet 位置

### Requirement: Jsonnet 依赖参与配置内容哈希

Evaluator SHALL 返回本次求值实际读取的 Jsonnet/Libsonnet 文件集合；配置内容哈希 MUST 包含这些文件内容、board、product、variant 和求值后的 canonical JSON。未参与求值的无关配置文件变化 MUST NOT 改变当前 target 的配置哈希。

#### Scenario: 公共库变化触发配置哈希变化
- **WHEN** 当前 target import 的 `lib.libsonnet` 内容发生变化
- **THEN** 当前 target 的配置内容哈希发生变化

#### Scenario: 无关板配置变化不触发重建
- **WHEN** 修改另一个 board 且当前 target 未 import 的 Jsonnet 文件
- **THEN** 当前 target 的配置内容哈希保持不变

### Requirement: flange 自带 Jsonnet 求值运行时

项目 MUST 固定并声明 Jsonnet 求值依赖，`flange lunch`、`flange build` 和配置查询不得要求用户预先在 PATH 中安装 `jsonnet` CLI。运行时缺失或版本不兼容时 MUST 在配置加载阶段给出明确安装错误。

#### Scenario: PATH 中没有 jsonnet CLI
- **WHEN** 用户环境的 PATH 不包含 `jsonnet` 可执行文件但项目 Python 依赖完整
- **THEN** 配置发现、lunch 和 build 正常工作

