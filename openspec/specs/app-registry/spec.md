# app-registry Specification

## Purpose

规定 flange 中 App 源的注册与发现模型：定义本地 App 目录、out-of-tree 单体注册（`external_apps.local_path` / `git`）与搜索路径（`external_app_dirs`）三类来源的配置格式与查找优先级，统一路径解析规则，并规范 `flange create app` 脚手架命令的目标目录选择与注册指引行为、`flange list apps` 的来源标签展示。让 App 源码既能随 flange 仓库分发，也能放置在宿主机任意位置被同一套构建流水线发现、识别与打包。

## Requirements

### Requirement: App 身份由 app.yaml 声明，目录名仅用于物理定位

每个 App SHALL 在其根目录内提供一个 `app.yaml`，其中 `app.name` 字段是 App 的权威身份；App 目录名本身不作为身份，仅用于在宿主机上定位。构建系统 SHALL 在加载 App 时以 `app.yaml` 的 `app.name` 为准。

#### Scenario: 目录名与 app.name 一致

- **WHEN** App 根目录名为 `foo`，其中 `app.yaml` 内 `app.name: foo`
- **THEN** 构建系统加载该 App 时使用 `foo` 作为 App 名称

#### Scenario: 目录名与 app.name 不一致

- **WHEN** App 根目录名为 `bar-legacy`，其中 `app.yaml` 内 `app.name: bar`
- **THEN** 构建系统加载后使用的 App 名称为 `bar`，`rootfs.custom_packages` 中引用此 App 时必须写 `bar`

---

### Requirement: 本地 App 目录为默认根

构建系统 SHALL 把 `<project_root>/components/app/` 视为本地 App 的默认根目录；其任意子目录 `<project_root>/components/app/<name>/` 若包含 `app.yaml` 即被识别为一个本地 App。本目录的识别行为 MUST NOT 受任何配置字段影响，始终启用。

#### Scenario: 本地 App 被默认识别

- **WHEN** `<project_root>/components/app/adbd/app.yaml` 存在，且 `external_apps` / `external_app_dirs` 均未声明
- **THEN** `flange list apps` 输出包含 `adbd` 条目，标签为 `[local]`

#### Scenario: 空的本地 App 目录被忽略

- **WHEN** `<project_root>/components/app/stub/` 存在但不含 `app.yaml`
- **THEN** 构建系统 SHALL 不把 `stub` 识别为 App，`list apps` 输出中不出现它

---

### Requirement: external_apps 字典支持 local_path 与 git 两种互斥分支

顶层配置键 `external_apps` SHALL 是一个 `dict[str, dict]`，每个条目表示一次显式的 App 注册。条目字典 MUST 声明以下二选一：

- `local_path: str` — 指向宿主机任意目录，内部需含 `app.yaml`；
- `git: str`（连同 `branch` / `commit` / `tag` / `ref` 等 git 相关字段）— 指向外部 git 仓库，由构建系统克隆到 `.build/sources/apps/<name>/`。

两个字段 MUST NOT 同时出现；二者都缺失时，构建系统 SHALL 报错终止。

#### Scenario: local_path 声明合法

- **WHEN** 配置包含 `external_apps = {"foo": {"local_path": "~/workspace/foo"}}`，且 `~/workspace/foo/app.yaml` 存在
- **THEN** 构建系统把 `foo` 识别为 out-of-tree local App，`list apps` 中标签为 `[external:local]`

#### Scenario: git 声明合法（向后兼容）

- **WHEN** 配置包含 `external_apps = {"bar": {"git": "https://example.com/bar.git", "tag": "v1.0"}}`
- **THEN** 构建系统在构建期把仓库克隆至 `.build/sources/apps/bar/`，行为与引入本变更之前一致，`list apps` 标签为 `[external:git]`

#### Scenario: 同时声明 local_path 与 git

- **WHEN** 配置包含 `external_apps = {"x": {"local_path": "...", "git": "..."}}`
- **THEN** 构建系统 SHALL 在配置解析阶段抛出明确错误，不允许继续

#### Scenario: 两者都缺失

- **WHEN** 配置包含 `external_apps = {"x": {}}`
- **THEN** 构建系统 SHALL 报错指出 `external_apps["x"]` 必须声明 `local_path` 或 `git` 之一

---

### Requirement: external_app_dirs 提供搜索路径，按顺序解析

顶层配置键 `external_app_dirs` SHALL 是一个 `list[str]`，可选。构建系统在查找某个 App 时 MUST 按列表顺序，检查每个目录下是否存在 `<dir>/<app_name>/app.yaml`，第一个命中即采用。未声明或为空列表时，本机制整体禁用。

#### Scenario: 单个搜索路径命中

- **WHEN** 配置 `external_app_dirs = ["~/vendor-apps"]`，且 `~/vendor-apps/wifi/app.yaml` 存在
- **THEN** 构建系统识别 `wifi` 为 out-of-tree App，`list apps` 标签为 `[dir:~/vendor-apps]`（或对应解析后的绝对路径）

#### Scenario: 多目录顺序解析

- **WHEN** 配置 `external_app_dirs = ["~/team-apps", "~/personal-apps"]`，且 `wifi` 在两处均存在
- **THEN** 构建系统取 `~/team-apps/wifi/`（列表中靠前者）为主来源

#### Scenario: 空列表等价于未声明

- **WHEN** 配置 `external_app_dirs = []`
- **THEN** 行为等同于不声明此键

---

### Requirement: App 查找优先级固定且显式注册压隐式搜索

当构建系统需要定位名为 `<name>` 的 App 时，SHALL 按以下顺序查找，第一个命中即终止：

1. `<project_root>/components/app/<name>/app.yaml`
2. `external_apps[<name>]` — 若存在，则严格解析此条目（不回退到后续层级）
3. `external_app_dirs` 中第一个含有 `<dir>/<name>/app.yaml` 的目录

若前述层级全部未命中，构建系统 SHALL 报错 `App '<name>' 未找到`，并在错误信息中列出已尝试的所有层级与对应路径，便于排错。

#### Scenario: 本地目录压过 external_apps

- **WHEN** `components/app/foo/app.yaml` 存在，同时 `external_apps = {"foo": {"local_path": "~/other/foo"}}`
- **THEN** 构建系统采用 `components/app/foo/`，`list apps` 主来源标签 `[local]`，但输出中标记 "also registered in external_apps"

#### Scenario: external_apps 命中后不回退

- **WHEN** `external_apps = {"bar": {"local_path": "~/broken/bar"}}` 但该路径不存在，且 `external_app_dirs = ["~/fallback"]` 下有 `bar/app.yaml`
- **THEN** 构建系统 SHALL 报错 `external_apps["bar"].local_path '~/broken/bar' 不存在`，不回退使用搜索路径

#### Scenario: 仅靠 external_app_dirs 命中

- **WHEN** `components/app/baz/` 与 `external_apps["baz"]` 均不存在，`external_app_dirs = ["~/apps"]` 下有 `baz/app.yaml`
- **THEN** 构建系统采用 `~/apps/baz/`

#### Scenario: 所有层级未命中

- **WHEN** 构建请求 `qux`，三个层级都没有
- **THEN** 报错 `App 'qux' 未找到`，错误信息列出本地路径、external_apps 键是否存在、external_app_dirs 各目录是否曾被检查

---

### Requirement: local_path 与 external_app_dirs 的路径解析规则一致

所有路径字段（`external_apps[name].local_path`、`external_app_dirs` 的每一项）SHALL 支持：

- `~` 展开至用户 HOME；
- 相对路径相对于 **project_root**（flange 仓库根目录）解析；
- 存储进 FINAL_CONFIG 前 resolve 为绝对路径。

#### Scenario: 用户目录展开

- **WHEN** `local_path = "~/workspace/foo"`
- **THEN** 解析后存储的路径为 `<HOME>/workspace/foo` 的绝对形式

#### Scenario: 相对路径相对 project_root

- **WHEN** `external_app_dirs = ["../vendor"]`，project_root 为 `/home/eki/flange`
- **THEN** 解析后该项对应 `/home/eki/vendor`

---

### Requirement: flange create app 默认写入 components/app/\<name\>/

`flange create app <name>` 在未指定 `--dir` 时，SHALL 把脚手架生成到 `<project_root>/components/app/<name>/`。目标目录已存在时报错终止，不覆盖。

#### Scenario: 默认路径

- **WHEN** 在 `<project_root>` 下执行 `flange create app myapp`，且 `components/app/myapp/` 不存在
- **THEN** 脚手架被生成到 `<project_root>/components/app/myapp/`，stdout 输出该绝对路径

#### Scenario: 目标已存在

- **WHEN** `components/app/myapp/` 已存在
- **THEN** 命令 SHALL 报错终止，不修改任何文件

---

### Requirement: flange create app 支持 --dir 指定父目录

`flange create app <name> --dir=<path>` SHALL 把脚手架生成到 `<path>/<name>/`；其中 `<path>` 是**父目录**（非完整目标路径），最终目录名永远取自 `<name>` 实参。`<path>` SHALL 支持 `~` 展开与相对路径（相对当前工作目录）。

#### Scenario: 绝对路径父目录

- **WHEN** 执行 `flange create app wifi --dir=/home/eki/vendor-apps`
- **THEN** 脚手架被生成到 `/home/eki/vendor-apps/wifi/`

#### Scenario: 带 ~ 的父目录

- **WHEN** 执行 `flange create app wifi --dir=~/vendor-apps`
- **THEN** 脚手架被生成到 `<HOME>/vendor-apps/wifi/`

#### Scenario: 父目录不存在

- **WHEN** `--dir=<path>` 指向的父目录不存在
- **THEN** 命令 SHALL 自动创建必要的父目录后继续生成，保持与默认路径行为一致

#### Scenario: 目标子目录已存在

- **WHEN** `<path>/<name>/` 已存在
- **THEN** 命令 SHALL 报错终止，不覆盖任何内容

---

### Requirement: create app 生成 out-of-tree 位置后输出注册指引

当 `flange create app` 用 `--dir` 把脚手架生成到 `components/app/` 之外的目录时，命令 SHALL 在 stdout 末尾打印一段注册指引文本，告诉用户如何将该路径加入 `external_apps` 或 `external_app_dirs`；命令 MUST NOT 自动修改任何 config.py 文件。

#### Scenario: out-of-tree 创建后输出指引

- **WHEN** 执行 `flange create app wifi --dir=~/vendor-apps`
- **THEN** 脚手架生成成功后，stdout 额外打印提示块，包含形如 `external_apps["wifi"] = {"local_path": "<abs>"}` 或 `external_app_dirs = ["<parent-abs>"]` 的示例配置片段

#### Scenario: 默认路径创建不输出指引

- **WHEN** 执行 `flange create app wifi`（无 `--dir`）
- **THEN** 命令不输出注册指引（因为路径已在默认扫描范围内）

---

### Requirement: flange list apps 遍历所有来源并标注

`flange list apps` SHALL 遍历三个层级收集所有被识别的 App：本地 `components/app/*`、`external_apps` 显式注册、`external_app_dirs` 搜索。每行输出 SHALL 包含 App 名称、类型、版本、描述以及来源标签。来源标签取值为 `[local]` / `[external:local]` / `[external:git]` / `[dir:<path>]` 之一。

#### Scenario: 三层混合展示

- **WHEN** `components/app/` 下有 adbd；`external_apps = {"zigbee": {"git": "..."}}`；`external_app_dirs = ["~/vendor"]` 下有 wifi
- **THEN** `list apps` 输出三行，分别标签为 `[local]`、`[external:git]`、`[dir:~/vendor]`（或相应的解析后路径）

#### Scenario: 同名多来源的 also-found 标记

- **WHEN** `components/app/foo/` 存在，同时 `external_apps = {"foo": {"local_path": "~/other"}}`
- **THEN** `list apps` 为 `foo` 输出一行，主来源标签 `[local]`，紧随一行 `(also found in: external_apps[local])`

#### Scenario: external_app_dirs 下枚举

- **WHEN** `external_app_dirs = ["~/vendor-apps"]`，其下 `wifi/app.yaml` 与 `bt/app.yaml` 存在
- **THEN** 两个 App 都出现在输出，标签相同 `[dir:<abs>]`
