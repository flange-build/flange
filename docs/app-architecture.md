# flange App 工程架构设计

本文档描述 flange 构建系统支持的用户 App 工程架构，包括 App 分类、工程结构、描述文件、构建打包、集成方式等设计。App 打包系统基于 Python 统一实现，核心模块位于 `builder/` 目录。

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
| `test` | 测试脚本，复制到目标文件系统执行 | 1 个 deb 包 | `/usr/lib/<name>/` |

### 1.2 一个 App 的组成

```
一个 App 可能包含：
├── 可执行文件        ← 编译产出的二进制程序
├── 资源文件          ← 图片、字体、模型、音频等运行时资源
├── 配置文件          ← 默认配置，安装到 /etc/<name>/ 下
├── 用户数据目录声明   ← 运行时产生的数据（如 /var/lib/my-app/）
├── 依赖动态链接库     ← App 自编译的 .so（非系统 apt 包提供的）
└── App 描述文件      ← app.yaml，App 身份与构建的唯一配置源
```

---

## 2. App 描述文件：app.yaml

### 2.1 设计原则

app.yaml 是 App 的唯一配置文件，同时描述 **App 是什么**（身份元数据）和 **App 怎么构建**（构建配置）。Python 构建引擎从 app.yaml 中读取所有信息，无需额外的构建规则文件。

### 2.2 完整 Schema

```yaml
# app.yaml — App 描述文件（唯一配置来源）

app:
  name: my-display-app           # 包名（唯一标识，用于 deb 包命名和依赖引用）
  version: 1.0.0                 # 语义化版本号（SemVer）
  description: 智能显示终端主应用   # 简短描述，写入 deb control
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

# 可选：构建配置
build:
  system: cmake                  # none | cmake | meson | make | swift | custom
  apt_packages:                  # 当前构建容器内安装的编译依赖
    - libssl-dev:{arch}          # {arch} 展开为当前目标架构
  options:                       # 传递给构建系统的选项（cmake -D 变量等）
    CMAKE_BUILD_TYPE: Release
    ENABLE_TESTS: "OFF"
  outputs:                       # 构建产物相对路径列表
    - build/my-display-app
  deps:                          # App 间构建依赖（其他 App 名称）
    - libfoo
  # custom 构建专用：命令列表（system=custom 时使用）
  commands:
    - ["make", "ARCH=arm64", "-j4"]
    - ["make", "install", "DESTDIR=dist/"]

# 可选：安装路径覆盖（覆盖约定式默认映射）
install:
  conf/special.conf: /etc/special.conf   # 源路径: 目标路径
  scripts/helper: /usr/sbin/helper

# 可选：systemd 服务配置（仅 service 类型）
systemd:
  unit: systemd/my-daemon.service        # unit 文件相对路径
  auto_start: true                       # 是否随系统自动启动

# 可选：运行期 apt 依赖
depends:
  - libc6
  - libssl3

# 可选：dpkg conffiles 声明（升级时 dpkg 不覆盖这些配置文件）
conffiles:
  - /etc/my-display-app/config.yaml

# 可选：运行时数据目录声明（deb postinst 中自动创建）
data_dirs:
  - /var/lib/my-display-app
  - /var/log/my-display-app

# 可选：链接库配置（仅 lib 类型）
lib:
  headers_dir: include/          # 头文件目录（相对于 App 目录）
  dev_suffix: -dev               # dev 包后缀，默认 -dev
```

### 2.3 字段说明

| 字段 | 必填 | 说明 |
|------|------|------|
| `app.name` | 是 | App 包名，全局唯一，用于 deb 包命名和依赖引用 |
| `app.version` | 是 | 语义化版本号（SemVer），用于 deb 版本 |
| `app.description` | 是 | 简短描述，写入 deb control 的 Description 字段 |
| `app.type` | 是 | App 类型：`exec` / `service` / `lib` / `test` |
| `app.arch` | 是 | 支持的目标架构列表（至少一个） |
| `maintainer.name` | 是 | 维护者姓名 |
| `maintainer.email` | 是 | 维护者邮箱 |
| `capabilities` | 否 | App 能力标签，供配置系统和文档使用 |
| `build.system` | 否 | 构建系统，默认 `none`（预编译包） |
| `build.apt_packages` | 否 | 构建容器内安装的 APT 编译依赖；支持 `:{arch}` 架构占位符 |
| `build.options` | 否 | 传递给构建系统的选项字典 |
| `build.outputs` | 否 | 构建产物路径列表（相对于 App 目录） |
| `build.deps` | 否 | App 间构建依赖列表 |
| `build.commands` | 否 | custom 构建专用命令列表 |
| `install` | 否 | 安装路径覆盖映射，源路径 → 目标路径 |
| `systemd.unit` | 否 | service unit 文件相对路径 |
| `systemd.auto_start` | 否 | 是否随系统自动启动，默认 `false` |
| `depends` | 否 | 运行期 apt 依赖列表 |
| `conffiles` | 否 | dpkg 保护的配置文件路径列表 |
| `data_dirs` | 否 | 运行时数据目录声明列表 |
| `lib.headers_dir` | 否 | 头文件目录，默认 `include/` |
| `lib.dev_suffix` | 否 | dev 包后缀，默认 `-dev` |

---

## 3. app.yaml 构建配置

### 3.1 构建系统选项

`build.system` 支持以下取值：

| 取值 | 说明 | 适用场景 |
|------|------|---------|
| `none` | 预编译包，无编译步骤 | bin/ 中直接放置编译好的二进制 |
| `cmake` | CMake 两阶段（configure + build） | C/C++ CMake 项目 |
| `meson` | Meson + Ninja 两阶段（setup + build） | C/C++ Meson 项目 |
| `make` | Make 单阶段 | Makefile 项目 |
| `swift` | Swift Package Manager 交叉编译 | Swift 项目 |
| `custom` | 完全自定义命令（由 `build.commands` 提供） | 特殊构建需求 |

### 3.2 构建期、App 间与运行期依赖

`build.apt_packages` 只在当前 `flange build` 容器内、编译命令执行前通过 APT 安装；`build.deps` 表示 App 间的
构建顺序与 sysroot 依赖；顶层 `depends` 会写入 `.deb` control，供目标设备安装运行时库。

构建期包支持 `:{arch}`，例如 `libasound2-dev:{arch}` 在 armhf 目标展开为 `libasound2-dev:armhf`。下载的 `.deb`
复用 `.build/cache/apt`，App 专属依赖不应固化进 `docker/Dockerfile`。

### 3.3 约定式路径映射

AppBuilder 根据 App 目录下的子目录名，按约定自动映射到目标文件系统路径：

| 源子目录 | 目标路径 | 文件权限 |
|---------|---------|---------|
| `bin/` | `/usr/bin/` | `0755` |
| `lib/` | `/usr/lib/` | `0644` |
| `include/` | `/usr/include/<name>/` | `0644`（仅 lib 类型） |
| `conf/` | `/etc/<name>/` | `0644` |
| `scripts/` | `/usr/lib/<name>/` | `0755` |
| `systemd/` | `/lib/systemd/system/` | `0644` |
| `udev/` | `/lib/udev/rules.d/` | `0644` |
| `res/` | `/usr/share/<name>/` | `0644` |

如需覆盖约定映射，在 `install:` 段声明具体路径（见 [2.2 节](#22-完整-schema) adbd 示例）。

### 3.4 预编译二进制架构选择

当 `build.system = none` 时，AppBuilder 根据目标架构自动选择 `bin/` 目录中的正确二进制：

- `aarch64` 目标：优先匹配 `-arm64`、`-aarch64` 后缀
- `armhf` 目标：优先匹配 `-armhf`、`-arm32` 后缀
- 不匹配目标架构的文件自动排除

### 3.5 类型示例

#### exec 类型（CMake）

```yaml
app:
  name: my-tool
  version: 1.0.0
  description: 命令行工具
  type: exec
  arch: [aarch64]

maintainer:
  name: Dev
  email: dev@example.com

build:
  system: cmake
  outputs:
    - build/my-tool

depends:
  - libc6
  - libssl3
```

#### service 类型

```yaml
app:
  name: my-daemon
  version: 1.0.0
  description: 后台守护服务
  type: service
  arch: [aarch64]

maintainer:
  name: Dev
  email: dev@example.com

build:
  system: cmake
  outputs:
    - build/my-daemon

systemd:
  unit: systemd/my-daemon.service
  auto_start: true

depends:
  - libc6

conffiles:
  - /etc/my-daemon/config.yaml

data_dirs:
  - /var/lib/my-daemon
  - /var/log/my-daemon
```

#### lib 类型（双包产出）

```yaml
app:
  name: libfoo
  version: 1.0.0
  description: 共享链接库
  type: lib
  arch: [aarch64]

maintainer:
  name: Dev
  email: dev@example.com

build:
  system: cmake
  outputs:
    - build/libfoo.so.1.0.0

lib:
  headers_dir: include/
  dev_suffix: -dev

depends:
  - libc6
```

lib 类型自动产出两个 deb 包：`libfoo_1.0.0_arm64.deb`（运行时）和 `libfoo-dev_1.0.0_arm64.deb`（开发头文件 + 静态库）。

#### test 类型

```yaml
app:
  name: hw-tests
  version: 1.0.0
  description: 硬件验证测试脚本集
  type: test
  arch: [aarch64]

maintainer:
  name: Dev
  email: dev@example.com
```

test 类型将 `scripts/` 下的 shell 脚本安装到 `/usr/lib/hw-tests/`。

---

## 4. App 来源与集成

### 4.1 两种来源

```
┌──────────────────────────────────────────────────────────┐
│                    App 来源                                │
│                                                          │
│   仓库内 App（内置）              仓库外 App（外部）        │
│   app/<name>/                   独立 git 仓库             │
│   直接在 flange 仓库开发          通过板级配置声明引入       │
│                                                          │
│         └──────────┬─────────────────┘                   │
│                    ▼                                     │
│            统一的 App 工程结构                              │
│            统一的 Python DebBuilder 打包                   │
│            统一安装到 rootfs                               │
└──────────────────────────────────────────────────────────┘
```

### 4.2 仓库内 App

直接在 `app/` 目录下开发：

```
flange/
└── app/
    ├── my-display-app/
    │   ├── app.yaml
    │   ├── src/
    │   ├── conf/
    │   └── systemd/
    └── libfoo/
        ├── app.yaml
        ├── include/
        └── src/
```

在板级配置中通过包名引用：

```jsonnet
rootfs+: { custom_packages+: ['my-display-app', 'libfoo'] },
```

### 4.3 仓库外 App（外部集成）

在板级配置的 `external_apps` 字段中声明 git 源，由 `SourceManager` 自动拉取：

```jsonnet
// board/my-board/config.jsonnet
{
  rootfs+: {
    custom_packages+: ['my-display-app', 'zigbee-daemon'],
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
配置解析引擎求值 board config.jsonnet
    │
    ├── 识别 packages 列表中的包名
    ├── SourceManager 在 app/ 目录查找仓库内 App
    ├── 未找到 → 查找 external_apps 声明
    │
    ▼
SourceManager 克隆外部 App 到 sources/apps/<name>
    │
    ▼
AppBuilder 读取 App 目录中的 app.yaml
    │
    ▼
DebBuilder 打包 → .deb → 安装到 rootfs
```

外部 App 必须遵循与仓库内 App 相同的工程结构（包含 `app.yaml`）。

---

## 5. 服务管理

### 5.1 systemd 集成

`type: service` 的 App 通过 systemd 管理生命周期。service unit 文件在 App 工程内维护，通过 `app.yaml` 的 `systemd:` 段声明。

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

### 5.3 auto_start 行为

```yaml
systemd:
  unit: systemd/my-daemon.service
  auto_start: true    # deb postinst 中执行 systemctl enable
```

- `auto_start: true`：deb 安装时自动执行 `systemctl enable`，系统启动时自动拉起
- `auto_start: false`：仅安装 unit 文件，需要手动 enable

---

## 6. deb 打包机制

### 6.1 Python DebBuilder

`builder/deb.py` 中的 `DebBuilder` 是 App 打包的核心，职责：

```
DebBuilder
    │
    ├── 读取 AppSpec → 提取 name/version/description/maintainer
    ├── 生成 debian/control 文件（架构自动映射 aarch64 → arm64）
    ├── 收集编译产物（按约定映射 + install 覆盖）
    ├── 处理 systemd unit（可选）
    ├── 处理 conffiles 声明（可选）
    ├── 生成 postinst/prerm 脚本（systemd enable/disable、data_dirs 创建等）
    │
    ▼
产出: <name>_<version>_<arch>.deb（纯 Python 实现，无需系统 ar/dpkg-deb）
```

### 6.2 lib 类型双包产出

lib 类型自动产出两个 deb 包，由 `AppBuilder` 触发两次 `DebBuilder` 调用：

```
libfoo_1.0.0_arm64.deb    ← 运行时包：.so 文件
libfoo-dev_1.0.0_arm64.deb ← 开发包：头文件 + 静态库（后缀由 lib.dev_suffix 配置）
```

### 6.3 deb 安装到 rootfs 的流程

```
rootfs 构建阶段（Docker 容器内，Python 驱动）
    │
    ├── AppBuilder 收集所有需要安装的 App
    │   ├── 板级配置 packages 列表过滤
    │   ├── 仓库内 App（app/<name>/）
    │   └── 外部 App（sources/apps/<name>/）
    │
    ├── DebBuilder 打包 → <name>_<version>_<arch>.deb
    │
    ├── 创建 rootfs chroot 环境（基于 ubuntu-base）
    │
    ├── apt install 系统级依赖包
    │
    └── dpkg -i *.deb 安装自定义 App
        ├── 文件安装到声明的路径
        ├── postinst 执行（创建 data_dirs、systemctl enable 等）
        └── conffiles 注册
```

---

## 7. App 工程目录模板

### 7.1 exec 类型

```
my-tool/
├── app.yaml                # App 唯一配置文件
├── src/                    # 源码
│   └── main.c
├── conf/                   # 默认配置文件（可选）→ /etc/my-tool/
│   └── config.yaml
└── res/                    # 资源文件（可选）→ /usr/share/my-tool/
    └── ...
```

### 7.2 service 类型

```
my-daemon/
├── app.yaml                # App 唯一配置文件
├── src/                    # 源码
│   └── main.c
├── conf/                   # 默认配置文件 → /etc/my-daemon/
│   └── daemon.yaml
├── res/                    # 资源文件（可选）
│   └── ...
└── systemd/                # systemd unit 文件 → /lib/systemd/system/
    └── my-daemon.service
```

### 7.3 lib 类型

```
libfoo/
├── app.yaml                # App 唯一配置文件
├── include/                # 公开头文件 → /usr/include/libfoo/（dev 包）
│   └── foo.h
├── src/                    # 源码
│   └── foo.c
└── conf/                   # 库配置（可选）
    └── ...
```

### 7.4 test 类型

```
hw-tests/
├── app.yaml                # App 唯一配置文件
└── scripts/                # 测试脚本 → /usr/lib/hw-tests/
    ├── test_wifi.sh
    ├── test_gpio.sh
    └── test_camera.sh
```

---

## 8. CLI 脚手架命令

### 8.1 flange create app

`flange create app` 命令自动生成 App 工程脚手架：

```bash
flange create app <name> [--type=<type>] [--build-system=<system>] [--dir=<path>] [--version=<ver>] [--description=<desc>]
```

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `<name>` | App 名称 | 必填 |
| `--type` | App 类型：`exec` / `service` / `lib` / `test` | `exec` |
| `--build-system` | 构建系统：`none` / `cmake` / `meson` / `make` / `swift` | `cmake` |
| `--dir` | 生成位置的**父目录**（支持 `~`、相对 cwd）；实际目录 = `<dir>/<name>/` | `components/app/` |
| `--version` | 初始版本号 | `0.1.0` |
| `--description` | 简短描述 | 空 |

> 使用 `--dir` 指向 `components/app/` 以外的目录时，脚手架会在 stdout 追加一段
> "注册指引"，提示在 config 里以 `external_apps.local_path` 或 `external_app_dirs`
> 注册该位置，详见 §8.4 "out-of-tree App 与查找优先级"。

支持的 type × build-system 组合：

| | none | cmake | meson | make | swift |
|--|------|-------|-------|------|-------|
| exec | Y | Y | Y | Y | Y |
| service | Y | Y | Y | Y | Y |
| lib | - | Y | Y | Y | - |
| test | Y | - | - | - | - |

### 8.2 使用示例

```bash
# 创建一个 service 类型的 App（CMake）
$ flange create app my-daemon --type=service
  App 脚手架已生成：app/my-daemon/
  # app/my-daemon/
  # ├── app.yaml
  # ├── CMakeLists.txt
  # ├── src/main.c
  # ├── conf/config.yaml
  # └── systemd/my-daemon.service

# 创建一个 Meson 项目的 App
$ flange create app my-app --type=exec --build-system=meson
  App 脚手架已生成：app/my-app/

# 创建一个预编译包（无需编译步骤）
$ flange create app my-prebuilt --type=exec --build-system=none
  App 脚手架已生成：app/my-prebuilt/

# 创建一个链接库（CMake）
$ flange create app libbar --type=lib --build-system=cmake
  App 脚手架已生成：app/libbar/

# 创建测试脚本集
$ flange create app board-tests --type=test
  App 脚手架已生成：app/board-tests/
```

### 8.3 其他 App 相关命令

| 命令 | 说明 |
|------|------|
| `flange build app` | 构建当前配置所需的所有 App |
| `flange build app <name>` | 构建指定 App（编译 + 打 deb 包） |
| `flange list apps` | 列出所有已注册的 App（本地 + 显式注册 + 搜索路径） |

### 8.4 out-of-tree App 与查找优先级

flange 支持把 App 源码放在仓库之外任意目录。三种声明方式按优先级查找：

1. `<project_root>/components/app/<name>/`（本地，无需配置）
2. `external_apps[<name>]`：单个 App 显式绑定到 `local_path` 或 `git`
3. `external_app_dirs[*]`：搜索路径列表，遍历找 `<dir>/<name>/app.yaml`

任一层命中即终止。三层全部未命中时报错并列出所有已尝试的路径。

`external_apps` 两分支互斥：

```python
BOARD = {
    "external_apps": {
        "wifi":   {"local_path": "~/workspace/wifi"},
        "zigbee": {"git": "ssh://git@example.com/zigbee.git", "tag": "v2.1.0"},
    },
    "external_app_dirs": ["~/my-flange-apps", "../vendor-apps"],
}
```

`local_path` / `external_app_dirs[*]` 支持 `~` 展开与相对 project_root 的路径解析，
在配置加载时统一 resolve 为绝对路径。

`flange list apps` 给每行加来源标签：`[local]` / `[external:local]` /
`[external:git]` / `[dir:<path>]`。同名多来源时主来源取优先级最高者，
其它来源以 `(also found in: ...)` 形式在次行打印。

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
│  │ app/my-app/                     │                           │
│  │ ├── app.yaml      (唯一配置源)   │                           │
│  │ ├── src/          (源码)         │                           │
│  │ ├── conf/         (配置)         │                           │
│  │ └── systemd/      (服务)         │                           │
│  └────────┬────────────────────────┘                           │
│           │                                                     │
│           ▼  板级配置引用                                        │
│  ┌─────────────────────────────────┐                           │
│  │ board/my-board/config.jsonnet   │                           │
│  │ custom_packages+: ['my-app']    │                           │
│  └────────┬────────────────────────┘                           │
│           │                                                     │
│           ▼  flange build（Docker 容器内）                       │
│  ┌─────────────────────────────────┐                           │
│  │ AppBuilder (builder/app.py)     │                           │
│  │ ├── 解析 app.yaml → AppSpec     │                           │
│  │ ├── 调用构建系统（cmake/meson…） │                           │
│  │ └── 收集产物，按约定映射路径      │                           │
│  └────────┬────────────────────────┘                           │
│           │                                                     │
│           ▼                                                     │
│  ┌─────────────────────────────────┐                           │
│  │ DebBuilder (builder/deb.py)     │                           │
│  │ ├── 生成 debian/control         │                           │
│  │ ├── 组装文件树                   │                           │
│  │ ├── 生成 postinst/prerm          │                           │
│  │ └── 产出 my-app_1.0_arm64.deb   │                           │
│  └────────┬────────────────────────┘                           │
│           │                                                     │
│           ▼  rootfs 集成                                        │
│  ┌─────────────────────────────────┐                           │
│  │ RootfsBuilder                   │                           │
│  │ ├── dpkg -i *.deb              │                           │
│  │ │   ├── /usr/bin/my-app        │                           │
│  │ │   ├── /etc/my-app/config…    │                           │
│  │ │   └── systemctl enable my-app│                           │
│  │ └── 产出 rootfs 镜像            │                           │
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

## 10. 目录结构

App 系统相关目录：

```
flange/
├── app/                    # 用户 App（仓库内）
│   ├── adbd/               # service 类型示例
│   │   ├── app.yaml
│   │   ├── bin/
│   │   ├── conf/
│   │   ├── scripts/
│   │   ├── systemd/
│   │   └── udev/
│   ├── my-display-app/     # 自定义 service App 示例
│   │   ├── app.yaml
│   │   ├── src/
│   │   ├── conf/
│   │   └── systemd/
│   └── libfoo/             # lib 类型示例
│       ├── app.yaml
│       ├── include/
│       └── src/
│
├── builder/                # 构建引擎
│   ├── app_spec.py         #   app.yaml 解析与校验 → AppSpec
│   ├── app.py              #   AppBuilder（文件收集、路径映射、构建调用）
│   ├── deb.py              #   DebBuilder（纯 Python deb 打包）
│   ├── scaffold.py         #   AppScaffold（工程脚手架生成）
│   └── templates/          #   脚手架模板文件
│       ├── app.yaml.tpl    #     通用 app.yaml 模板
│       ├── exec/           #     exec 类型模板（none/cmake/meson/make/swift）
│       ├── service/        #     service 类型模板
│       ├── lib/            #     lib 类型模板
│       └── test/           #     test 类型模板
│
└── sources/apps/           # 外部 App 源码缓存（git ignored）
    └── <name>/             #   SourceManager 克隆至此
```
