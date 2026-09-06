## Context

现有构建框架和平台策略已有价值，但仓库根、调用目录、输出根、目标状态混在同一个 project_root 中。
缓存根据排除表猜输入，部署根据文件名猜产物，App 单个/批量路径各自构建，存在已复现的正确性缺陷。
用户明确允许破坏性修改，旧 CLI、旧缓存和错误配置不作为必须保留的行为。

## Goals / Non-Goals

**目标：** 工作区、计划、产物、设备会话形成一条可追溯链；外部 App 从创建到构建部署验证调试有实际可用入口。
框架代码按职责分层，严格配置与有意义的集成测试守住边界。

**非目标：** 不在框架内重写 CMake/Make，不搭建远程执行集群或 OTA 服务，不自动写入真实设备。

## Decisions

### 工作区与路径

`builder/workspace.py` 提供 frozen dataclass `Target(board, product, variant)` 与 `.key`，
以及 `WorkspaceContext(tool_root, workspace_root, build_root, target, invocation_dir)`。
派生属性为 `target_dir`、`sources_dir`、`components_root`、`state_file`；调用目录只用于解释请求路径，不进入产物身份。

`flange.toml` 保存版本、工具根、输出根和 App 搜索目录；`.flange/current_config` 只保存该工作区的目标选择。
显式 `--target` 覆盖本次上下文但不修改状态。工具自带配置从 tool_root 解析，工作区 App 路径相对其声明位置解析。
Docker 将工具根、工作区和显式外部源按同一绝对路径挂载，宿主与容器不再重复计算不同路径。

### CLI

`builder/cli.py` 提供安装入口和 `python -m builder`。Shell 只准备 venv 并提供简短入口。
资源优先 `app/package` 保留唯一开发语义；系统 build/flash/recovery 与工作区 select/status/why 使用同一上下文。
旧动词优先 App alias 不保留为第二套行为。工作区选择、配置解析和操作前检查是独立服务，不在 Shell 拼 Python。

### 命令行体验

用户旅程按准备环境、创建工作区、选择目标、开发、预览、构建、部署、验证和调试分层。
全局 `--workspace/-C`、`--target`、`--json`、`--no-color`、`--no-interaction` 行为一致；`--` 后参数原样传递。
命令帮助给出用途、默认行为和下一步。用户错误不显示 Python 堆栈，错误中保留字段位置与修复指令。
退出码为 0 成功、1 操作失败、2 参数/配置错误、130 取消。stdout 承载结果，过程与诊断流向 stderr；
JSON 结果含 schema_version/command/ok/data 或 error，管道中不混入 ANSI 与进度动画。
目标选择使用键盘可操作的层级选择器，无 TTY 时要求显式目标，不隐式读取输入。
构建进度显示已完成任务数与实际耗时，不把任务计数宣称为时间预测；无颜色、窄终端与 CI 日志保持信息完整。
保留完整日志和轮转，取消后停止子进程、释放锁、保留诊断，不发布成功清单。

### 计划与产物契约

`TaskPlan` 由 recipe、具名 InputSpec、dependencies、ArtifactSpec 和 enabled 构成。
InputSpec 显式区分值、文件树与已解析源码版本，执行和摘要共用这些声明。
平台配方可保留 configure/compile/collect 的模板方法，不把动态 chroot 流程强行压平成静态命令列表。

`ArtifactManifest` 保存版本、任务身份、输入摘要、上游产物身份及输出路径/类型/权限/内容摘要。
成功记录只能在完整验证后原子发布；旧 hash 文件不视为成功证明。
文件树摘要覆盖节点类型、权限、链接目标与文件内容，不跟随链接，不使用全局路径名称排除有效源码。
工作区/源码/target 锁保护共享可变状态。共享下载与可变构建树分离，失败记录保留用于诊断。

### App 构建

所有请求经同一依赖闭包解析、拓扑排序、依赖 sysroot 组成、工具链适配和产物发布流程。
App 资源身份包含规范化源码身份，不以名字或 CLI 原始字符串充当唯一键。
输出位于 `<target_dir>/apps/<resource_id>/artifacts`，工作目录位于
`<build_root>/work/<target.key>/apps/<resource_id>`。系统 rootfs 消费构建报告中的准确 deb 集合。

Toolchain 统一提供目标架构和 CC/CXX/AR/STRIP，CMake/Meson 使用独立 build 目录，
不支持外部 build 目录的 Make/custom 源在隔离副本中编译。依赖安装前缀不冒充完整系统 sysroot。

### 配置、设备与验证

所有配置入口使用严格字段与类型校验，不能靠 ResolvedConfig 子类身份决定正确性检查。
App 字段必须有消费者：auto_start 改变服务注册行为；删除无消费者 headers_dir，头文件统一经 install staging 或显式映射安装。
设备部署消费 manifest，核对架构和内容；run/debug/test/log 通过会话记录关联设备与产物。
GDB 设备端模式保留，并提供远程会话所需符号、源码与端口信息；设备测试保存退出状态和结构化报告。

### 模式与可维护性

使用数据类表示值对象，Protocol 表示真正需要替换的执行/设备边界，策略模式承载平台差异，
上下文管理器承担锁和资源生命周期。避免无消费者的抽象层、巨型通用插件系统和同义配置。

## Risks / Trade-offs

- 旧缓存失效 → 明确版本边界，保留源码与上次发布的产物，不把旧记录迁移为新可信清单。
- 目录变化影响 custom App → 通过标准环境变量与隔离源目录完成迁移，验证所有仓库 App 描述。
- 核心签名变化影响测试 → 按新行为更新测试，保留平台契约与真实产物验证，禁止只删除断言掩盖失败。
- 真实硬件条件未知 → 自动化验证与实机验收分开报告，不能自动刷机。

## Migration Plan

先建立上下文与契约，三条实现线并行接入；完成 targeted tests 后跑全量测试与严格规格校验。
最后同步当前文档、移除过时入口并归档。每个实施任务控制在两小时内，集成失败另拆任务处理。
