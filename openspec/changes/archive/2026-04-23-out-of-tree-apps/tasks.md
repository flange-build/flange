## 1. 配置模型落地

- [x] 1.1 在 `builder/config/merge.py` 或等价的配置校验入口，识别顶层 `external_app_dirs` 键（默认空列表）并在合并后 resolve 为绝对路径列表；无此键时表现为 `[]`
- [x] 1.2 在 `builder/config/merge.py`（或新建小模块）对 `external_apps[<name>]` 条目做校验：`local_path` 与 `git` 互斥、二者必填其一；违规抛出明确错误并附带配置键路径
- [x] 1.3 把 `external_apps[<name>].local_path` 与 `external_app_dirs[*]` 的路径做 `Path.expanduser()` + 相对 project_root 的绝对化统一处理，存回 FINAL_CONFIG
- [x] 1.4 新增 `tests/builder/test_config_external_apps.py`：覆盖合法 local_path、合法 git、两者同时存在、两者都缺失、`~` 展开、相对路径解析 6 个用例

## 2. App 查找逻辑（SourceManager + AppBuilder）

- [x] 2.1 在 `builder/source.py` 的 `SourceManager.ensure_app()` 中新增 `local_path` 分支：命中后展开绝对路径、校验 `app.yaml` 存在、直接返回 Path；分支内不触发任何 git 操作
- [x] 2.2 修改 `SourceManager.ensure_app()`：当 `external_apps[<name>]` 不存在时，追加第三层 `external_app_dirs` 搜索——顺序遍历，首个含 `<dir>/<name>/app.yaml` 的目录命中即返回
- [x] 2.3 `SourceManager.ensure_app()` 三层未命中时，报错文本需列出已尝试的所有层级与对应路径（local、external_apps 键是否存在、external_app_dirs 各目录）
- [x] 2.4 对齐 `builder/app.py` 的 `AppBuilder._find_app_dir()`：删除其内部"本地优先 + fallback 到 SourceManager"两段式逻辑，改为始终委托给新版 `ensure_app()`，保持单一职责
- [x] 2.5 在 `tests/builder/test_app_external.py` 扩展：为 local_path 命中、local_path 路径不存在、external_app_dirs 顺序命中、全部未命中 4 个用例各加一条测试

## 3. 脚手架命令 --dir 参数

- [x] 3.1 在 `builder/scaffold.py` 的 `AppScaffold.create()` 增加可选形参或封装辅助函数，区分"父目录"与"完整目标目录"——CLI 传入父目录时内部拼成 `<parent>/<name>/`
- [x] 3.2 在 `envsetup.sh` 的 `_flange_cmd_create_app` 中解析 `--dir=<path>` 选项，展开 `~`，相对路径以当前工作目录为锚点；将结果以"父目录"语义传给 `AppScaffold.create()`
- [x] 3.3 `AppScaffold.create()` 在生成位置不属于默认 `components/app/<name>/` 时，返回值或输出流附加一段注册指引文本（同时覆盖 `external_apps` 与 `external_app_dirs` 两种示例片段）
- [x] 3.4 在 `envsetup.sh` 的 `flange help` 文本里把 `[--dir=<path>]` 加入 `create app` 参数列表；说明为"父目录（默认 components/app/）"
- [x] 3.5 新增/扩展 `tests/builder/test_scaffold.py`：默认路径生成、`--dir=<parent>` 生成、父目录不存在时自动创建、目标 `<parent>/<name>/` 已存在时报错、out-of-tree 创建后有注册指引文本 5 个用例

## 4. list apps 命令扩展

- [x] 4.1 在 `envsetup.sh` 的 `_flange_cmd_list_apps`（当前为内联 Python），抽成独立模块 `builder/app_list.py` 的函数，接收 `project_root` 与 FINAL_CONFIG，返回 `[(name, type, version, description, source_label, also_found_in)]`
- [x] 4.2 `app_list.list_all()` 实现三层遍历：本地 `components/app/*/app.yaml`、`external_apps[*]`（按分支区分 `[external:local]` / `[external:git]`）、`external_app_dirs[*]/*/app.yaml`；解析每个 `app.yaml` 填充元数据
- [x] 4.3 同名多来源按查找优先级选主来源、记录 also-found 的其它来源；每行输出主来源标签，若存在其它来源则次行打印 `(also found in: ...)`
- [x] 4.4 `envsetup.sh` 的 `_flange_cmd_list_apps` 改为调用新模块并格式化输出；保留现有依赖缺失（PyYAML）的错误提示
- [x] 4.5 新增 `tests/builder/test_app_list.py`：纯本地、本地+external_apps_local+external_apps_git 三类共存、same-name-multi-source、`external_app_dirs` 下枚举多 App 共 4 个用例

## 5. 文档与集成验证

- [x] 5.1 更新 `docs/app-architecture.md`：新增"App 来源"小节（§8.4），阐述三层查找优先级与各自配置片段；`create app` 小节补 `--dir` 说明
- [x] 5.2 更新 `README.md` 命令表：`flange create app` 行后补参数；新增"引用 out-of-tree App"小节给 `external_apps.local_path` / `external_app_dirs` 示例片段
- [x] 5.3 在 `ProjectSpec.md` §9.1 新增"App 来源查找优先级"小节，描述三层优先级、互斥校验、路径解析规则与 `list apps` 标签
- [x] 5.4 本会话无 Docker / 实机条件下改为脚本化端到端冒烟：真实板子 `resolve_config('radxa-zero3w', 'default', 'release')` → `list_all` 识别既有 adbd；手写 tmp 场景验证三层查找命中 + 三层未命中错误信息含全部已尝试路径，全部通过
- [x] 5.5 `openspec validate out-of-tree-apps` 通过；`openspec status` 4/4 artifacts 全 done；本变更相关测试 107/107 通过（test_config_external_apps + test_app_external + test_scaffold + test_app_list + test_app_builder）。仓库内 test_engine/test_cache/test_cache_e2e/test_rootfs_deb 合计 29 个预先失败用例，经在干净 main 上复现确认与本变更无关（涉及 `BuildCache._hash_cache` / 依赖图 / dpkg 集成），应由独立变更处理
