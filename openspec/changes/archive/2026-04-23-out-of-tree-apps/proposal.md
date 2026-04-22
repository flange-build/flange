## Why

flange 当前仅支持把 App 工程写在 `components/app/<name>/` 仓库内部目录，`external_apps` 配置字段只识别 git 仓库模式，无法让用户把 App 源码放在宿主机任意目录（例如团队共享的 vendor 目录、个人 workspace、或另一个独立 git 仓库）并在当前构建中复用。`flange create app` 命令也硬写入仓库内目录，无法为 out-of-tree 工程生成脚手架。结果是：同一份 App 必须复制进每个 flange 仓库副本，破坏了"代码 / 内容 / 产物"三层分离的语义，也无法支持多产品共享 App 源的工程场景。

## What Changes

- `flange create app` 新增 `--dir=<path>` 参数，允许把脚手架直接生成到任意目录（默认仍为 `components/app/<name>/`）。
- `external_apps` 字典新增 `local_path` 字段（与现有 `git` 字段互斥、二选一），允许显式把单个 App 名称绑定到宿主机任意目录，不再经过 `.build/sources/apps/` 克隆。
- 新增顶层配置 `external_app_dirs`（字符串列表），作为 App 搜索路径；`<dir>/<app_name>/app.yaml` 存在时即被采用。
- `SourceManager.ensure_app()` 查找顺序改为：`components/app/<name>` → `external_apps` 显式注册（`local_path` 优先，其次 `git`）→ `external_app_dirs` 中首个命中目录。
- `flange list apps` 同步扩展：遍历上述全部来源，每行尾标注 `[local]` / `[external:local]` / `[external:git]` / `[dir:<path>]`。
- **向后兼容**：现有 `external_apps[<name>] = {"git": ...}` 的写法保持原语义不变；`external_app_dirs` 未声明时等价于空列表，行为等同于今日。

## 非目标

- 不改动 App 构建产物目录（依旧落 `.build/target/<board>/<product>/<variant>/app/`）。
- 不在本变更中重构 `external_apps` 现有 git 模式的 clone / commit / branch 处理逻辑，仅在其旁新增 `local_path` 分支。
- 不引入"工作空间 / manifest 文件"（例如 repo/west 式的外部 manifest），`external_app_dirs` 是平铺的字符串列表。
- 不处理 out-of-tree App 目录的版本管理：用户自行负责目录内容；flange 不 clone、不 checkout、不 reset。
- 不改变 `flange build app <name>` 的构建流程与缓存键规则。

## Capabilities

### New Capabilities

- `app-registry`: App 源的注册与发现模型——定义本地 App 目录、out-of-tree 单体注册（`external_apps.local_path` / git）、搜索路径（`external_app_dirs`）三类来源的配置格式、查找优先级与 `list apps` 展示规则；同时规定 `flange create app` 如何选择脚手架目标目录，以及生成后如何提示用户完成注册。

### Modified Capabilities

（无——现有 specs 里 `repo-layout`、`platform-abstraction`、`shared-repo-references` 等都不涉及 App 来源的规范化，本变更新建独立 capability。）

## Impact

- **代码**：`builder/source.py`（`SourceManager.ensure_app` 加分支与 local_path 校验）、`builder/scaffold.py`（`AppScaffold.create` 的目标目录选择逻辑与提示）、`builder/app.py`（`AppBuilder._find_app_dir` 与 `source` 的查找顺序对齐）、`envsetup.sh`（`_flange_cmd_create_app` 暴露 `--dir`，`_flange_cmd_list_apps` 扩展扫描来源）。
- **配置 / 文档**：`docs/app-architecture.md` 与 `README.md` 的 App 命令表需追加新参数与字段说明；`openspec/specs/app-registry/spec.md` 为本次新增。
- **测试**：`tests/builder/test_app_external.py` 扩展覆盖 `local_path` 与 `external_app_dirs` 两条新分支；`tests/builder/test_scaffold.py`（若存在）需加 `--dir` 用例，否则新增之。
- **依赖 / API**：无新外部依赖；FINAL_CONFIG 新增可选顶层键 `external_app_dirs`，`external_apps[<name>]` 新增可选键 `local_path`。
- **向后兼容**：所有既有配置无需修改即可继续构建。
