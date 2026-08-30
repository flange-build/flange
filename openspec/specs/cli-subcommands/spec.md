# cli-subcommands Specification

## Purpose

定义 `envsetup.sh` 提供的 `flange` 子命令契约：每个子命令做什么、等价于什么、
以及哪些前置条件必须满足。

## Requirements

### Requirement: flange build 构建组件或整机镜像

`flange build [component]` SHALL 在构建容器内驱动 `builder.engine`，按依赖图
构建目标组件；省略 `component` 时构建 `image`（整机镜像，含全部上游组件）。

`flange build app <name-or-path>` SHALL 只构建指定的单个 App，并在构建后写入
该 App 的产物清单，供后续整机构建按 App 粒度复用。

选项 SHALL 由 `flange` 自身解析，不透传给下层：`-f/--force` 跳过缓存校验强制
重建（有 component 时只强制该组件，否则全部），`-v/--verbose` 输出全量日志，
`-q/--quiet` 只输出错误。

#### Scenario: 默认构建整机镜像
- **WHEN** 执行 `flange build`
- **THEN** 在容器内按依赖图构建到 `image` 组件，产出 `raw.img`

#### Scenario: 构建单个组件
- **WHEN** 执行 `flange build kernel`
- **THEN** 只构建 kernel 及其未就绪的上游依赖

#### Scenario: 构建单个 App
- **WHEN** 执行 `flange build app demo`
- **THEN** 只构建名为 `demo` 的 App，并写入其产物清单

#### Scenario: 强制重建
- **WHEN** 执行 `flange build kernel -f`
- **THEN** kernel 跳过缓存校验重建，其余组件仍走缓存

#### Scenario: 未选择目标
- **WHEN** 未执行 `lunch` 就执行 `flange build`
- **THEN** 命令前置检查失败并提示先选择目标

### Requirement: 产物收集由构建流程完成

组件产物 SHALL 由 `builder.engine` 在每个组件构建后收集到
`.build/target/<board>/<product>/<variant>/<component>/`，不需要独立的收集命令。

#### Scenario: 构建后产物就位
- **WHEN** `flange build kernel` 成功
- **THEN** kernel 产物出现在该 target 的 `kernel/` 目录下

### Requirement: flange flash 刷写

`flange flash` SHALL 在**宿主机**执行 `python3 -m builder.flash run`，读取
target 目录下的 `flash-config.json` 并按平台策略刷写。额外参数透传。

刷写在宿主机而非容器内执行：它需要直接访问 USB 设备。

#### Scenario: 默认刷写
- **WHEN** 执行 `flange flash`
- **THEN** 宿主机读取当前 target 的 flash-config.json 并整机刷写

#### Scenario: 缺少镜像
- **WHEN** 当前 target 尚未构建出镜像就执行 `flange flash`
- **THEN** 报错提示先执行 `flange build`

### Requirement: flange recovery 线刷与维护

`flange recovery` SHALL 通过 USB ADB 通道对已进入 recovery 的设备做线刷、
备份与维护，由 `builder.recovery_host` 实现。

#### Scenario: 进入 recovery 维护
- **WHEN** 设备已启动到 recovery 且执行 `flange recovery`
- **THEN** 宿主机通过 adb 通道与设备端 recoveryctl 交互

### Requirement: flange push / run 热部署

`flange push <app>` SHALL 把单个 App 的产物部署到目标设备；
`flange run <app>` SHALL 在部署之后立即运行它。

#### Scenario: 热部署
- **WHEN** 执行 `flange push demo`
- **THEN** demo 的产物被部署到设备，不需要重新刷写整机镜像

### Requirement: flange shell 交互式 shell

`flange shell` SHALL 启动构建容器的交互式 bash session。

#### Scenario: 进入容器 shell
- **WHEN** 执行 `flange shell`
- **THEN** 用户进入构建容器内的 bash

### Requirement: flange clean 清理构建产物

`flange clean` SHALL 清理**当前 target** 的构建产物目录；
`flange clean --all` SHALL 连同跨 target 共享的缓存（base 快照等）一并清理。

区分两档是因为共享缓存的重建代价远高于单 target 产物 —— 默认清理不应
牵连它。

#### Scenario: 清理当前目标
- **WHEN** 执行 `flange clean`
- **THEN** 删除 `.build/target/<board>/<product>/<variant>/`，共享缓存保留

#### Scenario: 连同共享缓存清理
- **WHEN** 执行 `flange clean --all`
- **THEN** 共享缓存目录一并删除

### Requirement: flange why 解释缓存决策

`flange why <component>` SHALL 说明该组件下次构建会不会重建，若会，是哪一段
输入（依赖 / 身份 / 配置 / 构建逻辑 / 自身源码）变了。

缓存决策不可解释时，开发者只能靠 `--force` 兜底，增量构建的收益随之失效。

#### Scenario: 解释重建原因
- **WHEN** 执行 `flange why kernel`
- **THEN** 输出各输入段的当前值与上次构建值的比对结果

### Requirement: flange status 显示状态

`flange status` SHALL 显示当前 target 身份、Docker 运行状态与各组件产物状态。

#### Scenario: 显示完整状态
- **WHEN** 执行 `flange status`
- **THEN** 输出当前 board/product/variant、Docker 是否可用、各组件产物是否存在

### Requirement: flange 无参数显示帮助

不带子命令执行 `flange` SHALL 显示按用途分组的子命令列表与当前目标。

#### Scenario: 帮助信息
- **WHEN** 执行 `flange`（无参数）
- **THEN** 输出核心模块与环境工具两组子命令，以及当前目标（未选择时提示先 lunch）
