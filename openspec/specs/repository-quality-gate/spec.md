# repository-quality-gate Specification

## Purpose

定义变更收尾时完整 pytest、OpenSpec strict validation 与环境能力复验的仓库质量门禁。
## Requirements
### Requirement: 仓库收尾 SHALL 通过完整自动化质量门禁

准备归档并声明变更完成前，flange 仓库 SHALL 在受支持的 Python 环境中运行完整 pytest，且 SHALL 运行 `openspec validate --all --strict`；两项命令都必须零失败。不得通过删除有效测试、无依据增加 `skip` 或关闭 strict 校验来达成门禁。

#### Scenario: 完整质量门禁通过

- **WHEN** 一个变更准备归档并执行最终验收
- **THEN** 完整 pytest 报告零 failed，且 OpenSpec all strict 报告全部通过

#### Scenario: 既有测试与当前公开契约不一致

- **WHEN** 测试仍调用已删除的私有接口、使用废弃路径或断言已正式变更的配置默认值
- **THEN** 维护者依据当前主规格和公开接口同步测试，并保留其行为覆盖，不得仅因测试陈旧而删除用例

### Requirement: 缓存命中测试 MUST 同时验证哈希与必需产物

缓存正向测试 MUST 创建 TaskPlan 声明的必需产物，通过 `TaskPlan.fingerprint()` 获取输入身份，并由 `BuildCache.store(plan, before, dependencies)` 发布成功 ArtifactManifest。命中判断 MUST 同时验证输入和每项输出的内容、权限、节点类型与链接目标；测试不得依赖旧 hash 标记或已删除的私有 helper。

#### Scenario: 缺少必需产物
- **WHEN** 测试没有创建声明的 modules、镜像或 deb
- **THEN** 成功发布被拒绝，不能构造仅有输入摘要的假命中

#### Scenario: 源码变化后查询
- **WHEN** 测试修改具名源码输入
- **THEN** 使用同一公开计划重新计算指纹或重新构造计划后查询，观察到输入变化和缓存 miss

#### Scenario: 已发布产物损坏
- **WHEN** 成功 manifest 已存在，但产物被删除或权限改变
- **THEN** BuildCache.explain 返回 miss 并指出受影响的产物

### Requirement: 环境能力限制 MUST 与功能回归分开验证

依赖本机回环 socket 等普通宿主能力的测试若在受限沙箱中因系统权限返回 `EPERM`，MUST 在具备该能力的普通宿主环境中复跑。只有普通宿主环境仍失败时，才 SHALL 将其判定为功能回归。

#### Scenario: 沙箱禁止回环 socket

- **WHEN** `recoveryctl` socket 测试在受限沙箱绑定 `127.0.0.1` 时返回 `EPERM`
- **THEN** 同一测试在普通宿主权限下复跑，并以该结果判定功能是否正常

#### Scenario: 普通宿主环境仍失败

- **WHEN** 受限环境失败的用例在具备所需能力的宿主环境中仍然失败
- **THEN** 质量门禁保持失败，维护者必须修复实现或测试契约后再收尾

### Requirement: OpenSpec 与实现的漂移 SHALL 由自动闸门拦截

仓库 SHALL 用自动化检查拦截以下三类 spec 治理失败，它们的共同点是"不会
自己暴露"—— 没有人在改代码时会顺手去读一份没提到的 spec：

1. **任务全部完成的变更未归档**：spec 的事实源停在旧状态，且拖得越久越难
   收口 —— 后续变更会重写同一片 spec，早先那份 delta 挂着的标题随之消失，
   归档时报 "header not found"，只能回头逐条核对。
2. **live spec 规定仓库中不存在的构建系统**：这比没有 spec 更糟，它会主动
   误导实现者。明确要求"不得依赖"的否定式引用不在此列。
3. **Purpose 仍是归档工具留下的占位**：等于宣告这份 spec 没人认领过。

#### Scenario: 变更全勾选未归档

- **WHEN** `openspec/changes/<name>/tasks.md` 的任务全部勾选，但目录仍在
  `changes/` 下而非 `changes/archive/`
- **THEN** 质量门禁失败，并指出应执行 `openspec archive <name>`

#### Scenario: spec 规定已废弃的构建系统

- **WHEN** 某份 live spec 以肯定式规定使用一个仓库中并不存在的构建系统
- **THEN** 质量门禁失败并列出具体行

#### Scenario: 废弃标记的前提被推翻

- **WHEN** 该构建系统重新被引入仓库（出现其证据文件）
- **THEN** 门禁自身先失败，要求先更新废弃清单，再决定 spec 怎么写

#### Scenario: Purpose 仍是占位

- **WHEN** 某份 live spec 的 Purpose 仍为 `TBD - created by archiving change …`
- **THEN** 质量门禁失败，要求写清它到底约束什么
