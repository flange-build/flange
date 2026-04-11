## Context

flange 的 App 工程体系由 `docs/app-architecture.md` 完整定义：4 种 App 类型（exec / service / lib / test）、5 种构建系统（none / cmake / meson / make / swift）、双包产出、仓库内外 App 集成、CLI 脚手架。原设计基于 Bazel/Starlark 实现，已随 Python 迁移废弃。

现有构建体系：
- Python 构建引擎 `builder/engine.py` 管理依赖图和调度
- `ComponentBuilder` 策略模式，平台子类实现具体构建逻辑
- Docker 容器内执行编译，`DockerRunner` 封装 `docker compose run`
- `SourceManager` 管理源码仓库克隆和更新
- `BuildCache` 基于内容哈希判断是否需要重建
- rootfs 构建分 Phase 1（base apt install）和 Phase 2（customize overlay）

App 打包需要融入这套体系，而非另起炉灶。

已有的 App 资产：
- `app/adbd/` — 完整的 service 类型 App（预编译二进制、脚本、配置、systemd unit、udev rule）
- `app/adbd/app.yaml` — 基础元数据（name、version、type、arch）
- `board/radxa-zero3w/config.py` — 已声明 `custom_packages: ["adbd"]`

缺失的链路：app.yaml 解析 → 构建系统调用 → .deb 打包 → rootfs 安装。

## Goals / Non-Goals

**Goals:**

- 实现完整的 Python App 打包系统，覆盖 `docs/app-architecture.md` 定义的全部能力
- app.yaml 成为 App 的唯一数据源，不需要 BUILD 文件
- 融入现有 Python 构建引擎架构（engine/cache/docker/source）
- adbd 作为首个端到端验证 App

**Non-Goals:**

- 不实现 App 级 action 缓存（复用 BuildCache 组件级 content hash）
- 不实现 App 的独立 OTA 更新（属于刷写增强范畴）
- 不处理 dpkg triggers、alternatives 等高级特性

## Decisions

### 决策 1: Pure Python 构建 .deb，不依赖 dpkg-deb

.deb 本质上是一个 `ar` 归档，结构简单且固定：

```
package.deb (ar archive)
├── debian-binary        # 固定内容 "2.0\n"
├── control.tar.gz       # control, conffiles, postinst, prerm
└── data.tar.gz          # 实际安装文件树
```

用 Python `tarfile` 模块构建 `control.tar.gz` 和 `data.tar.gz`，用 `ar` 命令（Docker 容器内 `binutils` 提供）打包最终 .deb。

**理由**:
- `tarfile` 是 Python 标准库，零外部依赖
- control 文件从 app.yaml 生成，全部字段可控可测
- 与 flange Python 统一架构一致
- Bazel 时代的 shell 脚本方案（决策 1）已验证 .deb 格式的简单性

**替代方案**: 调用 `dpkg-deb --build`。更简单但成为黑盒，control 格式错误时报错信息不友好。

### 决策 2: app.yaml 为唯一数据源，消除 BUILD 文件

Bazel 时代的核心痛点：Starlark 不能解析 YAML，导致 app.yaml 仅作参考，元数据必须在 BUILD.bazel 中重复声明（`docs/app-architecture.md` §11.1 已记录此问题）。

Python 方案中，app.yaml 承担原 BUILD.bazel 的全部职责：

```
Bazel 时代                          Python 时代
─────────────                      ──────────────
app.yaml   → 身份证（元数据）        app.yaml → 唯一数据源
BUILD.bazel → 施工图（构建+打包）               （元数据 + 构建 + 打包）
```

app.yaml 解析使用 PyYAML（`yaml.safe_load`），在构建引擎的 Python 进程中直接执行，无语言边界。

**理由**: 消除重复声明，app.yaml 所见即所得。PyYAML 是成熟的库，`safe_load` 防止任意代码执行。

### 决策 3: 约定式路径映射 + 显式覆盖

App 目录结构与安装路径的映射遵循约定优于配置原则：

| App 目录 | 默认安装路径 | 说明 |
|---|---|---|
| `bin/` | `/usr/bin/` | 可执行文件 |
| `lib/` | `/usr/lib/` | 动态链接库 |
| `include/` | `/usr/include/<name>/` | 头文件（lib 类型） |
| `conf/` | `/etc/<name>/` | 配置文件 |
| `scripts/` | `/usr/lib/<name>/` | 辅助脚本 |
| `systemd/` | `/lib/systemd/system/` | systemd unit |
| `udev/` | `/lib/udev/rules.d/` | udev 规则 |
| `res/` | `/usr/share/<name>/` | 资源文件 |

app.yaml 的 `install` 段可逐文件覆盖默认映射：

```yaml
install:
  bin/adbd-arm64: /usr/bin/adbd           # 重命名 + 指定路径
  conf/usbdevice.conf: /etc/usbdevice.conf  # 不走 /etc/<name>/ 约定
```

如果 `install` 段未声明，按约定映射整个目录。如果声明了，仅映射显式列出的文件。

**理由**: 大多数 App 的目录结构是标准化的（adbd 的 bin/conf/systemd/udev 就是典型模式），约定映射使 app.yaml 最小化。特殊需求通过显式覆盖处理。

### 决策 4: 构建系统作为黑盒调用

AppBuilder 不理解各构建系统的内部逻辑，只负责：
1. 根据 `build.system` 选择命令模板
2. 用 `build.options` 填充模板参数
3. 通过 `DockerRunner` 在容器内执行
4. 从 `build.outputs` 收集产物

```python
# builder/app.py 中的构建系统命令模板
_BUILD_SYSTEMS = {
    "none": [],  # 预编译，跳过
    "cmake": [
        ["cmake", "-B", "build",
         "-DCMAKE_C_COMPILER=aarch64-linux-gnu-gcc",
         "-DCMAKE_CXX_COMPILER=aarch64-linux-gnu-g++",
         "{options}"],
        ["cmake", "--build", "build", "-j$(nproc)"],
    ],
    "meson": [
        ["meson", "setup", "build",
         "--cross-file", "/etc/meson/cross-aarch64.ini",
         "{options}"],
        ["ninja", "-C", "build"],
    ],
    "make": [
        ["make",
         "ARCH=arm64",
         "CROSS_COMPILE=aarch64-linux-gnu-",
         "-j$(nproc)",
         "{targets}", "{options}"],
    ],
    "swift": [
        ["swift", "build",
         "-c", "release",
         "--triple", "aarch64-unknown-linux-gnu",
         "{options}"],
    ],
}
```

`{options}` 占位符在运行时从 `build.options` 展开为 `-D<key>=<value>` 或 `--<key>=<value>` 格式（取决于构建系统）。

**理由**: 跟 Debian 的 `dpkg-buildpackage` 调用 `debian/rules` 是同样的模式 — 打包器不需要理解构建系统，只需要知道怎么调用它。每种构建系统的交叉编译参数格式不同，但都是确定性的命令行模板。

**替代方案**: 在 app.yaml 中直接声明完整构建命令（`build.commands: [...]`）。灵活但牺牲了标准化——用户需要自己处理交叉编译参数。保留此方案作为高级逃生通道，命名为 `build.system: custom`。

### 决策 5: App 构建作为 engine 依赖图中的独立节点

将 App 构建插入 `builder/engine.py` 的依赖图中：

```python
DEPENDENCY_GRAPH = {
    "kernel":     [],
    "bootloader": [],
    "app":        [],              # 新增：App 构建不依赖其他组件
    "rootfs":     ["app"],         # 修改：rootfs 依赖 App（需要 .deb）
    "boot":       ["kernel"],
    "image":      ["boot", "bootloader", "rootfs"],
}
```

App 构建由 `AppBuilder` 处理（不走 `ComponentBuilder` 继承体系，因为 App 不是平台策略类）。engine 在调度到 "app" 节点时，调用 `AppBuilder` 构建所有 `custom_packages` 声明的 App。

**理由**:
- App .deb 是 rootfs Phase 2 的输入，必须先于 rootfs 构建
- App 构建不依赖 kernel/bootloader，可以与它们并行（未来并行构建优化时受益）
- engine 统一调度，BuildCache 统一管理缓存

### 决策 6: lib 双包产出策略

lib 类型 App 产出两个 .deb：

```
libfoo/
├── app.yaml (type: lib)
├── include/foo.h
├── src/foo.c
└── lib:                     # app.yaml 中的 lib 段
      headers_dir: include/
      dev_suffix: -dev
```

AppBuilder 对 lib 类型执行两次打包：

1. **运行时包** `libfoo_<ver>_<arch>.deb`:
   - `data.tar.gz` 包含 `/usr/lib/libfoo.so*`
   - `control` 的 Depends 正常填写

2. **开发包** `libfoo-dev_<ver>_<arch>.deb`:
   - `data.tar.gz` 包含 `/usr/include/foo/` + `/usr/lib/libfoo.a`（如有）
   - `control` 的 Depends 包含 `libfoo (= <version>)`

两个包都安装到 rootfs（开发包仅在 debug variant 时安装，通过条件标记 `+custom_packages:debug` 控制）。

**理由**: 遵循 Debian 双包约定（libfoo + libfoo-dev），开发者在目标设备上有头文件可以交叉验证。debug variant 安装 -dev 包对嵌入式开发场景实用。

### 决策 7: 预编译二进制的架构选择

预编译 App（`build.system: none`）通过文件命名约定选择架构：

```
bin/adbd-arm64          → aarch64 时选择
bin/adbd-armhf          → armhf 时选择
bin/my-tool-aarch64     → 同 arm64
```

架构映射表：

| config["arch"] | 匹配后缀 |
|---|---|
| `aarch64` | `-arm64`, `-aarch64` |
| `armhf` | `-armhf`, `-arm32` |

匹配时去掉架构后缀，打包时重命名为不带后缀的文件名（`adbd-arm64` → `/usr/bin/adbd`）。

如果 `install` 段显式声明了映射（`bin/adbd-arm64: /usr/bin/adbd`），直接使用声明的映射，跳过自动匹配。

**理由**: 与现有 adbd 的文件组织方式（`bin/adbd-arm64`、`bin/adbd-armhf`）一致，不需要改动现有 App。显式 install 映射提供逃生通道。

### 决策 8: 仓库外 App 通过 SourceManager 拉取

板级配置中声明的 `external_apps` 由 `SourceManager` 统一管理：

```python
# SourceManager 新增方法
def ensure_app(self, app_name: str, config: dict) -> Path:
    """确保 App 源码就绪，返回 App 目录路径。"""
    # 1. 先查 app/<name>/ 仓库内目录
    local_dir = Path(f"app/{app_name}")
    if local_dir.exists():
        return local_dir
    # 2. 查 external_apps 配置
    ext = config.get("external_apps", {}).get(app_name)
    if not ext:
        raise ValueError(f"App '{app_name}' 未找到：不在 app/ 目录，也未在 external_apps 中声明")
    # 3. 克隆到 sources/apps/<name>
    app_dir = self.sources_dir / "apps" / app_name
    if not app_dir.exists():
        self._clone(repo=ext["git"], branch=ext.get("branch", ""), dest=app_dir,
                    commit=ext.get("tag", ext.get("commit", "")))
    return app_dir
```

外部 App 克隆到 `sources/apps/<name>`，后续流程与仓库内 App 完全一致。

**理由**: 复用 SourceManager 的 git 克隆能力（shallow clone、commit lock、SSH key 传递），不引入新的源码管理机制。`sources/` 目录已在 `.gitignore` 中。

### 决策 9: App 间依赖通过 sysroot 传递

lib 类型 App 构建后，将头文件和 .so 安装到 `target/<board>/<product>/<variant>/sysroot/`：

```
target/radxa-zero3w/default/debug/sysroot/
├── usr/include/foo/foo.h
└── usr/lib/libfoo.so
```

后续 App 编译时，构建系统命令模板追加 sysroot 参数：

```python
# cmake 追加
["-DCMAKE_SYSROOT={sysroot}", "-DCMAKE_FIND_ROOT_PATH={sysroot}"]

# meson cross file 中
[sys_root] = '{sysroot}'

# make 追加
["CFLAGS=-I{sysroot}/usr/include", "LDFLAGS=-L{sysroot}/usr/lib"]
```

构建顺序由 `build.deps` 字段决定，AppBuilder 内部拓扑排序：

```python
def _resolve_build_order(self, app_names: list) -> list:
    """根据 build.deps 拓扑排序 App 构建顺序。"""
    graph = {}
    for name in app_names:
        spec = self._load_spec(name)
        graph[name] = spec.get("build", {}).get("deps", [])
    return _topo_sort(graph)
```

**理由**: sysroot 是交叉编译的标准模式（cmake/meson/make 都原生支持）。拓扑排序复用 engine.py 已有的 `_topo_sort` 函数。

### 决策 10: postinst 脚本兼容 chroot 环境

沿用 Bazel 时代设计（已实际验证）：deb 安装发生在 rootfs 构建的 chroot 内，systemd 不在运行。postinst 需做环境检测：

```bash
#!/bin/bash
set -e

# systemd enable（兼容 chroot）
if [ -d /run/systemd/system ]; then
    systemctl daemon-reload
    systemctl enable {service_name}
else
    # chroot 内：手动创建 symlink
    WANTED_BY=$(grep "^WantedBy=" /lib/systemd/system/{service_name} | cut -d= -f2)
    for target in $WANTED_BY; do
        mkdir -p /etc/systemd/system/$target.wants
        ln -sf /lib/systemd/system/{service_name} /etc/systemd/system/$target.wants/
    done
fi

# 创建数据目录
{mkdir_commands}
```

prerm 脚本：

```bash
#!/bin/bash
set -e
if [ -d /run/systemd/system ]; then
    systemctl stop {service_name} 2>/dev/null || true
    systemctl disable {service_name} 2>/dev/null || true
fi
```

**理由**: 这是 Bazel 时代实际验证中发现的必要处理 — `systemctl enable` 在 chroot 中会失败。Debian 官方包也使用类似的环境检测逻辑。

### 决策 11: 脚手架模板按 type × build-system 组织

```
builder/templates/
├── app.yaml.j2                    # 通用 app.yaml Jinja2 模板
├── exec/
│   ├── cmake/
│   │   ├── CMakeLists.txt.j2
│   │   └── src/main.c.j2
│   ├── meson/
│   │   ├── meson.build.j2
│   │   └── src/main.c.j2
│   ├── make/
│   │   ├── Makefile.j2
│   │   └── src/main.c.j2
│   ├── swift/
│   │   ├── Package.swift.j2
│   │   └── Sources/main.swift.j2
│   └── none/                      # 预编译
│       └── (空，只生成 app.yaml)
├── service/
│   ├── cmake/ ...                 # 同 exec + systemd unit 模板
│   ├── systemd/
│   │   └── {name}.service.j2
│   └── conf/
│       └── config.yaml.j2
├── lib/
│   ├── cmake/
│   │   ├── CMakeLists.txt.j2     # 带 shared lib target
│   │   ├── include/{name}.h.j2
│   │   └── src/{name}.c.j2
│   ├── meson/ ...
│   └── make/ ...
└── test/
    └── none/
        └── scripts/test_example.sh.j2
```

使用 Jinja2 模板引擎（如不想引入依赖，可用 Python `string.Template`），`{name}` 在生成时替换为 App 名。

**理由**: type × build-system 的组合是有限且确定的，预定义模板比运行时拼接更可维护。Jinja2 是 Python 生态的标准模板引擎，也是 Ansible/Flask 等项目使用的。

**替代方案**: 用 `string.Template`（标准库），避免 Jinja2 依赖。模板功能够用（只需变量替换，不需要循环/条件），但 Jinja2 未来扩展性更好。优先尝试 `string.Template`，复杂度不够再切 Jinja2。

### 决策 12: build.system: custom 逃生通道

除 5 种标准构建系统外，支持 `build.system: custom`，允许用户在 app.yaml 中直接声明构建命令：

```yaml
build:
  system: custom
  commands:
    - ["./configure", "--host=aarch64-linux-gnu", "--prefix=/usr"]
    - ["make", "-j$(nproc)"]
    - ["make", "install", "DESTDIR={build_dir}"]
  outputs: [bin/my-tool]
```

AppBuilder 按顺序执行 `commands` 列表中的命令。

**理由**: 总有构建系统不在 5 种之列的情况（autotools、cargo、go 等），custom 提供逃生通道而不需要改框架代码。

## Risks / Trade-offs

- **[PyYAML 依赖]** → Docker 容器需要安装 `python3-yaml`。Ubuntu base 不预装。→ Dockerfile 中 `apt install python3-yaml`，或者 `pip install pyyaml`。体积增量可忽略。
- **[ar 命令可用性]** → .deb 打包依赖 `ar`（binutils）。Docker 容器中通常已有，但需确保 Dockerfile 声明。→ 在 Dockerfile 中显式 `apt install binutils`。
- **[构建系统交叉编译参数]** → 不同版本的 cmake/meson 交叉编译参数可能有差异。→ 命令模板基于 Docker 容器内固定版本的工具，版本由 Dockerfile 锁定。
- **[App 间循环依赖]** → `build.deps` 拓扑排序不处理循环依赖。→ 嵌入式场景中 App 间循环依赖是设计错误，拓扑排序时检测并报错即可。
- **[sysroot 污染]** → 多个 lib App 安装到同一个 sysroot 可能产生冲突。→ 嵌入式项目 lib 数量有限（通常个位数），命名冲突概率低。如有冲突，构建时会报错。
- **[外部 App 信任]** → external_apps 声明的 git 仓库是用户指定的，flange 不做安全审查。→ 与 kernel/bootloader 的外部仓库是同样的信任模型，由用户负责。
