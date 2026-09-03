---
title: out-of-tree app 构建
type: workflow
status: stable
sources:
  - builder/dev.py
  - builder/app_spec.py
  - builder/app.py
  - builder/deploy.py
  - builder/docker.py
  - envsetup.sh
related:
  - "[[scaffold 新建 app 流程]]"
  - "[[external_apps 装载]]"
  - "[[app 打包系统]]"
  - "[[硬件特性包]]"
updated: 2026-09-03
---

## TL;DR

`flange app create|build|deploy|run|debug|log` 是 App 的资源优先入口。它可以在
flange 仓库外执行；除 `create` 外，目标可为已注册的 App 名称或含
`app.yaml` 的目录路径，省略时默认使用调用者当前目录。路径模式是
ad-hoc（即时）开发，无需修改 lunch config 或 App registry。

## 从仓库外完成开发闭环

先 `source <flange>/envsetup.sh` 并用 `lunch` 选择 target，然后可在任意目录执行：

```bash
mkdir -p /work/vendor
cd /work/vendor

# create 默认以当前目录为父目录，生成 /work/vendor/demo
flange app create demo --type exec --build-system cmake
cd demo

# 其余命令省略 target 时使用当前目录
flange app build
flange app deploy --serial <adb-serial>
flange app run --serial <adb-serial> -- --port 9000
flange app debug --serial <adb-serial> -- --port 9000
flange app log --serial <adb-serial>
```

`deploy` / `run` / `debug` 默认先构建，已有可用产物时可传
`--no-build`。`run` / `debug` 的 `--` 后参数会传给 exec App；有显式
action 时，会追加到该 action 的 argv。service App 的默认 `log` 在目标机
执行 `journalctl -u <unit> --no-pager -f`。默认 `debug` 仅在 debug variant
可用：exec App 以目标机 GDB `--args` 启动，service App 则附加（attach）当前
MainPID。release variant 应切换 target 或定义显式 `debug` action。默认
service 日志还支持 `--lines <n>`、`--since <time>` 与 `--no-follow`。

`--serial` 可用于 `deploy` / `run` / `debug` / `log`。未指定时，flange 只在
ADB 恰好有一台状态为 `device` 的设备时自动选择；无设备或多设备均会在
部署或启动前失败。

## 目标解析与产物

- 绝对路径、以 `.` 开头的路径、含 `/` 的路径，或当前目录下已存在的目录，
  按路径解析并校验 `app.yaml`。相对路径总是相对调用者 cwd。
- 其余值按 App 名称通过本地 `components/app/` → `external_apps` →
  `external_app_dirs` 查找，详见 [[external_apps 装载]]。
- flange 先在宿主机解析外部目录，再将它 bind mount 进最外层 Docker。
  编译与打包仍发生在容器中。
- `.deb` 统一写入仓库
  `.build/target/<board>/<product>/<variant>/app/<name>_<version>_<arch>.deb`。
  ad-hoc 路径不会改写 config，也不会出现在 `flange list apps`。

## 显式 actions

App 可在 `app.yaml` 顶层为无法安全推断的生命周期定义 argv（参数向量）：

```yaml
actions:
  build: ["./tools/build.py", "--profile", "debug"]
  deploy: ["./tools/deploy.py"]
  run: ["./tools/run.py", "--mode", "safe"]
  debug: ["./tools/debug.py"]
  log: ["./tools/log.py"]
```

只允许 `build` / `deploy` / `run` / `debug` / `log`，每个值必须是由非空字符串
组成的非空列表。未知键、shell 命令字符串、空列表或非字符串元素都会在
执行前被拒绝。显式 action 是对同名生命周期的自包含覆盖：flange 不会再
自动插入构建、部署或默认运行步骤。`build` action 在 Docker 内以 App 目录为
cwd 执行，并应通过 `FLANGE_TARGET_DIR` 发布产物；其余 action 在宿主机
App 目录中执行。设备 action 可从 `FLANGE_ADB_SERIAL` 读取已校验的设备。例如：

```bash
flange app run -- --port 9000
# 直接执行 argv：./tools/run.py --mode safe --port 9000
```

flange 不经 shell 拆词、插值或 `eval`，所以 `;`、`$()` 等内容只是普通
argv 元素。但 action 程序本身仍拥有对应运行环境的权限：只应使用可信 App，
并审查宿主机上运行的 `deploy` / `run` / `debug` / `log` 脚本。

## 兼容入口

以下动词优先形式仍可用，并委托给同一实现：

| 兼容入口 | 资源优先入口 |
|---|---|
| `flange build app <name-or-path>` | `flange app build <name-or-path>` |
| `flange push app <name-or-path>` | `flange app deploy <name-or-path>` |
| `flange run app <name-or-path>` | `flange app run <name-or-path>` |

`flange create app <name>` 也保留兼容，但未指定 `--dir` 时仍创建到仓库
`components/app/`；新入口 `flange app create <name>` 默认创建到调用者 cwd。
`flange build app` 不带单 App 目标时仍表示构建当前配置的所有 App。

路径含空格时仍要按调用 shell 的规则加引号，例如
`flange app build "/work/My App"`；进入 Python 编排层后不会再用 shell 重新解析。
