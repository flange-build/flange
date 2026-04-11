## Why

flange 的 App 生命周期存在一个关键断裂点：板级配置已声明 `custom_packages: ["adbd"]`，`app/adbd/` 目录已包含完整的文件（二进制、脚本、配置、systemd unit），但从 app.yaml 到 .deb 打包再到 rootfs 安装的整条链路完全缺失。

原有的 `flange_deb` 设计基于 Bazel/Starlark，已随 Python 迁移废弃。Bazel 方案存在已知缺陷：Starlark 无法解析 YAML（元数据需在 BUILD.bazel 中重复声明），且与 Python 构建引擎割裂（无法读取 FINAL_CONFIG）。

需要用 Python 重新实现完整的 App 打包系统，覆盖 `docs/app-architecture.md` 定义的全部能力：4 种 App 类型、5 种构建系统、双包产出、仓库内外 App 集成、CLI 脚手架命令。使 app.yaml 成为唯一数据源，打通 "App 源文件 → 编译 → .deb → rootfs" 的完整链路。

## What Changes

### 1. App 构建器 (`builder/app.py`)

新增 `AppBuilder` 类，作为 App 打包的核心引擎：

- **解析 app.yaml** — 提取包元数据（name、version、description、type、arch）、构建配置、安装映射、systemd 配置、依赖声明
- **约定式路径映射** — `bin/` → `/usr/bin/`、`conf/` → `/etc/<name>/`、`systemd/` → `/lib/systemd/system/`、`udev/` → `/lib/udev/rules.d/`、`scripts/` → `/usr/lib/<name>/`、`lib/` → `/usr/lib/`、`include/` → `/usr/include/<name>/`、`res/` → `/usr/share/<name>/`，app.yaml 的 `install` 段可覆盖默认映射
- **架构选择** — 预编译 App 按 `bin/<binary>-<arch>` 命名约定，打包时根据目标架构选择对应二进制；源码构建的 App 由交叉编译工具链决定架构
- **生成 deb control** — 从 app.yaml 生成 `control`、`conffiles`、`postinst`（systemd enable + 数据目录创建）、`prerm`（systemd disable）
- **构建 .deb** — 用 Python `tarfile` 构建 `control.tar.gz` + `data.tar.gz`，`ar` 命令打包最终 .deb

### 2. 五种构建系统支持

AppBuilder 根据 app.yaml 的 `build.system` 字段，在 Docker 容器内调用对应的构建系统：

| build.system | 调用方式 | 适用场景 |
|---|---|---|
| `none` | 不编译，直接打包 | 预编译二进制（adbd）、纯脚本/配置包（test 类型） |
| `cmake` | `cmake -B build [options] && cmake --build build` | CMake 项目 |
| `meson` | `meson setup build [options] && ninja -C build` | Meson 项目 |
| `make` | `make [vars] [targets]` | Makefile 项目 |
| `swift` | `swift build -c release --triple <target>` | Swift Package Manager 项目 |

所有构建均在 Docker 容器内执行，使用容器内的交叉编译工具链。构建选项通过 app.yaml 的 `build.options` 传递。

### 3. 四种 App 类型

完整实现 `docs/app-architecture.md` 定义的四种类型：

**exec** — 可执行文件，手动启动。产出 1 个 .deb，安装到 `/usr/bin`。

**service** — 系统服务，systemd 管理。产出 1 个 .deb + systemd unit。`auto_start: true` 时 postinst 执行 `systemctl enable`。

**lib** — 链接库，被其他 App 依赖。产出 2 个 .deb：
- `lib<name>` — 运行时包，包含 .so，安装到 `/usr/lib`
- `lib<name>-dev` — 开发包，包含头文件和静态库，安装到 `/usr/include/<name>` + `/usr/lib`

**test** — 测试脚本集，部署到目标执行。产出 1 个 .deb，脚本安装到 `install` 段声明的路径。

### 4. app.yaml 完整 Schema

在现有 app.yaml 基础上扩展为唯一数据源，替代原 BUILD.bazel 的全部职责：

```yaml
app:
  name: my-daemon
  version: 1.0.0
  description: 示例守护进程
  type: service              # exec / service / lib / test
  arch: [aarch64, armhf]

maintainer:
  name: flange
  email: flange@localhost

capabilities: [network, usb-gadget]   # 可选，App 能力标签

# ── 构建配置（预编译/纯脚本 App 不需要）──
build:
  system: cmake              # cmake / meson / make / swift / none
  options:                   # 传递给构建系统的选项
    CMAKE_BUILD_TYPE: Release
    ENABLE_TESTS: OFF
  outputs: [bin/my-daemon]   # 构建产物路径（相对于 build 目录）
  deps: [libfoo]             # App 间构建依赖（lib 类型的 App）

# ── 安装路径映射（可选，覆盖约定默认值）──
install:
  bin/my-daemon: /usr/bin/my-daemon
  conf/config.yaml: /etc/my-daemon/config.yaml

# ── systemd 配置（仅 service 类型）──
systemd:
  unit: systemd/my-daemon.service
  auto_start: true

# ── deb 打包配置 ──
depends: [libc6, libssl3]                  # 运行期 apt 依赖
conffiles: [/etc/my-daemon/config.yaml]    # dpkg 升级保护
data_dirs: [/var/lib/my-daemon]            # postinst 创建的数据目录

# ── lib 类型专用（双包产出）──
lib:
  headers_dir: include/      # 公开头文件目录
  package_suffix: ""         # 运行时包后缀（默认空）
  dev_suffix: "-dev"         # 开发包后缀
```

### 5. App 间依赖解析

lib 类型 App 需要在依赖它的 App 之前构建。AppBuilder 实现 App 级拓扑排序（复用 `engine.py` 的 `_topo_sort` 模式）：

1. 扫描所有待构建 App 的 `build.deps` 字段
2. 拓扑排序确定构建顺序
3. lib App 构建后，将头文件和 .so 安装到 `target/sysroot/` 供后续 App 编译使用
4. 后续 App 编译时通过 `-I` / `-L` 指向 sysroot

### 6. 仓库内 + 仓库外 App

**仓库内 App**：`app/<name>/` 目录下，包含 app.yaml 和全部源文件。通过 `custom_packages` 配置引用。

**仓库外 App**：板级配置中声明 git 源，由 `SourceManager` 拉取：

```python
# board config 中声明
"external_apps": {
    "zigbee-daemon": {
        "git": "ssh://git@gitlab.example.com/apps/zigbee.git",
        "tag": "v2.1.0",
    },
},
```

AppBuilder 查找顺序：先在 `app/` 目录查找仓库内 App，未找到则查找 `external_apps` 声明，由 SourceManager 克隆到 `sources/apps/<name>` 后按相同流程构建。外部 App 必须遵循相同的工程结构（包含 app.yaml）。

### 7. Rootfs 集成

修改各平台 rootfs builder 的 Phase 2 (Customize) 阶段，安装 custom packages：

```
Phase 2 流程：
  1. overlay 复制（已有）
  2. 构建 custom_packages 中声明的所有 App .deb
  3. chroot dpkg -i 安装所有 .deb
```

App 的构建在 rootfs 之前完成（加入 engine.py 的依赖图），.deb 产物供 rootfs builder 消费。

### 8. CLI 命令

扩展 `envsetup.sh` 和 `flange` 命令：

| 命令 | 说明 |
|------|------|
| `flange build app <name>` | 单独构建指定 App 的 .deb |
| `flange build app` | 构建当前配置所需的所有 App |
| `flange create app <name> --type=<type> [--build-system=<system>]` | 生成 App 工程脚手架 |
| `flange list apps` | 列出所有可用 App（仓库内 + 外部） |

### 9. `flange create app` 脚手架

根据 `--type` 和 `--build-system` 参数，自动生成 App 工程目录：

```bash
flange create app my-daemon --type=service --build-system=cmake
  创建: app/my-daemon/
  ├── app.yaml             # 预填 type=service, build.system=cmake
  ├── CMakeLists.txt       # CMake 项目模板
  ├── src/main.c           # 源码模板
  ├── conf/config.yaml     # 默认配置模板
  └── systemd/my-daemon.service  # systemd unit 模板
```

模板文件存放在 `builder/templates/`，按 type × build-system 组织。支持的组合：

| type \ build-system | none | cmake | meson | make | swift |
|---|---|---|---|---|---|
| exec | Y | Y | Y | Y | Y |
| service | Y | Y | Y | Y | Y |
| lib | - | Y | Y | Y | - |
| test | Y | - | - | - | - |

### 10. 文档同步

全面更新 `docs/app-architecture.md`：
- 移除所有 Bazel/Starlark/BUILD.bazel 引用
- 用 Python 实现描述替代（app.yaml 为唯一数据源，无需 BUILD 文件）
- 更新数据流图、目录结构、CLI 示例
- 移除迁移状态提示

## 非目标

- **不实现 App 级增量缓存** — App 的增量判断复用现有 `BuildCache` 的 content hash 机制，不做 action 级细粒度缓存
- **不实现 App 的 OTA 单独更新** — App 随 rootfs 整体刷写，独立 OTA 属于刷写增强范畴
- **不处理 adbd 的 RSA 认证** — 开发阶段不需要
- **不实现 App 的版本冲突检测** — 假设同一配置下不会声明同名不同版本的 App

## Capabilities

### New Capabilities

- **app-builder**: Python App 构建器核心引擎，解析 app.yaml、调用 5 种构建系统、约定式路径映射、deb control 生成、.deb 打包、lib 双包产出
- **app-dependency-resolver**: App 间依赖拓扑排序、sysroot 管理
- **app-rootfs-integration**: custom_packages 从配置声明到 rootfs 安装的完整链路
- **app-external-source**: 仓库外 App 的 git 源声明、自动拉取、统一构建
- **app-scaffold**: `flange create app` 工程脚手架生成器，支持 type × build-system 矩阵
- **app-yaml-full-schema**: app.yaml 完整 schema，支持 build/install/systemd/depends/conffiles/data_dirs/lib 全部声明

### Modified Capabilities

- **rootfs-builder**: 修改各平台 rootfs builder 的 Phase 2，新增 custom deb 安装步骤
- **build-engine**: engine.py 依赖图新增 app 组件节点，App 构建在 rootfs 之前完成
- **cli**: envsetup.sh 新增 `build app`、`create app`、`list apps` 子命令

## Impact

- **新增文件**: `builder/app.py`（App 构建器）、`builder/templates/`（脚手架模板目录）、`tests/builder/test_app.py`（测试）
- **修改文件**: `builder/platforms/rockchip/rootfs.py`（Phase 2 集成）、`builder/engine.py`（app 组件注册）、`builder/source.py`（外部 App 拉取）、`envsetup.sh`（新增 CLI 命令）、`app/adbd/app.yaml`（扩展 install/systemd 配置）、`docs/app-architecture.md`（Python 实现同步）
- **依赖**: Docker 容器内需要 `binutils`（`ar` 命令）和 `python3-yaml`（PyYAML）；cmake/meson/swift 等构建工具按 App 需要在 Dockerfile 中安装
- **验证**: adbd 作为第一个端到端验证的 App — 从 app.yaml 到 .deb 到 rootfs 内可运行
