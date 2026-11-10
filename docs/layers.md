# 多层工作区

Layer（扩展层）提供只读构建输入；Workspace（工作区）拥有目标选择、可变源码、缓存与产物。
flange 基础仓库隐式为最低层 `flange`。层数量不限，依赖构成有向无环图，工作区明确指定线性组合顺序。

```toml
# 产品工作区 flange.toml
schema_version = 2
tool_root = "../flange"
layers = ["../layer-bsp", "../layer-common", "."]
```

```toml
# 产品层 layer.toml
schema_version = 1
api_version = 1
name = "product"
requires = ["flange", "bsp", "common"]
[providers.platform]
myplatform = "strategies/platform/provider.py"
```

同一目录可以同时提供两份清单。`layers` 路径相对工作区，`requires` 引用层名称；每个依赖必须已位于下层。
重复名称、重复真实路径、缺失依赖、依赖循环和顺序错误都会报错。flange 不自动排序或同步 Git 仓库。
未声明 `layers` 的 schema 1/2 工作区只有基础层。并行保留不同组合需要不同工作区。

## 内容与优先级

层内内容继续放在 `components/`，Python 策略放在独立 `strategies/` 子目录。
基础仓库的现有内容无需移动。

| 资源 | 规则 |
| --- | --- |
| 配置 | 发行版基线 → platform → SoC → board → 目标直接启用的 Package；每阶段内部低层到高层 |
| Jsonnet 字段 | 原生对象组合；普通字段替换，`+:` 追加或继承，无 Python 深度合并 |
| App / Package | 同名目录选择最高层的完整定义；缺文件报错，不向下层补齐 |
| Python 策略 | 按种类及名称选择最高层完整实现 |
| 补丁 | platform → board；各作用域低层到高层，同相对文件名原位替换，新增补丁追加 |
| rootfs overlay（文件覆盖） | 发行版基线 → platform → board；各作用域按层顺序覆盖，支持文件、目录、符号链接类型替换 |

工作区 `[apps]`、显式路径、调用目录及 `app_dirs` 保持已有优先级。Package 只展开直接启用项的配置，
不递归加载新增 Package 的配置。上层同名 board 可通过 `products+: [...]` 追加产品，
`lunch` 与构建共用组合后的板卡身份，目标格式继续是 `<board>-<product>-<variant>`。

## 路径与 import

普通相对 import 只访问所属层的 `components/` 树。跨层复用显式引用启用层：

```jsonnet
// 产品板卡配置：复用基础公共函数，引用本层资源。
local lib = import 'layer://flange/components/config/lib.libsonnet';
local layer = import 'flange/layer.libsonnet';
{
  sources+: { firmware: {local_path: layer.path('components/firmware')} },
}
```

`layer.path()` 返回带层身份的资源引用，求值后转为该层绝对路径；继承字段不会重新解释成最高层目录。
基础层原有相对路径语义保持兼容。import 拒绝绝对路径、`..`、未启用层及经符号链接越出配置树的路径。
overlay 内符号链接作为目标文件系统节点复制，不跟随链接写入目标树之外。

## 策略 API 1

入口是层内 `.py` 文件，可用 `from .helper import ...` 引用同目录辅助模块。
加载器使用独立命名空间，不修改 `PYTHONPATH` 遮蔽 flange，禁止辅助模块越出策略目录，
忽略已有 pyc；同一进程切换工作区或修改 helper 后不会沿用另一份实现。
Python 策略属于用户信任的构建代码，不是沙箱插件。

| providers 种类 | 工厂与契约 |
| --- | --- |
| `platform` | `ARTIFACT_NAMES`、`create_builder(component, docker, source)`；可提供 `output_contract(component, config, context)`、`extra_inputs(...)`、`validate_config(config)` 等平台校验 |
| `distro` | `create_distro()` 返回 `DistroBackend`；可声明 `BUILD_ENVIRONMENT` |
| `environment` | `create_environment(config, context)` 返回 `BuildEnvironmentSpec` |
| `toolchain` | `create_toolchain(config, context)` 返回 `Toolchain`；可提供 `create_dependencies(config, context, runner)` |
| `packaging` | `create_backend()` 返回 `PackageBackend` |
| `flash_plan` | `create_plan()` 返回构建期 `FlashPlan` |
| `flash` | `create_strategy()` 返回宿主执行期 `FlashStrategy` |

平台可通过 `extra_inputs` 返回具名 `InputSpec`；产物契约返回目标目录内的 `ArtifactSpec`。
固定组件图及组件依赖继续由引擎管理，不允许策略任意注入任务图。
每种策略建议单独目录；选中入口目录中的 Python 辅助文件作为配方输入，避免将不相关策略放在同目录。

专有配置放入 `extensions['种类:名称']`。对应策略必须声明 `EXTENSION_SCHEMA`，类型为
`builder.config.schema.Object`，默认拒绝未知字段；不会放开整个配置的未知字段检查。

## 发行版、环境与 SDK

目标配置可选择 `distro`、`build_environment`、`userland_toolchain`。
默认 Ubuntu 继续使用 `components/rootfs/config.jsonnet` 和内建 Docker 配方。
其他发行版使用 `components/distro/<name>/config.jsonnet`，不继承 Ubuntu 软件包；
其 overlay 目录为该发行版下的 `overlay/` 和 `recovery-overlay/`。
先从目标配置确定发行版，再加载基线。normal rootfs 与 recovery 使用同一发行版、各自包集合。

`DistroBackend` 提供基础计划/构建、App 安装、额外包安装、系统定制和包清单导出。
`AptDistro` 可供 Debian 系发行版复用；共享 rootfs 编排仍负责硬件内容、overlay、存储和成像。
rootfs APT 缓存按发行版、架构、基础归档与软件源身份隔离。

`BuildEnvironmentSpec` 声明完整镜像，或镜像名及层内 Dockerfile/build_context；可以声明
`required_tools=((绝对工具路径, 版本文本), ...)`。每个目标使用单个完整容器环境。
独立 App、Package、系统构建与 `flange docker build` 使用同一环境选择。
容器内执行要求环境名称及实际镜像身份已标识且匹配；请从宿主 flange 入口启动，勿手动进入未标识容器构建。

内核/bootloader 的 gcc10 与 App 的用户态工具链可以并存。外部 `Toolchain` 要求
`profile`、`sdk_identity` 和绝对 `target_sysroot`：

- `sdk_source='environment'`：SDK 随镜像提供，实际镜像摘要标识 SDK 内容。
- `sdk_source='directory'`：独立 SDK 目录，自动挂载并将内容纳入指纹和 ABI 身份。

SDK 不依赖最终 rootfs。每个 App 将 SDK 和已验证的上游 App 安装树组合到自身构建目录；
`FLANGE_SYSROOT` 仍指上游安装前缀，`FLANGE_TARGET_SYSROOT` 指组合后的完整目标 SDK。
CMake 使用 toolchain file 的 `CMAKE_SYSROOT` 与 ONLY 查找规则；Meson 使用 cross-file；
Make/custom 通过编译参数与 `PKG_CONFIG_SYSROOT_DIR`、`PKG_CONFIG_LIBDIR` 使用相同目标路径。
SDK 依赖须预置，或由策略明确提供安装适配器；默认不往其他发行版隐式安装 Ubuntu 开发包。

## 缓存与诊断

任务输入包含最终消费配置、选中资源、补丁/overlay 顺序、策略及辅助代码、构建环境和 SDK。
不把整个 Layer 的 Git HEAD 加入所有任务。被覆盖补丁和 overlay 文件、无关板卡文件不会使目标重建。
环境配方目录视为完整构建上下文，应保持精简。

App 报告 schema 3 记录发行版及用户态 ABI 身份，独立 SDK 包含内容摘要，镜像 SDK 包含镜像摘要。
rootfs 安装和 `--no-build` 检查身份；缺少身份的旧报告必须重建。
刷写清单记录提供者 URI 与 API 版本，当前层集合选中另一提供者时拒绝执行。

```sh
flange layer list
flange layer check
flange layer show product
flange layer show components/board/myboard/config.jsonnet
flange plan kernel
flange why rootfs
```

`plan/why` 展示层顺序、配置组合链、启用资源的覆盖关系、最终补丁顺序；JSON 输出包含结构化来源。
此版本不追踪任意 Jsonnet 表达式的精确字段来源，不下载、同步或锁定层仓库版本。

完整示例与执行记录见 [Debian 多层验证](examples/layers/README.md)。
