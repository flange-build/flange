## Why

flange 的 App 开发能力目前散落在 `create/build/push/run app` 中，仓库外 ad-hoc 路径还会在最外层
Docker 挂载、调用者工作目录和构建产物收集处断链；硬件特性 Package 则只能由仓库内 board 配置启用，
没有独立开发入口。需要一组以资源为中心的命令，让开发者在任意工作目录完成 Package 与 App 的开发闭环。

## What Changes

- 新增 `flange package create|build|deploy|run|debug|log` 命令组，参数接受仓库内名称或仓库外路径，
  非 `create` 操作省略目标时默认使用当前目录。
- Package 继续使用现有 `package.py` 与 component 类型；`vendor` component 复用 App/Deb 流水线，
  无法由 component 类型推断的生命周期通过清单中的显式 argv action 执行。
- 新增 `flange app create|build|deploy|run|debug|log` 对称命令组，复用既有 AppBuilder、DebBuilder 和 ADB
  部署逻辑；旧的 verb-first 命令保留为兼容入口。
- 修通仓库外 App/Package 的调用者工作目录、lunch state、最外层 Docker bind mount 与统一 `.build/target`
  产物路径；CLI 参数通过 argv 传递，不再插入 `python -c` 或使用 `eval` 展开用户输入。
- 修复 App scaffold 的标准构建系统只编译却未安装到 deb staging、导致空 deb 的问题，保证
  create → build → deploy → run 的默认模板可用。
- App 的 service 默认支持跟随 journal；debug target 上的 exec/service 默认支持通过 ADB 启动目标机 GDB，
  不能可靠推断的 App/Package 可通过显式 action 定义 debug/log 行为。
- ADB 操作支持显式 serial，并在多设备时拒绝静默选择第一台设备。

## Capabilities

### New Capabilities

- `package-development-workflow`: 定义仓库外 Package 的定位、脚手架、构建、部署、运行、调试、日志和
  显式 action 契约。

### Modified Capabilities

- `cli-subcommands`: 增加 `flange package` / `flange app` 资源优先命令组及旧入口兼容关系。
- `hardware-feature-packages`: 允许 ad-hoc 路径加载 package 清单，并明确 vendor fallback 与不可运行
  component 的失败语义。
- `app-registry`: 增加 `flange app create` 的仓库外默认位置和资源优先路由，不改变既有来源优先级。

## 非目标

- 不把 ad-hoc Package/App 自动写入 board 配置或长期 registry。
- 不把 Device Tree、内核驱动等不可执行 component 伪装成可运行对象，也不在 `deploy` 中自动刷写分区；
  此类 Package 必须声明显式 action。
- 不引入新的构建依赖、通用任务编排语言、IDE 工程生成或远程网络部署。
- 不替代 Package/App 自身的测试框架；CLI 只负责调用现有流水线或清单声明的单条 argv action。

## Impact

- 主要影响 `envsetup.sh`、`builder/packages.py`、`builder/app.py`、`builder/app_spec.py`、
  `builder/deploy.py`、`builder/scaffold.py`、`builder/oot_mounts.py` 与 `builder/config/loader.py`。
- 新增一个 Python CLI/编排模块以及对应最小测试；复用现有 Docker、ADB、AppBuilder、DebBuilder，
  不新增第三方依赖。
- 标准 App 模板的 deb 内容从“可能为空”修正为包含实际 install staging 产物，属于 bug fix；旧命令语法
  继续可用。
