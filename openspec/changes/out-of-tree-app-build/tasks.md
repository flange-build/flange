## 1. DockerRunner 注入 extra_mounts

- [x] 1.1 `builder/docker.py` 给 `DockerRunner.run` 增 `extra_mounts: list[Path] | None = None` 参数，签名兼容现有调用
- [x] 1.2 `_run_docker` 分支拼 `-v <realpath>:<realpath>:rw`：循环 extra_mounts，对每条调用 `os.path.realpath` 后追加到 `docker_cmd`
- [x] 1.3 `_run_direct` 分支：参数签名接收但忽略 `extra_mounts`（已在容器内）
- [x] 1.4 `_run_with_capture` 透传 `extra_mounts` 至 `_run_docker`（如果走容器外捕获分支）
- [x] 1.5 `run_privileged` 透传 `extra_mounts`

## 2. AppBuilder 支持路径入参

- [x] 2.1 `builder/app.py` 新增 `_resolve_app_dir(arg: str) -> Path`：实现"含 `/`、以 `.` 开头、目录存在且含 app.yaml → path 分支"判定（name 走 `_find_app_dir`，spec 在 `build_one` 中按惯例加载）
- [x] 2.2 `build_one(name_or_path: str)` 用 `_resolve_app_dir` 替换原 `_find_app_dir` 调用；保留对 `_find_app_dir` 的兜底（纯 name 走 SourceManager）
- [x] 2.3 `_compile` 接收并计算 `extra_mounts`：当 `app_dir` 不在 `self._project_dir` 子树时设为 `[app_dir]`，否则为 None
- [x] 2.4 `_compile` 调用 `self._docker.run(cmd, cwd=str(app_dir), extra_mounts=extra_mounts)`
- [x] 2.5 路径不存在或缺 `app.yaml` 时抛 `FileNotFoundError`，错误信息含原始字符串

## 3. envsetup.sh 透传与 SourceManager 修复

- [x] 3.1 `_flange_cmd_build` 的 app 分支：把 `$app_name` 透传给 `AppBuilder.build_one(name_or_path)`（不在 shell 侧判定）
- [x] 3.2 `_flange_cmd_build` 两处 `AppBuilder(DockerRunner(), None, cfg)` 改为传入 `SourceManager(project_root=Path('.'))`
- [x] 3.3 `_flange_cmd_push` / `_flange_cmd_run` 首个非 flag 参数原样透传给 `deploy.py`，不在 shell 判定
- [x] 3.4 帮助文本（`flange build --help` / `push --help` / `run --help`）更新："app `<name-or-path>`" 取代 "app `<name>`"

## 4. deploy.py 入口解析路径

- [x] 4.1 `deploy_app(name_or_path, build_deb, run)` 新增入口逻辑：复用 `_resolve_app_arg` 拿 `(app_dir, app_name, spec)`
- [x] 4.2 内联构建子调用：把 `name_or_path` 透传给 `AppBuilder.build_one`；同时 `AppBuilder(DockerRunner(), SourceManager(...), cfg)` 修 `source=None`
- [x] 4.3 `find_latest_deb(app_name, config)` 保持按 name 在仓库 `.build/target/.../app/` 查；不动
- [x] 4.4 `argparse` 参数 `app_name` 改名 `app`（位置参数），help 文本更新

## 5. 单元测试

- [x] 5.1 `tests/builder/test_docker_extra_mounts.py`：mock subprocess，验证 `extra_mounts=[Path("/a/b")]` 时 `_run_docker` 命令列表里含 `-v /a/b:/a/b:rw`
- [x] 5.2 同文件：含 symlink 路径经 realpath 解析后挂载
- [x] 5.3 同文件：`_run_direct` 路径下 `extra_mounts` 被忽略
- [x] 5.4 `tests/builder/test_app_builder.py`：`build_one(<外部 path>)` 走外部分支，`_compile` 收到非空 `extra_mounts`
- [x] 5.5 同文件：`build_one("foo")`（纯 name）走 SourceManager 分支，`extra_mounts=None`
- [x] 5.6 同文件：`_resolve_app_dir` 三种判定（含 /、点开头、目录存在）各一例
- [x] 5.7 同文件：路径不存在时 `build_one` 抛带原始字符串的错误
- [x] 5.8 `tests/builder/test_deploy.py`：`deploy_app("<外部 path>", build_deb=False, run=False)` 能解析路径、按 spec 中的 name 查 .deb
- [x] 5.9 同文件：`deploy_app("adbd", ...)`（纯 name）行为不变

## 6. 文档与 wiki

- [x] 6.1 `wiki/workflows/out-of-tree-app-构建.md` 新增；`workflows/index.md` 与 `wiki/log.md` 同步
- [x] 6.2 README 命令清单两行更新："`<name-or-path>`" + 新增 push/run 行
- [ ] 6.3 真机端到端验收（需用户在 lunch target + 设备连通环境下执行；自动化测试链路已用 mock 覆盖）
