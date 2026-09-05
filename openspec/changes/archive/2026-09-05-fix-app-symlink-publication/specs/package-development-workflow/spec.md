## ADDED Requirements

### Requirement: Package 源码快照 SHALL 保留链接与复制配方身份

显式 Package build action 使用的源码快照 SHALL 复用 App 文件树复制语义：链接保存目标文本而不展开目标，普通文件保存内容及模式，目录保存结构、空目录及模式。复制 MUST 不依赖链接目标已存在，真实 I/O 错误 MUST 中止本次构建且保留上次成功发布。公共复制实现的身份 MUST 纳入 Package 构建计划，避免实现变化后复用旧产物。

#### Scenario: Package 源码包含暂时悬空链接

- **WHEN** Package 源码中有链接指向之后由 build action 生成的文件
- **THEN** 源码快照保留相同链接文本，不读取尚未生成的目标
- **AND** build action 在准确快照中执行

#### Scenario: 复制失败不能成功发布

- **WHEN** Package 源码复制发生真正的源读取或目标写入错误
- **THEN** 本次构建失败，不替换上次成功的 artifacts 与 manifest

#### Scenario: 公共复制实现变化

- **WHEN** Package 使用的文件树复制实现发生变化
- **THEN** Package 的构建计划指纹变化，不能直接复用使用旧配方的产物
