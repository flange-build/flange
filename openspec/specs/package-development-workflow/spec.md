# package-development-workflow Specification

## Purpose
定义 Package 资源的独立开发、构建和设备生命周期，以及它与 App 及系统组件之间的边界，使开发者能够在独立工作区中维护 vendor SDK、执行明确的构建动作，并追踪部署和验证结果。
## Requirements
### Requirement: Package 命令 SHALL 覆盖完整开发生命周期

CLI SHALL 提供 `flange package create|list|plan|build|deploy|run|debug|log|test`。list SHALL 枚举工具仓库与工作区内的 Package。除 create/list 外，目标 MAY 是工具仓库内 Package 名称或含 package.py 的目录路径；省略时 SHALL 使用调用目录。所有命令 SHALL 可从工具仓库外执行，产物 SHALL 写入当前 WorkspaceContext 的 target_dir。plan MUST 只读解析输入、依赖与输出，不触发源码下载或构建。build SHALL 支持 -v/--verbose 与 -q/--quiet，并复用统一 BuildOutput 与 target_dir/build.log；自定义 Package 构建亦须在容器内捕获完整命令日志，不能向宿主透传未过滤的编译输出。

#### Scenario: 在仓库外创建并构建 Package

- **WHEN** 用户在独立工作区执行 package create demo 后进入 demo 执行 package build
- **THEN** 创建目录在调用位置，源码通过同绝对路径进入构建容器
- **AND** 产物发布到该工作区的 target 目录，与工具仓库及其他工作区隔离

#### Scenario: 以仓库内名称定位 Package

- **WHEN** 用户执行 flange package build meizu-e3-panel
- **THEN** CLI 从工具仓库 components/packages/meizu-e3-panel/package.py 加载清单

### Requirement: Package SHALL 复用既有 component 流水线

没有 actions.build 的 Package SHALL 通过选定的 vendor components 复用完整 App 依赖闭包、DebBuilder、ArtifactManifest 与设备会话。存在多个 vendor 根时 run/debug/log/test MUST 要求 --component；deploy SHALL 一次消费完整多根 runtime 闭包。有非 vendor component 或无 component 的 Package 独立构建 MUST 声明 actions.build，不能静默忽略 component 或产生无交付物的成功结果。

#### Scenario: 单 vendor Package 自动运行

- **WHEN** Package 仅含一个 vendor component，且执行 package run
- **THEN** CLI 构建该 App 的完整依赖闭包、部署准确 runtime DEB，然后使用其运行入口

#### Scenario: 混合 Package 没有构建契约

- **WHEN** Package 同时含 vendor 和 oot-driver，未声明 actions.build 且未选择 vendor component
- **THEN** 命令失败并提示为非 vendor 交付声明 actions.build

#### Scenario: 多 vendor Package 选择不明确

- **WHEN** Package 含多个 vendor component，且 run 未提供 --component
- **THEN** 命令失败并要求选择单个运行对象

### Requirement: 显式 action SHALL 是无 shell 展开的 argv

PACKAGE.actions 与 App 顶层 actions MAY 定义 build、deploy、run、debug、log、test，每个值 MUST 是非空字符串数组。未知动作、字符串命令、空 argv 与非字符串元素 MUST 在执行前拒绝。build action MUST 在 Docker 内执行，构建参数由清单描述；其余动作 SHALL 在宿主资源目录执行并把 -- 后参数原样追加，MUST NOT 经过 shell 插值。Package 显式构建 SHALL 在源码副本执行，FLANGE_SOURCE_DIR 指向副本，FLANGE_TARGET_DIR 与 FLANGE_PACKAGE_OUTPUT_DIR 指向专属 artifacts 暂存目录；该目录 MUST 非空并通过 manifest 校验后原子发布。后续显式动作的输出路径变量 SHALL 指向已发布 artifacts，且会话 MUST 关联同一 manifest 身份。App 显式构建 SHALL 使用 FLANGE_APP_OUTPUT_DIR/DESTDIR 交付内容，仍经过统一安装收集与 App manifest 校验。

#### Scenario: 参数按 argv 原样追加

- **WHEN** run action 为 ["./run.sh", "--mode", "safe"]，用户追加 -- --port 9000
- **THEN** 执行 argv 为 ./run.sh --mode safe --port 9000
- **AND** 任一参数均不经过 shell 插值或 eval

#### Scenario: actions-only Package 发布并测试

- **WHEN** Package 没有 component，build action 在 FLANGE_TARGET_DIR 生成 SDK 文件，并声明 test action
- **THEN** build 发布专属 artifacts 树、resource 元数据与 manifest
- **AND** test 消费该产物目录并保存目标、manifest 身份、退出状态与日志

#### Scenario: 空产物拒绝发布

- **WHEN** Package build action 成功退出但未生成任何 artifacts
- **THEN** 构建失败，上次成功清单与产物保持不变

#### Scenario: 拒绝 shell 字符串 action

- **WHEN** action 值为字符串 ./run.sh; reboot
- **THEN** 清单加载失败且动作不被执行

### Requirement: 设备选择 SHALL 无歧义

App 与 Package 默认 ADB deploy/run/debug/log/test SHALL 支持 --serial。未指定且恰有一台在线设备时 SHALL 自动选择；零台或多台 MUST 在变更前失败。显式动作 SHALL 接收 FLANGE_ADB_SERIAL，由动作实现自身传输语义，CLI 不得在其前隐式联系 ADB。

#### Scenario: 多设备未指定 serial

- **WHEN** ADB 列出两台在线设备且命令未传 serial
- **THEN** 命令失败并列出设备，不向任意设备部署或运行程序

### Requirement: 默认 debug 与 log SHALL 匹配 App 运行类型

没有显式动作时，service 日志 SHALL 使用 journalctl -u unit 并默认 follow。debug target 的 exec/service SHALL 使用准确报告中的符号与源码快照，支持 target GDB 与 remote GDB/gdbserver；service attach 当前 MainPID。release target、无运行入口或非交互环境 MUST 拒绝默认 GDB 并给出明确指引。

#### Scenario: 跟随 service 日志

- **WHEN** 对 demo.service 执行 flange app log demo
- **THEN** 在所选设备执行 journalctl -u demo.service --no-pager -f

#### Scenario: release target 拒绝默认 GDB

- **WHEN** 当前 variant 为 release 且没有显式 debug action
- **THEN** debug 在启动 GDB 前失败并提示选择 debug variant

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
