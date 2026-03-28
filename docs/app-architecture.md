# flange App 工程架构设计

本文档描述 flange 构建系统支持的用户 App 工程架构，包括 App 分类、工程结构、描述文件、构建打包、集成方式等设计。

---

## 1. App 分类体系

flange 支持四种 App 类型：

```
┌──────────────────────────────────────────────────────────────────┐
│                       flange App 类型                             │
│                                                                  │
│  ┌───────────┐  ┌───────────┐  ┌───────────┐  ┌───────────┐    │
│  │  test      │  │  lib       │  │  exec      │  │  service   │    │
│  │  测试脚本   │  │  链接库    │  │  可执行文件  │  │  服务      │    │
│  ├───────────┤  ├───────────┤  ├───────────┤  ├───────────┤    │
│  │ shell 脚本 │  │ .so / .a  │  │ 手动启动    │  │ 随系统启动  │    │
│  │ 验证/测试  │  │ 被其他 App │  │ 按需运行    │  │ 持续运行   │    │
│  │ 部署到目标 │  │ 依赖       │  │            │  │ systemd    │    │
│  └─────┬─────┘  └─────┬─────┘  └─────┬─────┘  └─────┬─────┘    │
│        │              │              │              │            │
│        ▼              ▼              ▼              ▼            │
│     .deb 包       .deb 包 ×2     .deb 包        .deb 包         │
│                  (lib + dev)                 + systemd unit      │
│                                                                  │
│  安装与否由板级配置的 packages 列表 + 条件标记决定                    │
└──────────────────────────────────────────────────────────────────┘
```

### 1.1 类型定义

| 类型 | 说明 | 产出 | 安装目标 |
|------|------|------|---------|
| `exec` | 可执行文件，需手动启动运行 | 1+ 个 deb 包 | `/usr/bin` 等 |
| `service` | 服务，随系统自动启动，由 systemd 管理 | 1+ 个 deb 包 + systemd unit | `/usr/bin` + `/lib/systemd/system/` |
| `lib` | 链接库，被其他 App 依赖 | libfoo + libfoo-dev 两个 deb 包 | `/usr/lib` + `/usr/include` |
| `test` | 测试脚本，复制到目标文件系统执行 | 1 个 deb 包 | 由 BUILD.bazel 定义路径 |

### 1.2 一个 App 的组成

```
一个 App 可能包含：
├── 可执行文件        ← 编译产出的二进制程序
├── 资源文件          ← 图片、字体、模型、音频等运行时资源
├── 配置文件          ← 默认配置，安装到 /etc/ 下
├── 用户数据目录声明   ← 运行时产生的数据（如 /var/lib/my-app/）
├── 依赖动态链接库     ← App 自编译的 .so（非系统 apt 包提供的）
└── App 描述文件      ← app.yaml，App 身份与能力的元数据
```

---

## 2. App 描述文件：app.yaml

### 2.1 设计原则

app.yaml 是 App 的"身份证"，只描述 **App 是什么**，不描述 **App 怎么构建**。

```
app.yaml（身份证）                   BUILD.bazel（施工图）
───────────────────                 ───────────────────────────
名称、版本、描述                     编译规则
类型                                源文件、编译选项、构建依赖
维护者                              deb 打包规则
支持架构                              ├── 包名、包拆分
App 能力/特性声明                      ├── 安装路径映射
                                      ├── systemd unit 文件
                                      ├── conffiles 声明
                                      └── 运行期 apt 依赖
```

deb 包产出声明、文件系统路径映射、服务配置等**构建相关内容全部在 BUILD.bazel 中定义**。app.yaml 的信息会被 Bazel 的 `flange_deb` 规则读取，用于生成 deb 的 control 文件。

### 2.2 格式定义

采用 YAML 格式（比 XML 更友好，比 TOML 更适合嵌套结构），参考 iOS Info.plist 的设计思路：

```yaml
# app.yaml — App 描述文件

app:
  name: my-display-app           # 包名（唯一标识）
  version: 1.0.0                 # 语义化版本号
  description: 智能显示终端主应用   # 简短描述
  type: service                  # exec | service | lib | test
  arch:                          # 支持的目标架构
    - aarch64
    - armhf

maintainer:
  name: Zhang San
  email: zhangsan@example.com

# 可选：App 能力声明（供上层工具或文档使用）
capabilities:
  - display
  - touchscreen
  - network
```

### 2.3 字段说明

| 字段 | 必填 | 说明 |
|------|------|------|
| `app.name` | 是 | App 包名，全局唯一，用于 deb 包命名和依赖引用 |
| `app.version` | 是 | 语义化版本号（SemVer），用于 deb 版本 |
| `app.description` | 是 | 简短描述，写入 deb control 的 Description 字段 |
| `app.type` | 是 | App 类型：`exec` / `service` / `lib` / `test` |
| `app.arch` | 是 | 支持的目标架构列表 |
| `maintainer.name` | 是 | 维护者姓名 |
| `maintainer.email` | 是 | 维护者邮箱 |
| `capabilities` | 否 | App 能力标签，供配置系统和文档使用 |

---

## 3. BUILD.bazel 构建与打包

### 3.1 自定义 Bazel 规则

flange 提供以下自定义 Bazel 规则用于 App 构建和打包：

```python
# build/defs.bzl 导出的规则

flange_deb()          # deb 打包（核心规则）
flange_cmake()        # CMake 项目包装
flange_meson()        # Meson 项目包装
flange_make()         # Makefile 项目包装
flange_swift()        # Swift Package Manager 项目包装
```

### 3.2 exec 类型示例

```python
load("//build:defs.bzl", "flange_deb")

cc_binary(
    name = "my-tool",
    srcs = glob(["src/**/*.c"]),
    deps = ["//apps/libfoo"],
)

flange_deb(
    name = "my-tool-deb",
    app_yaml = "app.yaml",
    binary = ":my-tool",
    conf = ["conf/tool.yaml"],
    res = glob(["res/**"]),
    paths = {
        "bin":  "/usr/bin",
        "conf": "/etc/my-tool",
        "res":  "/usr/share/my-tool",
    },
    data_dirs = ["/var/lib/my-tool"],   # 运行时用户数据目录
    runtime_deps = ["libc6", "libssl3"],
)
```

### 3.3 service 类型示例

```python
load("//build:defs.bzl", "flange_deb")

cc_binary(
    name = "my-daemon",
    srcs = glob(["src/**/*.c"]),
    deps = ["//apps/libmqtt"],
)

flange_deb(
    name = "my-daemon-deb",
    app_yaml = "app.yaml",
    binary = ":my-daemon",
    conf = ["conf/daemon.yaml"],
    systemd = {
        "unit": "systemd/my-daemon.service",
        "auto_start": True,
    },
    paths = {
        "bin":  "/usr/bin",
        "conf": "/etc/my-daemon",
    },
    data_dirs = [
        "/var/lib/my-daemon",
        "/var/log/my-daemon",
    ],
    runtime_deps = ["libc6", "libmosquitto1"],
)
```

### 3.4 lib 类型示例（双包产出）

```python
load("//build:defs.bzl", "flange_deb")

cc_library(
    name = "foo",
    srcs = glob(["src/**/*.c"]),
    hdrs = glob(["include/**/*.h"]),
)

# 运行时包: libfoo
flange_deb(
    name = "libfoo-deb",
    app_yaml = "app.yaml",
    shared_lib = ":foo",
    paths = {"lib": "/usr/lib"},
    runtime_deps = ["libc6"],
)

# 开发包: libfoo-dev
flange_deb(
    name = "libfoo-dev-deb",
    app_yaml = "app.yaml",
    package_suffix = "-dev",
    headers = glob(["include/**/*.h"]),
    static_lib = ":foo",
    paths = {
        "include": "/usr/include/foo",
        "lib":     "/usr/lib",
    },
    runtime_deps = ["libfoo"],
)
```

### 3.5 test 类型示例

```python
load("//build:defs.bzl", "flange_deb")

flange_deb(
    name = "hw-tests-deb",
    app_yaml = "app.yaml",
    scripts = glob(["scripts/**/*.sh"]),
    paths = {
        "scripts": "/opt/tests/hw",
    },
)
```

### 3.6 多构建系统支持

App 源码不限于 Bazel 原生规则编译。flange 通过包装规则支持多种构建系统：

```
┌─────────────────────────────────────────────────────────────┐
│                   App 构建系统支持                            │
│                                                             │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐            │
│  │ Bazel 原生  │  │  CMake     │  │  Meson     │            │
│  │ cc_binary  │  │ flange_    │  │ flange_    │            │
│  │ cc_library │  │ cmake()   │  │ meson()   │            │
│  └──────┬─────┘  └──────┬─────┘  └──────┬─────┘            │
│         │               │               │                   │
│  ┌────────────┐  ┌────────────┐                             │
│  │  Makefile   │  │  Swift     │                             │
│  │ flange_    │  │ flange_    │                             │
│  │ make()    │  │ swift()   │                             │
│  └──────┬─────┘  └──────┬─────┘                             │
│         │               │                                   │
│         └───────┬───────┘                                   │
│                 ▼                                           │
│          编译产物（binary / .so / .a）                        │
│                 │                                           │
│                 ▼                                           │
│          flange_deb()  → .deb 包                            │
└─────────────────────────────────────────────────────────────┘
```

#### CMake 项目

```python
load("//build:defs.bzl", "flange_cmake", "flange_deb")

flange_cmake(
    name = "my-cmake-app",
    src = ".",
    cmake_options = [
        "-DCMAKE_BUILD_TYPE=Release",
        "-DENABLE_TESTS=OFF",
    ],
    out_binaries = ["my-cmake-app"],
    deps = ["//apps/libfoo"],
)

flange_deb(
    name = "my-cmake-app-deb",
    app_yaml = "app.yaml",
    binary = ":my-cmake-app",
    paths = {"bin": "/usr/bin"},
)
```

#### Meson 项目

```python
load("//build:defs.bzl", "flange_meson", "flange_deb")

flange_meson(
    name = "my-meson-app",
    src = ".",
    meson_options = [
        "-Dfeature_x=enabled",
    ],
    out_binaries = ["my-meson-app"],
)

flange_deb(
    name = "my-meson-app-deb",
    app_yaml = "app.yaml",
    binary = ":my-meson-app",
    paths = {"bin": "/usr/bin"},
)
```

#### Makefile 项目

```python
load("//build:defs.bzl", "flange_make", "flange_deb")

flange_make(
    name = "my-legacy-app",
    src = ".",
    make_targets = ["all"],
    make_vars = {
        "PREFIX": "/usr",
        "CROSS_COMPILE": "aarch64-linux-gnu-",
    },
    out_binaries = ["my-legacy-app"],
)

flange_deb(
    name = "my-legacy-app-deb",
    app_yaml = "app.yaml",
    binary = ":my-legacy-app",
    paths = {"bin": "/usr/bin"},
)
```

#### Swift Package Manager 项目

```python
load("//build:defs.bzl", "flange_swift", "flange_deb")

flange_swift(
    name = "my-swift-app",
    src = ".",
    swift_build_args = [
        "--configuration", "release",
    ],
    out_binaries = ["my-swift-app"],
)

flange_deb(
    name = "my-swift-app-deb",
    app_yaml = "app.yaml",
    binary = ":my-swift-app",
    paths = {"bin": "/usr/bin"},
)
```

---

## 4. App 来源与集成

### 4.1 两种来源

```
┌──────────────────────────────────────────────────────────┐
│                    App 来源                                │
│                                                          │
│   仓库内 App（内置）              仓库外 App（外部）        │
│   apps/<name>/                  独立 git 仓库             │
│   直接在 flange 仓库开发          通过板级配置声明引入       │
│                                                          │
│         └──────────┬─────────────────┘                   │
│                    ▼                                     │
│            统一的 App 工程结构                              │
│            统一的 flange_deb 打包                          │
│            统一安装到 rootfs                               │
└──────────────────────────────────────────────────────────┘
```

### 4.2 仓库内 App

直接在 `apps/` 目录下开发：

```
flange/
└── apps/
    ├── my-display-app/
    │   ├── app.yaml
    │   ├── BUILD.bazel
    │   ├── src/
    │   └── ...
    └── libfoo/
        ├── app.yaml
        ├── BUILD.bazel
        ├── include/
        └── src/
```

在板级配置中通过包名引用：

```python
"+packages": ["my-display-app", "libfoo"],
```

### 4.3 仓库外 App（外部集成）

在板级配置中声明 git 源，由 Bazel 自动拉取：

```python
# board/rk3588-evb/board.bzl
BOARD = {
    "rootfs": {
        "+packages": [
            "my-display-app",       # 仓库内 App
            "zigbee-daemon",        # 仓库外 App（下方声明源）
        ],
    },

    "external_apps": {
        "zigbee-daemon": {
            "git": "ssh://git@gitlab.example.com/apps/zigbee.git",
            "tag": "v2.1.0",
        },
        "ota-agent": {
            "git": "ssh://git@gitlab.example.com/apps/ota.git",
            "branch": "release/3.0",
        },
    },
}
```

### 4.4 外部 App 集成流程

```
flange build 触发
    │
    ▼
配置解析引擎读取 board.bzl
    │
    ├── 识别 packages 列表中的包名
    ├── 在 apps/ 目录查找仓库内 App
    ├── 未找到 → 查找 external_apps 声明
    │
    ▼
生成 Bazel git_repository 规则
    │
    ▼
Bazel 拉取外部 App 源码到 workspace
    │
    ▼
按外部 App 自身的 BUILD.bazel 编译打包
    │
    ▼
产出 .deb → 安装到 rootfs
```

外部 App 必须遵循与仓库内 App 相同的工程结构（包含 `app.yaml` 和 `BUILD.bazel`）。

---

## 5. 服务管理

### 5.1 systemd 集成

type 为 `service` 的 App 通过 systemd 管理生命周期。服务的 systemd unit 文件在 App 工程内维护，通过 `flange_deb` 的 `systemd` 参数声明。

### 5.2 systemd unit 模板

```ini
# systemd/my-daemon.service
[Unit]
Description=My Daemon Service
After=network.target

[Service]
Type=simple
ExecStart=/usr/bin/my-daemon --config /etc/my-daemon/config.yaml
Restart=on-failure
RestartSec=5
User=root

[Install]
WantedBy=multi-user.target
```

### 5.3 flange_deb 的 systemd 参数

```python
flange_deb(
    ...
    systemd = {
        "unit": "systemd/my-daemon.service",   # unit 文件路径
        "auto_start": True,                     # deb postinst 中 systemctl enable
    },
)
```

- `auto_start: True`：deb 安装时自动执行 `systemctl enable`，系统启动时自动拉起
- `auto_start: False`：仅安装 unit 文件，需要手动 enable

---

## 6. deb 打包机制

### 6.1 flange_deb 规则

`flange_deb` 是 App 打包的核心 Bazel 规则，职责：

```
flange_deb 规则
    │
    ├── 读取 app.yaml → 提取 name/version/description/maintainer
    ├── 生成 debian/control 文件
    ├── 收集编译产物 (binary/shared_lib/headers/scripts)
    ├── 按 paths 映射组织文件布局
    ├── 处理 systemd unit（可选）
    ├── 处理 conffiles 声明（可选）
    ├── 生成 postinst/prerm 脚本（systemd enable/disable 等）
    │
    ▼
产出: <name>_<version>_<arch>.deb
```

### 6.2 flange_deb 完整参数

| 参数 | 类型 | 说明 |
|------|------|------|
| `name` | string | Bazel target 名称 |
| `app_yaml` | label | app.yaml 路径 |
| `package_suffix` | string | 包名后缀（如 `-dev`、`-dbg`） |
| `binary` | label | 可执行文件 target |
| `shared_lib` | label | 动态库 target |
| `static_lib` | label | 静态库 target |
| `headers` | label_list | 头文件列表 |
| `scripts` | label_list | 脚本文件列表 |
| `conf` | label_list | 配置文件列表 |
| `res` | label_list | 资源文件列表 |
| `systemd` | dict | systemd 配置 `{unit, auto_start}` |
| `paths` | dict | 安装路径映射 `{类别: 目标路径}` |
| `data_dirs` | string_list | 运行时数据目录（deb postinst 创建） |
| `runtime_deps` | string_list | 运行期 apt 依赖 |
| `conffiles` | string_list | 需要保护的配置文件路径（dpkg 升级时不覆盖） |

### 6.3 多包产出

一个 App 可以产出多个 deb 包，通过定义多个 `flange_deb` target 实现：

```python
# 主包
flange_deb(name = "my-app-deb", ...)

# 调试包
flange_deb(name = "my-app-dbg-deb", package_suffix = "-dbg", ...)

# lib 运行时包
flange_deb(name = "libfoo-deb", ...)

# lib 开发包
flange_deb(name = "libfoo-dev-deb", package_suffix = "-dev", ...)
```

### 6.4 deb 安装到 rootfs 的流程

```
rootfs 构建阶段（Docker 容器内，Bazel 驱动）
    │
    ├── 收集所有需要安装的 deb 包
    │   ├── 仓库内 App 的 deb 产物
    │   ├── 外部 App 的 deb 产物
    │   └── 板级配置 packages 列表过滤
    │
    ├── 创建 rootfs chroot 环境
    │   └── 基于 ubuntu-base
    │
    ├── apt install 系统级依赖包
    │
    ├── dpkg -i *.deb 安装自定义 App
    │   ├── 文件安装到声明的路径
    │   ├── postinst 执行（创建数据目录、systemctl enable 等）
    │   └── conffiles 注册
    │
    └── 产出 rootfs 镜像
```

---

## 7. App 工程目录模板

### 7.1 exec 类型

```
my-tool/
├── app.yaml                # App 描述文件
├── BUILD.bazel             # 构建 + 打包规则
├── src/                    # 源码
│   └── main.c
├── conf/                   # 默认配置文件（可选）
│   └── config.yaml
└── res/                    # 资源文件（可选）
    └── ...
```

### 7.2 service 类型

```
my-daemon/
├── app.yaml                # App 描述文件
├── BUILD.bazel             # 构建 + 打包规则
├── src/                    # 源码
│   └── main.c
├── conf/                   # 默认配置文件
│   └── daemon.yaml
├── res/                    # 资源文件（可选）
│   └── ...
└── systemd/                # systemd unit 文件
    └── my-daemon.service
```

### 7.3 lib 类型

```
libfoo/
├── app.yaml                # App 描述文件
├── BUILD.bazel             # 构建 + 双包打包规则
├── include/                # 公开头文件
│   └── foo.h
├── src/                    # 源码
│   └── foo.c
└── conf/                   # 库配置（可选）
    └── ...
```

### 7.4 test 类型

```
hw-tests/
├── app.yaml                # App 描述文件
├── BUILD.bazel             # 打包规则
└── scripts/                # 测试脚本
    ├── test_wifi.sh
    ├── test_gpio.sh
    └── test_camera.sh
```

---

## 8. CLI 脚手架命令

### 8.1 flange create app

`flange create app` 命令自动生成 App 工程脚手架：

```bash
flange create app <name> --type=<type> [--path=<path>]
```

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `<name>` | App 名称 | 必填 |
| `--type` | App 类型：`exec` / `service` / `lib` / `test` | `exec` |
| `--path` | 创建位置 | `apps/<name>` |
| `--build-system` | 构建系统：`bazel` / `cmake` / `meson` / `make` / `swift` | `bazel` |

### 8.2 使用示例

```bash
# 创建一个 service 类型的 App
$ flange create app my-daemon --type=service
  创建: apps/my-daemon/
  ├── app.yaml
  ├── BUILD.bazel
  ├── src/main.c
  ├── conf/config.yaml
  └── systemd/my-daemon.service
  ✓ App 脚手架已生成

# 创建一个 CMake 项目的 App
$ flange create app my-cmake-app --type=exec --build-system=cmake
  创建: apps/my-cmake-app/
  ├── app.yaml
  ├── BUILD.bazel          ← 包含 flange_cmake() 规则
  ├── CMakeLists.txt       ← CMake 项目模板
  └── src/main.c
  ✓ App 脚手架已生成

# 创建一个 Swift 项目的 App
$ flange create app my-swift-app --type=exec --build-system=swift
  创建: apps/my-swift-app/
  ├── app.yaml
  ├── BUILD.bazel          ← 包含 flange_swift() 规则
  ├── Package.swift        ← SPM 项目模板
  └── Sources/
      └── main.swift
  ✓ App 脚手架已生成

# 创建一个链接库
$ flange create app libbar --type=lib
  创建: apps/libbar/
  ├── app.yaml
  ├── BUILD.bazel          ← 包含双包 flange_deb() 规则
  ├── include/bar.h
  └── src/bar.c
  ✓ App 脚手架已生成

# 创建测试脚本集
$ flange create app board-tests --type=test
  创建: apps/board-tests/
  ├── app.yaml
  ├── BUILD.bazel
  └── scripts/
      └── test_example.sh
  ✓ App 脚手架已生成
```

### 8.3 其他 App 相关命令

| 命令 | 说明 |
|------|------|
| `flange build apps/<name>` | 构建指定 App（编译 + 打 deb 包） |
| `flange build apps` | 构建当前配置下所有需要的 App |
| `flange list apps` | 列出所有已注册的 App（仓库内 + 外部） |

---

## 9. 完整数据流

```
┌─────────────────────────────────────────────────────────────────┐
│                     App 完整生命周期                              │
│                                                                 │
│  开发者                                                         │
│  ┌─────────────────┐                                           │
│  │ flange create   │                                           │
│  │ app my-app      │                                           │
│  │ --type=service  │                                           │
│  └────────┬────────┘                                           │
│           ▼                                                     │
│  ┌─────────────────────────────────┐                           │
│  │ apps/my-app/                    │                           │
│  │ ├── app.yaml      (身份证)       │                           │
│  │ ├── BUILD.bazel   (施工图)       │                           │
│  │ ├── src/          (源码)         │                           │
│  │ ├── conf/         (配置)         │                           │
│  │ └── systemd/      (服务)         │                           │
│  └────────┬────────────────────────┘                           │
│           │                                                     │
│           ▼  板级配置引用                                        │
│  ┌─────────────────────────────────┐                           │
│  │ board/rk3588-evb/board.bzl      │                           │
│  │ "+packages": ["my-app"]         │                           │
│  └────────┬────────────────────────┘                           │
│           │                                                     │
│           ▼  flange build（Docker 容器内）                       │
│  ┌─────────────────────────────────┐                           │
│  │ Bazel                           │                           │
│  │ ├── 编译 src/ → binary          │                           │
│  │ ├── 读取 app.yaml → control     │                           │
│  │ ├── 按 paths 组织文件布局         │                           │
│  │ ├── 打包 → my-app_1.0_arm64.deb │                           │
│  │ └── 安装到 rootfs chroot         │                           │
│  │     ├── /usr/bin/my-app         │                           │
│  │     ├── /etc/my-app/config.yaml │                           │
│  │     └── systemctl enable my-app │                           │
│  └────────┬────────────────────────┘                           │
│           │                                                     │
│           ▼  flange flash                                       │
│  ┌─────────────────────────────────┐                           │
│  │ rootfs 刷写到目标设备             │                           │
│  │ → 设备启动                       │                           │
│  │ → systemd 自动拉起 my-app       │                           │
│  └─────────────────────────────────┘                           │
└─────────────────────────────────────────────────────────────────┘
```

---

## 10. 目录结构（更新）

在 build-system-design.md 基础上，新增 App 相关目录：

```
flange/
├── ...                     # （已有结构省略）
│
├── apps/                   # 用户 App（仓库内）
│   ├── my-display-app/     # service 类型示例
│   │   ├── app.yaml
│   │   ├── BUILD.bazel
│   │   ├── src/
│   │   ├── conf/
│   │   ├── res/
│   │   └── systemd/
│   ├── libfoo/             # lib 类型示例
│   │   ├── app.yaml
│   │   ├── BUILD.bazel
│   │   ├── include/
│   │   └── src/
│   ├── my-tool/            # exec 类型示例
│   │   ├── app.yaml
│   │   ├── BUILD.bazel
│   │   └── src/
│   └── hw-tests/           # test 类型示例
│       ├── app.yaml
│       ├── BUILD.bazel
│       └── scripts/
│
├── build/
│   ├── defs.bzl            # 导出 flange_deb / flange_cmake / ...
│   ├── deb.bzl             # deb 打包规则实现
│   ├── cmake.bzl           # CMake 包装规则
│   ├── meson.bzl           # Meson 包装规则
│   ├── make.bzl            # Makefile 包装规则
│   ├── swift.bzl           # Swift PM 包装规则
│   └── templates/          # App 脚手架模板
│       ├── exec/
│       ├── service/
│       ├── lib/
│       └── test/
│
└── ...
```
