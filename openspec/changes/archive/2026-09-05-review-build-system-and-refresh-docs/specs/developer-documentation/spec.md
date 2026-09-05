## ADDED Requirements

### Requirement: 开发者入口描述当前可用能力

README MUST 包含项目定位、真实 clone 地址、前置依赖、首次构建、产物位置、外部 App 工作流、文档导航、贡献入口及许可状态。
README MUST 引用仓库内 Logo，MUST NOT 将规划能力或未经测量的性能比较描述为既有保证。

#### Scenario: 首次访问公开仓库
- **WHEN** 开发者从 README 开始使用 flange
- **THEN** 可找到从 clone 到镜像构建的完整命令和必要依赖
- **AND** 可明确区分已有能力、硬件条件和未来计划

### Requirement: 生命周期指南与维护文档分工明确

开发指南 MUST 说明配置选择、构建、产物检查、刷写、外部 App 创建构建部署调试、排障与维护检查。
ProjectSpec 与当前架构说明 MUST 描述实际配置边界、模块职责及能力限制；历史设计 MUST 标注其历史用途。

#### Scenario: 外部 App 开发
- **WHEN** 开发者在 flange 仓库之外开发 App
- **THEN** 文档说明调用入口、target 状态和输出目录仍属于 flange checkout，以及 GDB 所需设备和符号条件

### Requirement: 自有内容与第三方许可范围明确

仓库 MUST 为自有代码与文档提供 Apache License 2.0 原文，Python 包元数据 MUST 引用该 LICENSE。
许可说明 MUST 保留第三方源码、固件、工具与补丁的上游许可范围，不得将生成镜像整体标为 Apache-2.0。

#### Scenario: 公开发布代码与文档
- **WHEN** 开发者从 README 或 Python 包元数据查看许可
- **THEN** 能找到根目录 Apache-2.0 原文与第三方内容边界说明

### Requirement: 设计评审提供可追溯证据

评审 MUST 将缺陷、设计建议与未验证风险分别说明，给出相关源码位置、影响、优先级及验收条件。
后续实施工作 MUST 拆成每项不超过两小时的工作单元，MUST NOT 把模拟测试通过表述为实机验收完成。

#### Scenario: 维护者安排架构改进
- **WHEN** 维护者阅读评审路线图
- **THEN** 可以按依赖关系选择独立任务，并用明确验收条件判断是否完成
