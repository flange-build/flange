## Context

flange 的 App 子系统当前由三块代码协作完成 build/push/run：

- `builder/app.py`：`AppBuilder` 协调 App 查找、编译、打包成 `.deb`
- `builder/docker.py`：`DockerRunner` 通过 `docker compose run --rm build` 在容器内执行命令；容器内 `.:/workspace` 是唯一的 bind mount
- `builder/source.py`：`SourceManager.ensure_app` 实现三层查找（local → `external_apps` → `external_app_dirs`），已正确支持 `local_path` 指向仓库外的任意路径
- `builder/deploy.py`：`flange push/run app` 的入口，先 build、再 `adb push` / `dpkg -i`

理论上，把 App 放在仓库外并通过 `external_apps[name].local_path` 注册后，整套构建链路应该跑通。但实际有两个隐藏故障：

1. `envsetup.sh:392 / deploy.py:81` 在创建 `AppBuilder` 时传入 `source=None`，导致 `_find_app_dir` 走兜底分支只查 `components/app/<name>`，永远找不到外部 App。
2. 即使第 1 点修复，`DockerRunner._run_docker` 只挂 `.:/workspace`，外部 App 目录在容器内根本不可见，`cwd=app_dir` 会失败。

同时，用户希望除"配置注册"之外，还能用 `flange build app <path>` 这种 ad-hoc 形式直接编一个 out-of-tree App，特别适合 `flange create app --dir=...` 之后的快速验证。

## Goals / Non-Goals

**Goals:**

- `flange build/push/run app <name-or-path>` 位置参数自动识别 name vs path；含 `/` 或 `.` 或路径存在且含 `app.yaml` → 视为路径。
- 外部 App 编译时 Docker 容器内能访问 `app_dir`，cmake/meson 能在源码目录写 `build/` 中间产物。
- `.deb` 产物统一落在仓库内 `.build/target/<board>/<product>/<variant>/app/`，与现有 push/flash 链路无缝衔接。
- 顺手修通"已注册 external_apps 但 build 失败"的底层 bug。

**Non-Goals:**

- 不自动把 ad-hoc path 写回 lunch config 的 `external_apps`。
- 不限制路径必须落在某个根目录下（用户自负其责）。
- `.deb` 不回写到外部目录（保持产物收口于仓库 `.build/`，便于 `flange flash` / `find_latest_deb` 一致查找）。
- `flange list apps` 行为不变：ad-hoc path 不入列表（本来就没注册）。
- 不动 git 来源 App（`external_apps[name].git`）的现有行为。

## Decisions

### 决策 1：path 判定放在 Python 一处实现，shell 仅透传

**选择**：`envsetup.sh` 不在 shell 侧判定 name 还是 path，直接把首个非 flag 参数传给 Python。Python 侧统一封装 `_resolve_app_arg(arg, source, config) -> (app_dir: Path, app_name: str)`：

```
若 arg 含 "/" 或以 "." 开头 或 (Path(arg).is_dir() and (Path(arg)/"app.yaml").is_file())：
    视为路径 → load_spec 拿 app_name
否则：
    视为 name → SourceManager.ensure_app(arg, config)
```

**理由**：

- Shell 字符串判定容易引入边界 bug（特殊字符、引号、`~` 展开），Python 侧用 `pathlib.Path` + `app.yaml` 实际存在性来判断更稳。
- `flange build` / `flange push` / `flange run` / `deploy.py` 都要做同样的判定，集中到一处。

**备选**：shell 侧用 `[[ "$arg" == */* ]] || [[ -d "$arg/app.yaml" ]]` 判定后传不同的命名参数。否决，重复逻辑、shell 转义脆。

### 决策 2：Docker 动态挂载，方向选 `host_realpath:host_realpath:rw`

**选择**：`DockerRunner.run(..., extra_mounts: list[Path] | None = None)`；仅在 `_run_docker` 分支生效（容器外触发），拼接为 `-v <realpath>:<realpath>:rw`。

**理由**：

- **路径保持不变**：源码目录在宿主机和容器内是同一个绝对路径，`cwd=app_dir` 在两侧都能用，编译命令中如有错误日志、`compile_commands.json` 也指向用户能直接打开的位置。
- **`realpath` 解析**：macOS 上 `/var` 是 `/private/var` 的 symlink，多层项目目录里也常见软链。`docker -v` 直接传带 symlink 的路径会让容器内看到一个 deref 后的奇怪路径；`os.path.realpath` 把它展平掉。
- **rw 不是 ro**：cmake/meson 默认会在源码同级建 `build/`，这是用户可预期且文件可由宿主机直接清理的行为；强制 ro 会逼出 out-of-source 改造，得不偿失。
- **`_run_docker` only**：`_run_direct` 走"已在容器内"分支，此时 path 要么已在 `/workspace` 子树，要么是上一层早已挂入的外部目录——不重复挂载。

**备选 A**：把外部目录挂到容器内一个固定虚拟路径（如 `/external-app`）。否决，cwd 路径在宿主和容器里不一致会让 cmake 的 `CMAKE_SOURCE_DIR` 之类宏指向容器内路径，IDE/调试体验差。

**备选 B**：把每条 `external_app_dirs` 静态加进 `docker-compose.yml`。否决，不支持 ad-hoc path；ad-hoc 用例必须有动态 -v 能力，那两条逻辑就重了，不如统一走动态。

### 决策 3：`AppBuilder.build_one` 接口统一为 `name_or_path: str`

**选择**：`build_one(name_or_path: str) -> Path`；内部 `_resolve_app_dir(arg) -> (Path, str)` 调用决策 1 的判定逻辑；`build_all()` 因为只处理 `custom_packages`（按 name），不需要变。

**理由**：

- 单参形态对调用方最直观，shell 侧透传也最自然。
- 单元测试里调用 `build_one("foo")` 维持原行为，无需迁移；调用 `build_one("/abs/path")` 自动走外部分支。

**备选**：增 `build_one_path(path: Path)` 双方法。否决，强迫调用方做判定，违反 KISS。

### 决策 4：`source=None` 全部改成传入真正的 `SourceManager`

**选择**：

- `envsetup.sh:392 & 404`（`_flange_cmd_build` 的 app 分支两处）改成 `AppBuilder(DockerRunner(), SourceManager(project_root=Path('.')), cfg)`。
- `deploy.py:81` 内联构建子调用同步改。

**理由**：现状的 `source=None` 是早期开发占位，本就该是 bug；保留 `_find_app_dir` 中的 `source is None` 兜底分支供单元测试使用即可，无需删。

### 决策 5：`deploy.py` 仅入口解析路径，下半段不动

**选择**：`deploy_app(name_or_path, build_deb, run)`：

1. 用决策 1 的解析器拿到 `(app_dir, app_name, spec)`。
2. 若 `build_deb`，把 `name_or_path` 透传给内联的 `AppBuilder.build_one(...)`（在 docker compose run 子进程内）。
3. `find_latest_deb(app_name, config)` 仍然在仓库 `.build/target/.../app/` 按 name glob —— 因为 .deb 文件名是 `<app_name>_<version>_<arch>.deb`，与源在哪儿无关。
4. `adb push` / `dpkg -i` 完全不变。

**理由**：.deb 落地决策（决策 6）保证了"按 name 查仓库"对外部 App 同样有效，push/run 下半段零改动。

### 决策 6：.deb 产物统一落仓库 `.build/`，外部目录只接收编译中间物

**选择**：`AppBuilder._output_dir` 维持 `<project_dir>/.build/target/<board>/<product>/<variant>/app/`，与外部源码目录无关。

**理由**：

- `flange flash` / `flange push` / `find_latest_deb` 都已按 board/product/variant 查仓库 `.build/`，把外部 App 也收口在这里维持单一权威位置。
- 外部目录里只会出现 cmake/meson 自然生成的 `build/`，与用户手工 `cmake -B build` 体验一致；用户清理自己的目录即可，无 flange 产物泄漏。

### 决策 7：路径作为 ad-hoc 触发，不影响 registry

**选择**：`flange build app <path>` 不读写 `external_apps` / `external_app_dirs`；`flange list apps` 输出也不变。

**理由**：

- registry 是"团队级、随仓库分发"的注册；ad-hoc path 是"个人开发期"的短链路。两者分层清晰更利于维护。
- 用户希望沉淀某个 ad-hoc App，仍可手工把 `external_apps[name].local_path = <abs>` 加进 board/platform config。

## Risks / Trade-offs

- **[Risk] 用户传入相对路径在 docker compose 调用上下文里被错误解析**
  → Mitigation：Python 侧统一在解析阶段 `Path(arg).resolve()` + `os.path.realpath`，传给 `-v` 时永远是绝对路径。
- **[Risk] 外部目录里残留旧 `build/` 与新构建配置不兼容**
  → Mitigation：不在 flange 侧自动清，提示文字遵循"建议手工 `rm -rf build`"——这是 cmake/meson 标准卫生习惯，flange 不越权。
- **[Risk] 外部目录与仓库源码同名 App 引发歧义**（例如 `flange build app /tmp/foo`，但 `components/app/foo` 也存在）
  → Mitigation：因为走 path 分支时不咨询 registry，行为是确定的——以 path 内的 `app.yaml` 为准。仓库内同名 App 不参与本次构建，互不影响。
- **[Risk] `_run_docker` 命令行长度膨胀**（一次只挂一两个目录，影响不大）
  → Mitigation：暂不考虑；若未来出现批量外部 deps 编译，再考虑 docker-compose override 路线。
- **[Trade-off] `extra_mounts` 仅作用于 `_run_docker` 分支**：在 `_run_direct`（已在容器内）下被忽略；当前不会出现"容器内代码调 `AppBuilder.build_one(<外部 path>)`"的场景，但若未来在已经 `docker compose run` 进入的 shell 里再嵌套调 build_one，外部路径访问需依赖外层挂载——可接受，因为开发者既然已经进容器，应自行规划挂载。

## Open Questions

无。
