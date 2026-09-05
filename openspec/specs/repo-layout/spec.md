# repo-layout Specification

## Purpose

规定 flange 仓库的顶层目录分层契约（代码 / 内容 / 产物）、各层的语义边界，以及跨层引用的命名约定。任何新增顶层目录以及涉及跨层引用的代码与脚本都必须遵循本规格，使仓库随时间增长时保持"代码、内容、产物"三者结构清晰、互不混杂。
## Requirements
### Requirement: 顶层目录三层分法

flange 仓库根目录 MUST 将顶层目录按角色分为三层：**代码层**（`builder/`）、**内容层**（`components/`）、**产物层**（`.build/`）。除这三层以及工具/支持目录（`docker/`、`tools/`、`tests/`、`docs/`、`openspec/`）与规范文件（`envsetup.sh`、`pyproject.toml`、`docker-compose.yml`、`CLAUDE.md`、`ProjectSpec.md`、`README.md`、`roadmap.md`、`.gitignore` 等）之外，根目录 MUST NOT 出现第四类业务顶层目录。

#### Scenario: 新增业务目录必须归入三层之一

- **WHEN** 开发者新增一个承载业务内容的顶层目录（例如新增平台数据、新增 Python 子包、新增运行时缓存）
- **THEN** 该目录 MUST 分别放入 `components/`、`builder/`、`.build/` 中的对应层，不得直接创建在仓库根

#### Scenario: 工具与规范文件不受分层约束

- **WHEN** 开发者需要在根目录保留项目级工具（`tools/`）、容器定义（`docker/`）、测试（`tests/`）、文档（`docs/`）、OpenSpec 管理（`openspec/`）或根级规范文件
- **THEN** 这些目录与文件 MAY 直接位于仓库根，且 MUST NOT 被视作违反三层分法

### Requirement: 代码层职责边界

`builder/` 层 MUST 仅包含可通过 Python import 访问的模块代码（含 `__init__.py`），且 MUST 作为项目的唯一 Python 顶层包。任何"看起来是配置、但本质是 Python 代码"的子系统（例如配置加载 / 合并 / 查询子系统）MUST 位于 `builder/` 下的子包，而非顶层。

#### Scenario: 配置子系统归属

- **WHEN** 存在 Python 模块用于加载、合并、查询配置
- **THEN** 该模块 MUST 位于 `builder/config/` 子包，外部 import 路径形如 `from builder.config.<module> import …`

#### Scenario: 平台构建逻辑归属

- **WHEN** 存在承担平台构建策略的 Python 模块（`boot.py`、`bootloader.py`、`image.py`、`kernel.py`、`rootfs.py` 等）
- **THEN** 该模块 MUST 位于 `builder/platforms/<soc>/` 子包，不得与平台数据混放

#### Scenario: 代码层不得存放非代码资产

- **WHEN** 开发者考虑将 patches、配置清单、文件系统 overlay 等非 Python 资产放入 `builder/`
- **THEN** 该操作 MUST 被拒绝；这些资产归属内容层（`components/`）

### Requirement: 内容层职责边界

`components/` 层 MUST 仅包含仓库携带的"原料型"内容：应用源码、软件包定义、rootfs 基线配置与 overlay、板型定义、平台数据（patches、配置清单、SoC 级子目录），以及外部 vendor 资源（包括但不限于 device tree overlay 仓库的 source pin）。`components/` 下的目录 MUST 可被版本控制跟踪，MUST NOT 包含构建生成的派生物。

#### Scenario: 组件源码归属

- **WHEN** 仓库携带应用 / 软件包 / rootfs 基线配置或 overlay / 板型定义 / 平台数据
- **THEN** 这些内容 MUST 分别位于 `components/app/`、`components/packages/`、`components/rootfs/`、`components/board/`、`components/platform/` 下

#### Scenario: rootfs 基线配置归属

- **WHEN** 需要声明平台无关的 rootfs apt 包集合或 overlay
- **THEN** 这些内容 MUST 位于 `components/rootfs/` 下，并在配置解析阶段合并到最终 `rootfs.packages`

#### Scenario: 平台数据与平台逻辑分离

- **WHEN** 需要为某个 SoC 家族维护 patches、配置清单与 SoC 子目录
- **THEN** 这些内容 MUST 位于 `components/platform/<soc>/`，与 `builder/platforms/<soc>/` 中的构建逻辑按"数据与代码分离"的原则分别维护

#### Scenario: 外部 vendor overlay 仓库 source 归属

- **WHEN** 仓库需要消费外部 vendor 维护的 device tree overlay 仓库（例如 radxa-overlays）
- **THEN** 该 source pin（git URL + ref）与默认配置 MUST 位于 `components/device-tree-overlay/` 下，构建逻辑位于 `builder/overlays.py`，遵循"数据与代码分离"原则

#### Scenario: 内容层不得存放运行时产物

- **WHEN** 构建过程生成中间文件或最终镜像
- **THEN** 该产物 MUST NOT 写入 `components/` 层；MUST 写入 `.build/` 层

### Requirement: 补丁归属按影响面判断

补丁 MUST 按"它影响谁"归位：影响该平台**所有**板子的补丁位于
`components/platform/<平台>/patches/`（SoC 级差异可再下沉到
`components/platform/<平台>/<soc>/patches/`），只影响**特定板子**的补丁位于
`components/board/<板>/patches/<组件>/`。

判据是影响面而不是"谁先发现的"：把板级补丁放到平台层，其他板会静默地被打上
不该打的补丁；把平台补丁放到板级，同平台的新板会缺一个必需修复，而且要到
它真正跑起来才发现。

#### Scenario: 平台通用补丁归属

- **WHEN** 一个内核补丁修复该平台所有 SoC 的公共问题
- **THEN** 补丁位于 `components/platform/<平台>/patches/`

#### Scenario: 板级特有补丁归属

- **WHEN** 一个内核补丁仅修复某块板子的硬件问题
- **THEN** 补丁位于 `components/board/<板>/patches/kernel/`

#### Scenario: 补丁不进代码层

- **WHEN** 开发者考虑把补丁放到 `builder/platforms/<平台>/` 旁边
- **THEN** 该操作 MUST 被拒绝：补丁是数据，归内容层

### Requirement: 产物层职责边界

运行时派生物 MUST 位于 `WorkspaceContext.build_root`，默认是当前工作区的 `.build/`，允许在 `flange.toml` 中用 `build_dir` 指定其他目录。该根下 SHALL 以 `cache/` 保存共享缓存、`sources/` 保存共享下载、`work/<target.key>/` 保存目标中间目录、`target/<board>/<product>/<variant>/` 保存已发布产物、`locks/` 协调共享状态。工具仓库与外部工作区的产物 MUST NOT 因 cwd 变化而混写。

#### Scenario: 默认工作区派生目录
- **WHEN** 工作区没有覆盖 build_dir
- **THEN** 缓存、下载、中间目录和产物统一进入该工作区 `.build/`，且默认 `.build/` 不进入版本控制

#### Scenario: 独立构建存储
- **WHEN** 工作区配置了绝对 build_dir
- **THEN** 全部构建路径由该 build_root 推导，产物位于 `target/<board>/<product>/<variant>/`，工具仓库不会额外生成另一份输出

#### Scenario: 清理目标
- **WHEN** 开发者通过 CLI 清理当前目标
- **THEN** 清理在该目标锁内完成，不能修改工具内容层或用户本地源码；需要的派生物可由后续构建重新创建

### Requirement: 跨层引用方向

运行时路径 MUST 由显式 `WorkspaceContext` 提供。工具内容使用 `context.components_root`，目标产物使用 `context.target_dir`，下载和工作目录使用 `context.sources_dir` 与 `context.build_root`；不得用 cwd、仓库全局 BUILD_ROOT 或根级软链接猜测当前工作区产物位置。`builder.paths` MAY 提供已安装工具根的默认发现入口，不承担当前工作区和目标状态。

#### Scenario: 从外部工作区启动构建
- **WHEN** 调用者 cwd 不在 flange 工具仓库中
- **THEN** 平台内容仍从 tool_root 读取，所有产物写入所选 workspace/build_root 的当前目标目录

#### Scenario: 宿主与容器路径
- **WHEN** 工作区资源传入构建容器
- **THEN** 工具、工作区、build_root 和外部 App 挂载到相同绝对路径，计划和 manifest 不需要 `/workspace` 路径翻译
