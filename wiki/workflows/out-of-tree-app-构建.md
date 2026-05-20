---
title: out-of-tree app 构建
type: workflow
status: stable
sources:
  - builder/app.py
  - builder/deploy.py
  - builder/docker.py
  - envsetup.sh
related:
  - "[[scaffold 新建 app 流程]]"
  - "[[external_apps 装载]]"
  - "[[app 打包系统]]"
updated: 2026-05-21
---

## TL;DR

`flange build/push/run app` 的位置参数支持两种形态：**应用名** 或 **宿主机目录路径**。路径形态走 ad-hoc 模式，不需要在 lunch config 里注册即可即时构建 / 推送，特别适合 `flange create app --dir=<外部目录>` 之后的快速验证。

## 触发判定

判定在 Python 侧统一实现（[`builder/app.py:_resolve_app_dir`](../../builder/app.py)），shell 仅透传首个非 flag 参数。满足以下任一条件即视为路径：

- 字符串含有 `/`
- 字符串以 `.` 开头
- 字符串解析后是存在的目录且其下含 `app.yaml`

否则按应用名走 `SourceManager.ensure_app` 三层查找（本地 → `external_apps` → `external_app_dirs`，详见 [[external_apps 装载]]）。

## 工作流：create → build → push

```bash
# 1. 在仓库外任意位置生成脚手架
flange create app demo --dir=/tmp --type=exec --build-system=cmake
# → /tmp/demo/ 内含 app.yaml、CMakeLists.txt、src/main.c

# 2. ad-hoc 构建（无需注册到 config）
flange build app /tmp/demo
# → 产物 .deb 落在 .build/target/<board>/<product>/<variant>/app/demo_*.deb

# 3. 热部署到设备
flange push app /tmp/demo
# 或直接运行：
flange run app /tmp/demo
```

也接受相对路径：

```bash
cd /tmp
flange build app ./demo
flange build app demo            # cwd 下存在 demo/app.yaml 时也按路径解析
```

## 容器内的源码可见性

Docker 默认只挂 `.:/workspace`。AppBuilder 检测到 `app_dir` 不在项目根目录子树内时，自动通过 `DockerRunner.extra_mounts` 给 `docker compose run` 追加 `-v <realpath>:<realpath>:rw`，挂载方向保持源路径与目标路径一致——cwd 在宿主与容器内是同一个绝对路径，cmake 的 `CMAKE_SOURCE_DIR`、`compile_commands.json` 等都指向用户能直接打开的位置。

`realpath` 会展平 symlink（macOS 上 `/var` → `/private/var` 之类），避免容器内出现 deref 后的非预期路径。

## 产物落地约定

- `.deb`：统一写到仓库 `.build/target/<board>/<product>/<variant>/app/<name>_<version>_<arch>.deb`，无论源码来自仓库内、`external_apps`、`external_app_dirs` 还是 ad-hoc 路径。
- **外部目录里只会出现 cmake/meson 自然生成的 `build/`**，与你在该目录手工跑同样构建命令的行为一致。flange 不在外部目录写任何 `.deb`。

## 与 registry 注册的关系

| 场景 | 适合 |
|---|---|
| `flange build app <path>` ad-hoc | 个人开发期、`flange create --dir=...` 后的快速验证 |
| `external_apps[name].local_path` | 团队级、随仓库 config 分发的 out-of-tree App |
| `external_apps[name].git` | 远端 git 仓库（详见 [[external_apps 装载]]） |
| `external_app_dirs` | 把整个父目录当搜索路径（多 App 批量） |

ad-hoc path 不读写 lunch config，也不出现在 `flange list apps` 输出里——它本来就没注册。需要沉淀的话再手工把 `external_apps[name].local_path = <abs>` 加进 board/platform config。

## 已知限制

- `--no-build` 模式下 `flange push app <path>` 不会回退到外部目录搜索 `.deb`，仍只在仓库 `.build/.../app/` 按 spec 中的 `app.name` 查 `<name>_*.deb`。先 build 过一次后再 `--no-build` 才有效。
- 路径中含特殊字符（空格、引号）时，shell 透传可能踩坑——使用 `"` 包裹路径即可。
