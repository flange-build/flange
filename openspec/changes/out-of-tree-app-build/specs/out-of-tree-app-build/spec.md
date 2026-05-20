## ADDED Requirements

### Requirement: build/push/run app 命令位置参数支持路径形式

`flange build app`、`flange push app`、`flange run app` 三条子命令 SHALL 接受单一位置参数 `<name-or-path>`。当参数满足以下任一条件时，构建系统 MUST 将其视为路径并直接定位 App，否则按 App 名称走 `app-registry` 三层查找：

- 字符串中含有 `/`
- 字符串以 `.` 开头
- 字符串解析后是一个存在的目录，并在该目录下存在 `app.yaml` 文件

判定与解析 MUST 在 Python 侧统一实现，shell 端 MUST NOT 自行判断；shell 仅透传首个非 flag 参数。当判定为路径但目录或 `app.yaml` 不存在时，构建系统 SHALL 立即报错终止，错误信息 MUST 包含用户传入的原始字符串。

#### Scenario: 含斜杠的相对路径被识别为路径

- **WHEN** 用户执行 `flange build app ./my-app`，且 `./my-app/app.yaml` 存在
- **THEN** 构建系统按路径分支加载 App，从 `app.yaml` 读取 `app.name`，不查阅 `external_apps` / `external_app_dirs`

#### Scenario: 绝对路径被识别为路径

- **WHEN** 用户执行 `flange build app /home/user/work/foo`，且 `/home/user/work/foo/app.yaml` 存在
- **THEN** 构建系统按路径分支加载 App

#### Scenario: 纯名称走 registry 查找

- **WHEN** 用户执行 `flange build app adbd`
- **THEN** 构建系统按名称分支调用 `SourceManager.ensure_app("adbd", config)`，沿用 `app-registry` 三层查找语义

#### Scenario: 路径不存在时报错

- **WHEN** 用户执行 `flange build app /tmp/nonexistent`
- **THEN** 构建系统 SHALL 报错指出 `/tmp/nonexistent` 不存在或缺失 `app.yaml`，错误信息中 MUST 出现 `/tmp/nonexistent` 原始字符串

#### Scenario: 当前目录被识别为路径

- **WHEN** 用户在 App 工程目录内执行 `flange build app .`，当前目录存在 `app.yaml`
- **THEN** 构建系统按路径分支加载当前目录的 App

---

### Requirement: 外部 App 编译时容器内必须能访问源码目录

当 `AppBuilder._compile` 处理的 App 目录不位于项目根目录（`<project_dir>`）子树内时，构建系统 SHALL 通过 `DockerRunner` 的 `extra_mounts` 机制把该目录挂载到容器内，挂载源路径与目标路径相同。挂载属性 MUST 为 `rw`，允许 cmake/meson 等构建系统在源码目录下创建 `build/` 中间产物目录。

挂载路径 MUST 经过 `os.path.realpath` 解析，去除 symlink 跳板，避免容器内出现 deref 后的非预期路径。`extra_mounts` 仅对 `_run_docker` 分支生效，`_run_direct`（已在容器内）MUST 忽略该参数。

#### Scenario: 外部 App 编译时动态挂载

- **WHEN** 用户在容器外执行 `flange build app /home/user/foo`，且 `/home/user/foo` 不在项目根目录之下
- **THEN** `DockerRunner._run_docker` 拼接的 `docker compose run` 命令 SHALL 包含 `-v /home/user/foo:/home/user/foo:rw`（实际为 `realpath` 解析后的绝对路径），且容器内 `cwd` 设为同一绝对路径

#### Scenario: 仓库内 App 不触发额外挂载

- **WHEN** 用户执行 `flange build app components/app/adbd`，App 路径位于项目根目录之下
- **THEN** 构建系统 SHALL NOT 注入额外的 `-v`，`docker compose run` 命令保持默认挂载

#### Scenario: 路径含 symlink 时解析后挂载

- **WHEN** App 目录路径 `/var/work/foo` 实际是 `/private/var/work/foo` 的 symlink（macOS）
- **THEN** 挂载参数中 source 与 destination 均为 `/private/var/work/foo`

#### Scenario: 容器内调用忽略 extra_mounts

- **WHEN** `DockerRunner._run_direct` 接收到 `extra_mounts` 参数
- **THEN** 该参数被忽略，命令直接通过 `subprocess.run` 执行，不再拼接任何 docker 参数

---

### Requirement: .deb 产物统一落仓库 .build/，不写回外部目录

无论 App 源码位于仓库内 `components/app/<name>/`、`external_apps[name].local_path`、`external_app_dirs[*]/<name>/`，还是用户传入的 ad-hoc 路径，`AppBuilder` 输出的 `.deb` 文件 MUST 写到 `<project_dir>/.build/target/<board>/<product>/<variant>/app/<name>_<version>_<arch>.deb`。

构建系统 MUST NOT 在外部源码目录下写入或复制 `.deb` 文件。允许在外部源码目录中由 cmake/meson 等构建工具自然生成的中间产物（如 `build/`、`.o` 等）存在，这与用户在该目录手工运行同样构建命令的行为一致。

#### Scenario: 外部 App 的 .deb 产物落仓库

- **WHEN** 用户执行 `flange build app /home/user/foo`，board=`opi5plus`、product=`default`、variant=`release`
- **THEN** 生成的 .deb 路径 SHALL 为 `<project_dir>/.build/target/opi5plus/default/release/app/foo_<ver>_arm64.deb`，且 `/home/user/foo/` 目录下不出现任何 `*.deb` 文件

#### Scenario: 外部目录可写入 cmake 中间产物

- **WHEN** `/home/user/foo` 的 `app.yaml` 中 `build.system: cmake`，构建被触发
- **THEN** 在 `/home/user/foo/build/` 下生成 cmake 中间产物（CMakeFiles、Makefile、目标对象等），不报错

---

### Requirement: flange push/run app 接受路径并复用按 name 查 .deb 的链路

`flange push app <name-or-path>` 与 `flange run app <name-or-path>` SHALL 按"build/push/run app 命令位置参数支持路径形式"要求完成路径解析，从 `app.yaml` 读出真正的 `app_name`，然后：

- 若未指定 `--no-build`，触发 `AppBuilder.build_one(<name-or-path>)`（透传原始参数）；
- 调用 `find_latest_deb(app_name, config)` 在仓库 `.build/target/<board>/<product>/<variant>/app/` 按名称匹配 `<app_name>_*.deb`，取 mtime 最新者；
- 后续 `adb push` / `dpkg -i` / `systemctl restart` / 直接执行 等链路 MUST 与按名称形式完全一致，不再因路径分支而走不同代码。

#### Scenario: push 外部 App

- **WHEN** 用户执行 `flange push app /home/user/foo`
- **THEN** 构建系统先按路径分支构建并生成 `.build/target/.../app/foo_<ver>_arm64.deb`，再用 `app_name="foo"` 触发 adb push + dpkg -i 链路

#### Scenario: run 外部 service App

- **WHEN** 用户执行 `flange run app /home/user/bar`，`bar` 在 `app.yaml` 中声明 `type: service`
- **THEN** 部署完成后构建系统 SHALL 在设备上执行 `systemctl daemon-reload` + `systemctl restart bar.service`，与按名称运行 service App 时一致

#### Scenario: push 时配合 --no-build

- **WHEN** 用户执行 `flange push app /home/user/foo --no-build`
- **THEN** 构建系统跳过构建步骤，直接在仓库 `.build/target/.../app/` 查 `foo_*.deb`，找不到则报错（不回退到外部目录搜索）

---

### Requirement: 已注册 external app 的构建链路必须修复

`flange build app <name>`、`flange push app <name>`、`flange run app <name>`，当 `<name>` 由 `external_apps[name].local_path`、`external_apps[name].git` 或 `external_app_dirs` 注册时，构建系统 SHALL 通过 `SourceManager.ensure_app` 正确解析路径并完成编译。在 `AppBuilder` 构造点 MUST 传入真正的 `SourceManager` 实例；`source=None` 的兜底分支仅限单元测试使用。

#### Scenario: external_apps.local_path 注册的 App 可被编译

- **WHEN** lunch target 的 config 含 `external_apps = {"foo": {"local_path": "/home/user/foo"}}`，用户执行 `flange build app foo`
- **THEN** 构建系统按 `SourceManager.ensure_app` 解析到 `/home/user/foo`，并按"外部 App 编译时容器内必须能访问源码目录"要求挂载该目录，最终在仓库 `.build/.../app/` 下生成 `foo_*.deb`

#### Scenario: external_app_dirs 命中的 App 可被编译

- **WHEN** config 含 `external_app_dirs = ["/home/user/vendor-apps"]`，且 `/home/user/vendor-apps/bar/app.yaml` 存在，用户执行 `flange build app bar`
- **THEN** 构建系统按 `SourceManager.ensure_app` 解析到 `/home/user/vendor-apps/bar`，正常编译并产出 `.deb`
