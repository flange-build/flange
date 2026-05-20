## Why

目前 `flange create app --dir=<path>` 已经能把 App 脚手架生成到仓库外任意目录，但配套的构建/部署链路实际上跑不通：

- `envsetup.sh` 里 `AppBuilder(DockerRunner(), None, cfg)` 传入 `source=None`，使 `_find_app_dir` 退化为"只看 `components/app/<name>`"，即便用户已在 lunch config 里写了 `external_apps[name].local_path`，`flange build app <name>` 也找不到。
- `DockerRunner` 只挂载 `.:/workspace`，没有任何把外部目录映射进容器的能力；外部 App 的源码在容器里根本不可见。
- `flange create app --dir=...` 的最佳用户路径——先创建、再构建、再 push——目前实际上只能跑到第一步。

我们需要让"out-of-tree App"成为一条完整闭环：从 `create --dir=...` 创建，到 `flange build/push/run app <path>` 一气呵成，路径作为位置参数自动识别，无需先去 lunch config 里注册。

## What Changes

- `flange build app <name-or-path>` 位置参数自动检测：含 `/` 或 `.` 或路径存在且含 `app.yaml` → 视为路径；否则按 name 走原有三层查找。
- `flange push app <name-or-path>` 与 `flange run app <name-or-path>` 同步支持路径形式。
- `DockerRunner.run` 新增 `extra_mounts: list[Path] | None` 参数；构建外部 App 时动态拼 `-v <realpath>:<realpath>:rw`，仅在 `_run_docker` 分支生效。
- `AppBuilder.build_one` 接受 name 或 path（实际入参 `name_or_path: str`），新增 `_resolve_app_dir` 统一解析；外部目录时把 `[app_dir]` 注入编译命令的 `extra_mounts`。
- `deploy.py` 的 `deploy_app` 入口先解析 path/name → `load_spec` → 拿到真正的 `app_name`；构建子调用改为传 path；`find_latest_deb` 仍按 name 查仓库内 `.build/target/.../app/`。
- 修底层 bug：`envsetup.sh` 里 `_flange_cmd_build` 的 app 分支以及 `deploy.py` 内联构建调用，都把 `source=None` 换成真正的 `SourceManager`，使已注册的 `external_apps` / `external_app_dirs` 应用也能正确走通编译。
- **产物落地**：`.deb` 仍统一写到仓库内 `.build/target/<board>/<product>/<variant>/app/`，**不**回写到外部目录；外部目录仅允许编译期 cmake/meson 在 `build/` 子目录写中间产物（与手工 `cmake -B build` 行为一致）。

## Capabilities

### New Capabilities

- `out-of-tree-app-build`：规范 `flange build/push/run app` 对位置参数的 name vs path 双路语义、外部 App 编译时 Docker 容器的动态挂载策略，以及 .deb 产物统一落地在仓库 `.build/` 的约束。

### Modified Capabilities

（无）

> 说明：本变更不修改 `app-registry` 的注册与发现规则。`external_apps.local_path` / `external_app_dirs` 的查找语义保持不变；本次只把已声明但因 bug 而走不通的链路修通，并新增"ad-hoc path 不经 config 直接构建"的语义入口。

## Impact

- 修改文件：
  - `builder/docker.py`（`DockerRunner.run` 增 `extra_mounts` 参数）
  - `builder/app.py`（`AppBuilder.build_one` 接受路径；`_resolve_app_dir` 解析；外部目录时注入 `extra_mounts`）
  - `builder/deploy.py`（`deploy_app` 路径解析；内联构建子调用传 path；修 `source=None`）
  - `envsetup.sh`（`_flange_cmd_build` app 分支、`_flange_cmd_push`、`_flange_cmd_run` 首个非 flag 参数透传；`AppBuilder(..., source=SourceManager(...), ...)`）
- 新增测试：
  - `tests/test_docker.py`：`extra_mounts` 拼 `-v` 正确
  - `tests/test_app_builder.py`：`build_one(<path>)` 走外部分支、`extra_mounts` 注入
  - `tests/test_deploy.py`：`deploy_app(<path>)` 路径解析与 .deb 查找复用
- 用户可见行为：
  - `flange build app /abs/path/to/app` 直接构建（之前会报"App 不存在"）
  - `flange push app /abs/path/to/app` 直接构建 + 推送（之前同样不可用）
  - 已在 lunch config 注册 `external_apps[x].local_path` 的 App，从此真正可以 `flange build app x` 编通（bug 修复带来的副作用）
- **非目标**：
  - 不自动把 ad-hoc path 注册回 lunch config
  - 不限制路径的物理位置（用户自负其责）
  - 不修改 `flange list apps` 行为（ad-hoc path 仍不出现在列表里，因为它本来就没注册）
  - 不在 push/run 链路上支持把外部 .deb 缓存复用（每次 push 都走 build 子流程，与现有 `--no-build` 仅用于复用仓库内最新 .deb 的语义一致）
- 兼容性：
  - 对纯 name 用例完全兼容；现有 `flange build app adbd` / `flange push app adbd` 不受影响
  - 不修改 docker-compose.yml，本地的 `.:/workspace` 挂载继续保留
