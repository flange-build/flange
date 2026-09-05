# cli-subcommands Specification

## Purpose

定义 `envsetup.sh` 提供的 `flange` 子命令契约：每个子命令做什么、等价于什么、
以及哪些前置条件必须满足。
## Requirements
### Requirement: flange build 构建组件或整机镜像

flange build [component] SHALL 在 Docker 中按显式计划构建组件及依赖；省略组件时构建 image。--force SHALL 只强制指定组件，--force-all SHALL 强制整个闭包。--verbose/--quiet SHALL 作为执行选项传入，不进入系统配置或输入身份。

#### Scenario: 默认整机构建
- **WHEN** 运行 flange build
- **THEN** 构建到 image，输出与当前平台、介质和工作区匹配的镜像及清单

#### Scenario: 强制单个组件
- **WHEN** 运行 flange build kernel --force
- **THEN** kernel 强制执行，其余上游仍校验缓存

#### Scenario: 指定 App
- **WHEN** 运行 flange app build demo
- **THEN** 构建 demo 完整依赖闭包并返回准确报告，名称与路径入口共用同一实现

### Requirement: 产物收集由构建流程完成

构建 SHALL 按 ArtifactSpec 将产物发布到当前 WorkspaceContext.target_dir，不需要独立收集命令。只有内容、权限、类型与必需输出全部通过校验才可发布成功记录。

#### Scenario: 自定义输出根
- **WHEN** 工作区声明 build_dir 且 kernel 构建成功
- **THEN** 产物位于该输出根的 target/<board>/<product>/<variant>/kernel，而非工具仓库固定目录

### Requirement: flange flash 刷写

flange flash SHALL 在宿主调用统一刷写服务，读取当前工作区目标的 flash-config.json 并使用平台策略。公共帮助 SHALL 只呈现用户可选的分区与设备操作，不要求手工拼接内部目标目录。

#### Scenario: 分区刷写
- **WHEN** 运行 flange flash boot
- **THEN** 根据当前目标清单在宿主执行对应分区刷写

#### Scenario: 缺少清单
- **WHEN** 当前目标没有 flash-config.json
- **THEN** 指出缺少的文件并提示先构建 image

#### Scenario: 无交互整盘写入
- **WHEN** 非交互请求使用 --raw 但未提供 --yes
- **THEN** 在执行 dd 前失败并要求核对设备路径后明确确认

### Requirement: flange recovery 线刷与维护

flange recovery SHALL 通过宿主 ADB 调用设备端 recoveryctl，支持进入 recovery、分区列表、刷写、备份、Shell 和重启。

#### Scenario: 查看使用方式
- **WHEN** 运行 flange recovery --help
- **THEN** 显示子命令帮助，不访问设备

### Requirement: flange shell 交互式 shell

flange shell SHALL 使用当前工作区的容器路径模型。交互模式无参数进入 bash；显式 argv SHALL 直接执行且不经过 shell 字符串求值。

#### Scenario: 显式命令
- **WHEN** 运行 flange shell -- python3 --version
- **THEN** 容器执行指定 argv 并返回状态

### Requirement: flange clean 清理构建产物

flange clean SHALL 在目标锁内删除当前目标的发布产物与工作目录，保留共享下载和快照。--dry-run SHALL 仅列出待清理目录。

#### Scenario: 当前目标清理
- **WHEN** 运行 flange clean
- **THEN** 当前目标的 target 与 work 目录被清理，其他目标与共享源码不变

#### Scenario: 清理预览
- **WHEN** 运行 flange clean --dry-run
- **THEN** 仅输出待清理目录，不修改文件

### Requirement: flange why 解释缓存决策

flange why [component] SHALL 返回计划闭包各任务的命中、失效、禁用或待准备状态，并说明原因与已变化输入。未解析源码和环境 MUST 明确呈现为未确认条件。

#### Scenario: 解释失效
- **WHEN** 用户查询已构建组件且某个声明输入发生变化
- **THEN** 返回失效状态及发生变化的输入名称

### Requirement: flange status 显示状态

flange status SHALL 只读显示工具、工作区、输出根、目标与已记录清单的位置。环境探测 SHALL 通过 doctor 提供；目录存在 MUST NOT 被显示为成功验证。

#### Scenario: 未选目标工作区
- **WHEN** 新工作区执行 status
- **THEN** 显示工作区路径、未选目标状态与选择指引，不要求先配置目标

### Requirement: flange 无参数显示帮助

不带子命令执行 flange SHALL 显示命令用途、初始化示例、全局选项及退出状态约定，不要求工作区存在。

#### Scenario: 新用户查看帮助
- **WHEN** 在工作区外运行 flange
- **THEN** 显示可执行的开始步骤与命令列表

### Requirement: App 与 Package SHALL 提供资源优先命令组

CLI SHALL 提供 app/package 的 create、list、plan、build、deploy、run、debug、log、test 入口。两类资源 SHALL 使用显式工作区、声明动作和准确构建报告；动作后的 -- SHALL 保留用户 argv 边界。

#### Scenario: 资源帮助
- **WHEN** 用户运行 flange app 或 flange package
- **THEN** 显示对应动作帮助，不访问 Docker 或设备

### Requirement: App 热部署与运行

热部署 SHALL 由 flange app deploy/run 提供。旧 push/run 顶层别名 MUST NOT 作为另一套生命周期实现保留。

#### Scenario: 热部署
- **WHEN** 运行 flange app deploy demo
- **THEN** 使用准确 App 报告部署 runtime 依赖闭包并记录设备与产物身份
