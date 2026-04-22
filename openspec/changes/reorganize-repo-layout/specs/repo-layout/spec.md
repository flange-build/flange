## ADDED Requirements

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

`components/` 层 MUST 仅包含仓库携带的"原料型"内容：应用源码、软件包定义、rootfs overlay、板型定义、平台数据（patches、配置清单、SoC 级子目录）。`components/` 下的目录 MUST 可被版本控制跟踪，MUST NOT 包含构建生成的派生物。

#### Scenario: 组件源码归属

- **WHEN** 仓库携带应用 / 软件包 / rootfs overlay / 板型定义 / 平台数据
- **THEN** 这些内容 MUST 分别位于 `components/app/`、`components/packages/`、`components/rootfs/`、`components/board/`、`components/platform/` 下

#### Scenario: 平台数据与平台逻辑分离

- **WHEN** 需要为某个 SoC 家族维护 patches、配置清单与 SoC 子目录
- **THEN** 这些内容 MUST 位于 `components/platform/<soc>/`，与 `builder/platforms/<soc>/` 中的构建逻辑按"数据与代码分离"的原则分别维护

#### Scenario: 内容层不得存放运行时产物

- **WHEN** 构建过程生成中间文件或最终镜像
- **THEN** 该产物 MUST NOT 写入 `components/` 层；MUST 写入 `.build/` 层

### Requirement: 产物层职责边界

`.build/` 层 MUST 聚合所有运行时生成的派生物：外部工具缓存（`.build/cache/`）、源码下载/克隆（`.build/sources/`）、构建产物（`.build/target/`）。`.build/` 整棵目录 MUST 被 `.gitignore` 忽略，MUST 可被安全删除以触发完整重建。

#### Scenario: 缓存与下载归属

- **WHEN** 工具链需要缓存 apt 包、下载源码 tarball 或 clone 上游仓库
- **THEN** 这些内容 MUST 写入 `.build/cache/` 或 `.build/sources/`

#### Scenario: 构建产物归属

- **WHEN** 构建流程为某个 board 生成镜像、中间件或刷写工件
- **THEN** 产物 MUST 写入 `.build/target/<board>/` 路径下

#### Scenario: 产物层可被完全删除

- **WHEN** 开发者执行 `rm -rf .build`
- **THEN** 仓库 MUST 回到"仅有代码层与内容层"的纯净状态，后续任何构建入口 MUST 能够从零重建 `.build/` 子树而不需要人工干预

### Requirement: target 便捷软链接

仓库根目录 MUST 维护一个软链接 `target -> .build/target`，MUST 由 `envsetup.sh` 在每次 source 时幂等创建，MUST 在 `.gitignore` 中忽略以避免被提交。除 `target` 之外，MUST NOT 为 `cache/`、`sources/` 或 `.build/` 下的任何其它目录创建根级软链接。

#### Scenario: envsetup 幂等创建

- **WHEN** 开发者在已完成过初始化的工作区再次执行 `source envsetup.sh`
- **THEN** 根目录 `target` 软链接 MUST 仍然存在且指向 `.build/target`，操作 MUST 不报错、MUST NOT 重复产生 `target.1`/`target.bak` 之类残留

#### Scenario: 链接不被提交

- **WHEN** 开发者执行 `git status`
- **THEN** 根目录的 `target` 软链接 MUST NOT 出现在未跟踪或已修改列表中

#### Scenario: cache 与 sources 不暴露

- **WHEN** 开发者浏览仓库根目录
- **THEN** 根目录 MUST NOT 存在 `cache` 或 `sources` 软链接；访问这些内容 MUST 通过 `.build/cache/`、`.build/sources/` 完成

### Requirement: 跨层引用方向

代码层内部的路径解析 MUST 将"内容"与"产物"的根锚点表达为单一常量（例如 `COMPONENTS_ROOT`、`BUILD_ROOT`），而不是散落的字面量。代码 MUST NOT 直接拼接 `"app"`、`"packages"`、`"rootfs"`、`"board"`、`"platform"`、`"cache"`、`"sources"`、`"target"` 这些旧顶层名作为根目录段。

#### Scenario: 内容访问使用根锚点

- **WHEN** 代码需要读取应用 / 软件包 / rootfs overlay / 板型 / 平台数据
- **THEN** 路径 MUST 以 `COMPONENTS_ROOT` 为基准拼接（如 `COMPONENTS_ROOT / "app"`），MUST NOT 直接使用 `PROJECT_ROOT / "app"`

#### Scenario: 产物访问使用根锚点

- **WHEN** 代码需要写入缓存 / 源码下载 / 构建产物
- **THEN** 路径 MUST 以 `BUILD_ROOT` 为基准拼接（如 `BUILD_ROOT / "target"`），MUST NOT 直接使用 `PROJECT_ROOT / "target"`
