## ADDED Requirements

### Requirement: 部署使用准确产物与设备身份

App 部署 MUST 消费构建清单并校验文件内容、权限与目标架构，MUST NOT 按同名最新 DEB 或目录 glob 推断产物。多设备时 MUST 要求明确设备选择。默认部署 SHALL 安装完整闭包的 runtime DEB，排除开发包；文件上传后 MUST 校验 SHA-256，通过后才以一批 dpkg 安装。临时上传目录 SHALL 在成功或失败后清理。

#### Scenario: 错误架构产物

- **WHEN** 报告架构与设备 dpkg --print-architecture 不匹配
- **THEN** 部署在上传前失败并指出身份差异
- **AND** 持久化会话记录设备、target、产物身份与失败原因

#### Scenario: 上传内容不匹配

- **WHEN** 设备收到的 DEB 的 SHA-256 与本地清单产物不一致
- **THEN** 不运行 dpkg 安装并清理此次上传目录

#### Scenario: 多根 Package 部署

- **WHEN** Package 请求包含多个 vendor App 根
- **THEN** 部署同一报告中准确去重的 runtime 闭包，会话保留完整请求报告身份

### Requirement: 验证与调试记录关联产物

run、debug、test 和日志流程 MUST 在 `<target_dir>/sessions/<id>/session.json` 记录设备、target 与产物身份。测试 MUST 保存退出状态、stdout/stderr 日志和结构化结果；超时 SHALL 返回退出码 124 并记录 timed_out，取消 SHALL 保留 interrupted 结果。设备操作期间 SHALL 锁定目标产物，避免并行构建或清理替换正在使用的包、源码和符号。

#### Scenario: 设备测试失败

- **WHEN** 测试命令返回非零退出状态
- **THEN** CLI 返回失败并保存带设备与产物身份的报告和日志

#### Scenario: 测试超时

- **WHEN** 设备测试超过 --timeout 声明的秒数
- **THEN** 会话记录 timed_out 与退出码 124，CLI 不得报告成功

### Requirement: GDB 会话 SHALL 描述并执行真实连接

默认 debug MUST 使用 debug target 的 exec/service 产物，使用受清单保护的符号安装树、源码快照与编译路径映射。target 模式 SHALL 在设备运行 GDB，exec 使用 --args，service attach 当前 MainPID；临时源码 SHALL 在结束后清理。remote 模式 SHALL 校验宿主 GDB 与目标 gdbserver，通过 ADB forward 建立连接，在确认 gdbserver 监听后启动宿主 GDB，并在结束或失败后清理转发与 gdbserver 子进程。会话 MUST 保存连接方式、端口、符号路径、源码路径与映射。`FLANGE_NO_INTERACTION=1` 时默认 debug MUST 在联系设备前拒绝，并给出恢复到交互终端的指引。

#### Scenario: 隔离 Make 源码调试

- **WHEN** Make 编译记录了工作区资源源码副本路径
- **THEN** GDB substitute-path 把该实际编译路径映射到 manifest 记录的发布源码快照
- **AND** 用户后来编辑原目录不改变此次调试所展示的源码

#### Scenario: 服务尚未运行

- **WHEN** service 的 MainPID 不存在或为 0
- **THEN** debug 会话失败并提示先运行服务，不能启动一个无目标的 GDB

#### Scenario: 自动化环境请求交互调试

- **WHEN** FLANGE_NO_INTERACTION=1 且没有显式 debug action
- **THEN** CLI 拒绝启动 GDB，并提示在交互终端取消该变量后重试
