## MODIFIED Requirements

### Requirement: 开发者入口描述当前可用能力

README MUST 包含项目定位、真实 clone 地址、最少前置概念、无需设备的首次验证、完整镜像构建入口、
外部 App 工作流、使用/维护/扩展导航、贡献入口及许可状态。README MUST 引用仓库内 Logo，
MUST NOT 将规划能力或未经测量的性能比较描述为既有保证。

#### Scenario: 首次访问公开仓库
- **WHEN** 不熟悉嵌入式开发的读者从 README 开始使用 flange
- **THEN** 能理解宿主、Docker 构建环境、设备镜像与开发板之间的关系，并选择无需设备的起点
- **AND** 能找到从 clone 到镜像构建的指南，明确区分已有能力、硬件条件和未来计划

### Requirement: 生命周期指南与维护文档分工明确

文档系统 MUST 分别提供入门教学、完整使用参考、维护与扩展指南。开发指南 MUST 说明配置选择、
构建、产物检查、刷写、外部 App 创建构建部署调试、排障与验证边界。
ProjectSpec 与当前架构说明 MUST 描述实际配置边界、模块职责及能力限制；历史设计 MUST 标注用途。

#### Scenario: 外部 App 开发
- **WHEN** 开发者在 flange 仓库之外开发 App
- **THEN** 文档说明工具 checkout、外部工作区、目标状态及输出目录的独立归属，以及 GDB 所需设备和符号条件

#### Scenario: 第一次维护或扩展
- **WHEN** 开发者希望增加产品配置、App、Package、板卡或平台
- **THEN** 能从任务找到源码落点、最小示例、适用检查和需要同步的文档，不需先通读整个 ProjectSpec

## ADDED Requirements

### Requirement: 入门步骤提供可判断的结果

入门教程 MUST 说明命令运行位置、前置条件、预期产物或输出及下一步，MUST 区分只读计划、
实际编译和设备操作。首次出现的关键术语 MUST 有解释或紧邻的术语链接。

#### Scenario: 没有开发板的第一次学习
- **WHEN** 读者只有满足 Python 前提的电脑和工具 checkout
- **THEN** 可以按文档在独立工作区创建 App 并查看计划，知道此时尚未生成可运行的目标二进制

### Requirement: 图示和导航在公开仓库可直接阅读

主要导航 MUST 使用 GitHub 可用的 Markdown 链接。图示 MUST 有文字说明，示例目标与硬件条件
MUST 明确，文档修改 MUST 检查链接、CLI 示例及配置解析。核心概念存在重复页面时 MUST 指向同一当前参考。

#### Scenario: 从入门进入专题
- **WHEN** 读者从 README 进入 Wiki、维护或扩展主题
- **THEN** 可以直接点击链接且识别当前指南与历史记录，图示不依赖仅在私人笔记软件中可用的插件
