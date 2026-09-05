# ProjectSpec — flange 项目规格

本文档是 flange 项目的权威规格文档，涵盖项目目标、架构设计、编码规范、开发规范与维护规范。所有贡献者（人类与 AI Agent）均须遵守。

---

## 1. 项目目标

flange 是一个嵌入式 Linux 系统构建框架，基于 ubuntu-base 构建，复用发行版软件包，
将板级系统构建、App（应用）开发和设备维护统一到同一工具入口。
与 Buildroot / Yocto 的速度和可靠性比较需要相同目标下的测量，不作为未经验证的保证。

### 1.1 核心目标
1. 提供内核快速验证通道
2. 提供文件系统快速验证通道
3. 提供全系统级别快速验证通道
4. 提供产品级烧录镜像输出，支持 UFS、eMMC、SPI、SD 卡等多种存储介质
5. 支持独立 out-of-tree（源码树外）工作区中的 App 创建、计划、构建、部署、运行、测试、调试与日志查看
6. 以明确输入、目标隔离、准确产物清单与关联验证记录连接开发闭环；SDK 分发、锁定发布、
   系统级符号和完整硬件验收仍需持续完善，验证范围见[设计评审](docs/build-system-review.md)

### 1.2 核心优势
- 使用求值后的统一配置表达产品、变体与硬件差异
- 使用组件内容哈希、单 App 缓存与 rootfs 基础快照减少重复工作
- 以复用现有 apt 软件包为主，支持将自定义软件打包为 apt 包
- 最终产出可直接刷写的产品级镜像

---

## 2. 架构设计

### 2.1 构建模型

flange 采用 **Docker 容器化构建 + 宿主机部署** 的分离架构：

```
┌─────────────────────────────┐     ┌──────────────────────────┐
│        Docker 容器           │     │         宿主机            │
│                             │     │                          │
│  交叉编译工具链              │     │  刷写工具（平台相关）       │
│  内核/bootloader/rootfs 构建  │────▶│  USB 连接目标设备          │
│  镜像打包                    │     │  分区级刷写               │
│                             │     │                          │
│  输出: .build/target/        │     │  读取: .build/target/     │
└─────────────────────────────┘     └──────────────────────────┘
```

- **构建环境**：目标代码编译和镜像制作在 Docker 容器内完成，统一工具环境；
  严格复现还需固定源码版本、实际容器/工具链身份、软件包输入及文件系统语义
- **部署环境**：镜像刷写在宿主机执行，通过 USB 连接目标设备
- 工作区 `build_root/target/` 是容器与宿主机之间的产物桥梁；工具根、工作区及外部源码通过同绝对路径挂载。
- 内核源码和工作树必须位于大小写敏感文件系统；macOS 默认 APFS 不满足时，必须将
  `flange.toml` 的 `build_dir` 指向 APFS Case-sensitive 卷或使用 Linux ext4。环境不满足时早失败，
  禁止通过自动关闭驱动或修改目标 Kconfig 适配宿主文件系统。
- rootfs/recovery 的可变文件树在容器原生 `/var/tmp` 临时目录中完成解包、包安装、定制与成像。
  宿主共享目录即使大小写敏感，也不能据此认定具备 Linux 权限和 UID/GID 语义。
  最终镜像、清单与基础快照归档仍写入工作区持久化目录。

### 2.2 支持平台

支持多种嵌入式 SoC 平台，每个平台有对应的刷写工具链：

| 平台 | 刷写工具 | 连接方式 |
|------|---------|---------|
| Rockchip | `upgrade_tool` | USB |
| Amlogic | `fastboot` | USB |
| Allwinner | `dd` | SD 卡 / USB |
| Qualcomm | `edl-ng` | USB（EDL） |

刷写工具运行在宿主机上，不纳入 Docker 构建环境。各平台 `flash_tool` 在
`components/platform/<vendor>/config.jsonnet` 声明。

### 2.3 组件级构建与刷写

Python 构建引擎 (builder/engine.py) 管理组件依赖图，基于内容哈希实现增量构建。产物由引擎校验后发布到当前工作区的 build_root/target/<board>/<product>/<variant>/。

| 组件 | 构建命令 | 刷写命令 |
|------|---------|---------|
| Bootloader | `flange build bootloader` | 按 `flange flash --list` 中的实际分区名刷写 |
| Kernel / boot 分区 | `flange build kernel`，需要 boot 镜像时再 `flange build boot` | 清单包含 boot 时使用 `flange flash boot` |
| Rootfs | `flange build rootfs` | `flange flash rootfs` |
| Recovery | `flange build recovery` | `flange flash recovery` 或 USB ADB 在线写 |
| 全量镜像 | `flange build` | `flange flash` |

- 组件构建：在 Docker 容器内执行，构建引擎自动推断组件间依赖并基于内容哈希决定增量构建范围
- 产物收集：完整输出通过 ArtifactManifest（产物清单）验证后原子替换组件发布目录；失败保留上次成功产物
- 组件刷写：在宿主机执行，读取构建期生成的 `flash-config.json` 并按平台策略调用刷写工具
- 全量刷写：重写设备全部分区（分区表 + 所有组件镜像）
- 构建参数是组件名，刷写参数是生成清单中的分区名，两者不能通用互换。
  MTD / SPI NAND 路径提供 `kernel → boot`、`bootloader → uboot` 兼容别名，GPT 路径不通用此映射。

### 2.4 USB 线刷 Recovery

设备启动后可通过 `flange recovery` 命令组（宿主机）+ `recoveryctl`（设备端）
完成在线维护与分区级线刷，事实源是构建时冻结的 `/etc/flange/recovery-config.json`：

- **独立分区与独立 rootfs**：`recovery` 是独立 ext4 分区（label=recovery），
  与 normal rootfs 互不依赖；normal 损坏时仍能启动维护
- **双 extlinux 配置 + U-Boot 启动选择**：boot 分区生成
  `/extlinux/extlinux.conf`（normal）与 `/extlinux/recovery.conf`
  （recovery）；进入 recovery 时通过 Linux reboot reason
  `reboot("recovery")` 让 U-Boot 本次选择 `recovery.conf`，可选
  `flange_boot_once=recovery` 作为断电保持兜底，不持久修改 extlinux DEFAULT
- **Device Tree Overlay（设备树覆盖）**：运行期 overlay 统一通过
  `boot.overlays.{intree,vendor,board,package,enabled}` 声明来源与启用顺序；
  构建期 DTBO 合并单独使用 `kernel.device_tree.build_overlays`；
  boot 分区统一使用 `/extlinux/` 存放 Image 和 extlinux 配置，使用
  `/dtbs/<vendor>/` 存放 base DTB，overlay 位于
  `/dtbs/<vendor>/overlay/`。extlinux 中的路径以 boot 分区根为基准，
  不带 Linux 挂载后的 `/boot` 前缀。U-Boot 环境必须提供
  `fdtoverlay_addr_r` 供 extlinux `fdtoverlays` 临时加载 overlay。
- **首版 transport = ADB over USB**：`flange recovery enter/list/flash/backup
  /shell/reboot` 通过 ADB 编排 `recoveryctl`；后续可扩展 USB DFU
- **在线刷写默认流式写入**：`flange recovery flash` 通过 `adb forward
  + 设备端 127.0.0.1 TCP listen` 把镜像数据流式写入目标分区，控制面走
  `adb shell` 的 stdout 单行 ASCII 控制行；不要求 recovery 文件系统
  暂存完整镜像
- **硬约束（数据面）**：recovery 数据面（flash/backup）必须走 `adb forward
  + 设备端 127.0.0.1 TCP listen`；控制面走 `adb shell` 的 stdout 单行
  ASCII 控制行（`PORT=`/`READY`/`PROGRESS:`/`STATUS:OK`/`STATUS:FAIL:`）。
  禁止依赖 `adb exec:` service 或 `shell:v2` protocol，以保留既有
  recovery 控制与数据协议的兼容范围。当前内置 adbd 已升级为 ADB 36.0.1，
  版本、补丁与验证范围见 [adbd README](components/app/adbd/README.md)；
  守护进程升级不自动改变上述传输协议约束
- **安全策略**：bootloader/raw 与 recovery 自身默认 protected；强制写入
  需要 `--force` 双重确认（host 输入 `YES` + device 端要求 `--sha256`）
- **不属于范围**：OTA / A/B 切换 / 网络烧录 / recovery 自升级

详细用户文档与排障：[`docs/recovery.md`](docs/recovery.md)。

### 2.5 App 与 Package 开发生命周期

- 安装入口为 `flange` / `python -m builder`；`envsetup.sh` 只准备 Python 环境与 `lunch` 包装。
  `flange init` 创建 `flange.toml`，`WorkspaceContext` 明确工具根、工作区根、输出根、目标和 App 来源。
- `flange app` / `flange package` 提供 `create/plan/build/deploy/run/test/debug/log`。
  `name-or-path` 可以是名称或路径，省略时使用调用者目录；create 的 `--dir` 指定父目录。
- App 名称、路径和 cwd 入口统一进入 AppResolver，递归解析 `build.deps`，拒绝缺失、循环和同名不同源歧义。
  AppBuilder 使用统一 Toolchain、目标隔离工作树、依赖安装前缀与准确 AppBuildReport；打包前检查 ELF 架构。
- 默认部署通过宿主 ADB（Android 调试桥），校验设备架构、实际产物及传输摘要，按运行依赖顺序安装 deb；
  多设备必须指定 `--serial`。`--no-build` 仍验证成功报告和实际文件。
- exec/test 使用已验证安装树中的 `runtime.executable`，默认 `/usr/bin/<name>`；service 使用 `systemd.unit`。
  `auto_start` 仅控制安装时是否启用服务，`run` 显式启动服务。
- debug 要求 debug target。默认设备 GDB（GNU 调试器）支持源码同步和路径映射；`--mode remote`
  使用 gdbserver、ADB 转发和宿主 GDB。系统库符号、IDE 配置和硬件调试仍需单独准备。
- `test`、部署、运行和调试会话记录 target、设备与准确产物身份；测试保存退出码、stdout/stderr。
  这些记录不等于已完成全部板卡、驱动和介质的实机验收。
- `app.yaml.actions` / `PACKAGE["actions"]` 使用 argv 列表。build action 在 Docker 的隔离副本执行；
  Package 专属产物通过 manifest 发布，后续动作消费该清单。非 build action 在宿主执行，显式动作无需先选 ADB。
- 操作与当前边界见[开发指南](docs/development-guide.md)，维护接口见[App 架构](docs/app-architecture.md)。

---

## 3. 通用原则

- **简洁优先**：代码应简洁、直接，避免过度抽象
- **可读性**：代码是写给人看的，清晰胜于巧妙
- **一致性**：同一模块内风格必须一致，跨模块尽量一致
- **最小惊讶原则**：命名和行为应符合嵌入式/Linux 社区的常见惯例
- **错误必须处理**：嵌入式系统中未处理的错误会导致不可预测的行为

---

## 4. 语言与文档

### 4.1 文档语言
- 所有文档、注释、commit message 使用**中文**
- 专业术语保留英文，首次出现时标注中文释义（如：Device Tree（设备树））
- 代码中的标识符（变量名、函数名等）使用**英文**

### 4.2 文档格式
- 使用 Markdown 格式，文件扩展名 `.md`
- 每个顶层目录应包含 `README.md` 说明该目录用途
- 行宽不超过 120 字符（中文文档可适当放宽）

---

## 5. Shell 脚本规范

Shell 只负责开发环境初始化；公共 CLI、配置、路径与业务编排使用 Python。

### 5.1 基本要求
- 解释器声明：`#!/bin/bash`（明确使用 bash，不用 `#!/bin/sh`）
- 文件权限：可执行脚本必须有 `+x` 权限
- 文件扩展名：可执行脚本使用 `.sh`，被 source 的库文件无扩展名或使用 `.inc`

### 5.2 安全与健壮性
- 脚本开头必须设置：`set -euo pipefail`（构建/编排脚本建议追加 `-x` 输出执行轨迹，即 `set -xeuo pipefail`）
- 被 source 的环境入口必须保持调用者的 Shell 执行选项；初始化子进程可使用 `set -e` 保留失败处理，
  但不得主动启用 xtrace（命令跟踪），正常初始化只输出必要提示，失败诊断仍须可见。
- 临时文件使用 `mktemp`，并通过 `trap` 确保清理
- 路径变量必须用双引号包裹：`"${variable}"`
- 禁止使用 `eval`，除非有充分理由并附注释说明

### 5.3 风格
- 缩进：4 空格（禁止 Tab）
- 函数命名：`snake_case`，如 `build_kernel`、`pack_rootfs`
- 变量命名：
  - 局部变量：`snake_case`，使用 `local` 声明
  - 全局/环境变量：`UPPER_SNAKE_CASE`
- 函数定义使用 `function_name() {` 格式（不用 `function` 关键字）
- 长命令使用 `\` 换行，续行缩进 8 空格

### 5.4 日志与输出
- Shell 脚本层仅负责入口提示，构建过程输出由 Python `BuildOutput` 接管
- 详细输出规范见 §14 输出规范

---

## 6. Python 构建系统规范

Python 是本项目的构建引擎语言；配置内容使用 Jsonnet 描述，求值后以
canonical JSON（规范化 JSON）交给 Python builder。

### 6.1 文件组织
- 配置引擎位于 `builder/config/` 子包（jsonnet.py、registry.py、query.py、loader.py、apps.py、validate.py）
- 构建引擎位于 `builder/` 目录
- 平台策略类位于 `builder/platforms/<vendor>/`（如 `builder/platforms/rockchip/kernel.py`）
- 平台无关 rootfs 基线配置位于 `components/rootfs/config.jsonnet`
- 平台/SoC/板级配置位于 `components/platform/` 和 `components/board/` 下的 `config.jsonnet` 文件
- 分区表转换器位于 `builder/partition/`

### 6.2 配置体系
- 注释约束：每个 `*.jsonnet` 和 `*.libsonnet` 配置源的第一条非空内容 MUST 是中文职责注释，
  明确所属层级或共享范围、适用对象和配置用途；硬件限制、magic value、workaround、
  product/variant 条件原因 MUST 在对应字段旁说明。配置格式迁移 MUST 保留并按新语义
  改写原有有效注释，不得只迁移值而丢弃设计依据
- rootfs 基线：`components/rootfs/config.jsonnet` 声明平台无关的 rootfs 字段，先于硬件配置组合
- rootfs ubuntu-base：`rootfs.url` 必须配套声明可信的 `rootfs.sha256`；下载先写临时文件，
  摘要校验通过后方可原子替换缓存文件
- rootfs 包集合：`rootfs.package_sets` 定义命名包集合，`rootfs.package_set` 选择集合；
  product/variant 条件由 Jsonnet `if` 表达。求值边界将其展开为
  `rootfs.packages`，builder 只消费最终包列表。APT 推荐依赖通过
  `rootfs.install_recommends` 布尔字段控制：全局默认 `false` 并传入
  `--no-install-recommends`，需要完整发行版软件集合的 product MAY 显式设为
  `true`；该字段 MUST 进入 rootfs Phase 1 base cache 哈希。
- rootfs 默认语言：`rootfs.default_locale` 使用
  `{lang: "<locale>", language: "<gettext language list>"}` 声明；共享
  RootfsBuilder MUST 在 overlay 后将其写入 `/etc/locale.conf` 与
  `/etc/default/locale`，值必须是非空单行字符串。未声明时保持发行版默认值。
- rootfs 默认用户身份：`rootfs.default_user` 非空时，RootfsBuilder MUST 优先
  创建该用户并固定为 UID 1000，同时创建同名、GID 1000 的 user private group
  （用户私有组）；任一编号已被其他身份占用时 MUST 构建失败，不得静默改号。
  `rootfs.groups` 中尚不存在的附加组 MUST 创建为 system group（系统组），
  不得占用从 1000 开始的普通用户 GID 范围。
- rootfs 默认图形会话：`rootfs.default_session` 声明 `default_user` 使用的
  session 名；共享 RootfsBuilder MUST 校验对应的 X11 或 Wayland desktop launcher
  存在，并写入 `/var/lib/AccountsService/users/<default_user>`。未声明时保持 display
  manager（显示管理器）的发行版默认行为。
- Ubuntu Desktop 常亮策略：`ubuntu-desktop` package MUST 通过 GSettings 默认值关闭
  GNOME 空闲黑屏、锁屏与自动休眠，并通过 `systemd-sleep.conf` drop-in 禁止系统挂起和
  冬眠；该策略 MUST 只影响显式启用此 package 的 desktop product。
- rootfs 第三方资源声明式安装：
  - `rootfs.extra_firmware`：通过 `{source: {name, subpath}}` 引用顶层
    `sources`，或直接使用统一 `{url, sha256, filename}` 下载 descriptor；
    `files` 元素支持字符串或 `{src, dest}` 做重命名
  - `rootfs.extra_debs`：从 URL 直下不在 Ubuntu 官方源的预编译 deb，必须声明 `sha256` 校验
    ；vendor 合并包与 Ubuntu 拆分包存在已确认的文件冲突时，MAY 显式声明
    `force_overwrite: true`，并通过 `hold_packages` 锁定实际已安装的相关包，防止后续 APT
    升级覆盖 vendor 版本。未声明时 MUST 保持 dpkg 默认的冲突拒绝行为
  - 数组增减使用 Jsonnet 原生 `+` 与 `components/config/lib.libsonnet`
    的 `without`；缓存哈希纳入配置和 source 内容变更
- `components/packages` 中的 `vendor` component MUST 注册为本地 custom package，
  由 flange 的 AppBuilder / DebBuilder 重新打成自有 deb 后通过 rootfs 的统一
  `dpkg` 流程安装；MUST NOT 直接安装其参考的上游发行版 deb。vendor App MAY
  通过 `rootfs/` 目录按目标根文件系统布局递归携带文件与符号链接；需要保留
  安装、升级、卸载语义时，MAY 通过 `maintainer_scripts` 将 App 内的
  `preinst` / `postinst` / `prerm` / `postrm` / `triggers` 映射进 deb
  `control.tar.gz`，脚本路径 MUST 为 App 目录内的相对路径。
- 固定基础组合顺序：rootfs → platform → SoC → board；随后按 board 直接启用的
  `packages` 顺序追加包内可选 `config.jsonnet`（单层、不递归）。组合统一由
  Jsonnet 对象继承、`+:` 和数组表达式完成
- `rootfs.gnome_remote_desktop_login=true` 时，构建 MUST 使用
  `default_user` 及其非空 `users.<name>.password` 生成 root-only 首启凭据；
  目标机 MUST 生成仅服务账号可读的 TLS 私钥与证书，并通过 `grdctl --system`
  配置证书、凭据和 RDP backend；全部成功后 MUST 删除该暂存文件
- SoC 层只声明芯片级事实（架构、工具链、固件协议与硬件能力）；具体显示、存储路由、
  AMP enable 和 rootfs package policy 属于 board/product，MUST NOT 固化在 SoC 层
- 条件配置：使用 Jsonnet `if product == ...` / `if variant == ...`，不得把
  未求值的 product/variant 子树交给 builder
- 配置选择：`flange target select <board>-<product>-<variant>`（或 `lunch`）保存到当前工作区
  `.flange/current_config`；无参数仅在 TTY 进入层级界面，非交互环境要求明确目标。`--target` 仅覆盖本次调用。
- 目标解析统一使用注册表和 `config.query.parse_target`，不得在 CI/Shell 中按连字符重新拆分。
- 配置解析：`workspace.resolve_config(context)` 基于工具根调用配置注册表，返回严格校验的 canonical JSON dict；
  工作区 App 来源由 AppResolver 消费，不向系统配置临时注入路径或执行开关。
- 新增板级支持只需创建 `components/board/<name>/config.jsonnet`，无需修改框架代码

### 6.3 框架与策略分离
- **框架层**（`builder/base.py`）：ComponentBuilder 基类，负责源码生命周期、补丁管理、增量编译
- **策略层**（`builder/platforms/<vendor>/*.py`）：平台子类，实现 `configure()`、`compile()`、`collect()` 方法
- 配置通过求值后的 Python dict 传入（无环境变量契约）
- 新增平台时只需在 `builder/platforms/` 下添加策略子类，MUST NOT 修改框架层代码

当前 rootfs 与 recovery 复用 `builder/rootfs.py` 的公共构建编排，GPT（GUID 分区表）镜像
复用 `builder/image.py`，分区几何统一由 `builder/partition/layout.py` 解析。
上述平台扩展约束是设计目标；现有缓存产物路由和刷写策略仍有集中分派，新增能力时必须检查所有消费边界，
不能只创建一个目录便宣称任意平台已支持。维护落点见[架构指南](docs/build-system-design.md)。

### 6.4 构建与刷写约定
- 构建命令：`flange build [component]`（默认 image；包括 kernel、bootloader、app、
  device-tree-overlay、boot、rootfs、recovery、amp，按配置启用）
- 刷写命令：`flange flash [partition]`（读取 `.build/target/.../flash-config.json`，分区名以 `--list` 为准）
- `plan`、执行、`why` 和缓存共用 TaskPlan；输入包含配置、源码、补丁、配方、环境及上游产物身份。
- 缓存仅认带版本 manifest，并校验全部必需文件树、权限和链接；发布前重新检查输入，旧 `.build_hash` 不再有效。
- 共享下载与可变源码树分离，后者位于 `build_root/work/<target.key>/sources/`；同目标构建持有进程间锁。
- 默认产物目录为工作区 `.build/target/<board>/<product>/<variant>/`；`flange.toml.build_dir` 可覆盖输出根。
- rootfs/recovery 基础缓存按同一 Phase 1 计划寻址；APT、emulator、配方和环境决定快照身份，Phase 2 配置不干扰它。
- rootfs 活树作用域由 `rootfs_storage.py` 管理，不跟随 TMPDIR；该存储配方纳入 Phase 1 指纹。
  退出时先完成 chroot 子挂载清理；若仍有挂载，拒绝递归删除临时树并保留诊断，不发布成功状态。
- ubuntu-base 解包与基础快照保存/恢复显式保留数字 UID/GID、模式位、链接、扩展属性、文件 capability
  （能力属性）和 ACL（访问控制列表）。`snapshot.py` 纳入 Phase 1 配方，归档行为改变时旧快照必须失效。

### 6.5 配置驱动原则
- 新增板级支持时，**只允许创建配置文件**（`components/board/<name>/config.jsonnet`），不得修改框架层代码
- 所有可变信息从 FINAL_CONFIG dict 获取
- 违反此原则说明框架抽象不足，应先重构框架再新增支持

### 6.6 配置边界与维护职责

- 系统配置源是 Jsonnet，`app.yaml` 描述 App，`package.py` 的 `PACKAGE` 描述功能包。
  Package Python 文件是受信任的可执行代码，不能视为纯数据或隔离脚本。
- `builder/config/jsonnet.py` 负责组合求值，`schema.py` 负责闭合结构与严格类型，`validate.py` 负责领域语义；
  `app_spec.py` 将 YAML 转为 dataclass（数据类），`packages.py` 校验 Package 的 component 类型联合。
- 系统、App、Package 拒绝未知字段和隐式类型转换；布尔值不能写成字符串，数组不能写成单字符串。
  动态映射仅用于明确声明的名称到配置结构；所有真实入口执行相同校验，不以 dict 子类身份跳过约束。
- Jsonnet 作者输入不得声明 `packages_meta` / `boot.package_overlay_sources` 等派生字段；这些只由包展开器生成。
  错误须指出字段路径、期望类型和中文纠正说明。重复 YAML 键必须拒绝。
- 未消费的 App `capabilities`、`lib.headers_dir` 已移除；头文件使用构建 install staging、`install` 映射与 include 约定。
  `runtime.executable` 与 `systemd.auto_start` 必须在安装产物及生成维护脚本中兑现。
- 每个新增字段同时说明类型、默认值、所属层、合法组合、消费位置和缓存影响；
  需要运行行为的新字段必须同时验证解析、执行与缓存判定，不能只增加配置示例。

---

## 7. C/C++ 规范

用于内核模块、驱动、系统工具等场景。

### 7.1 风格
- 遵循 **Linux Kernel Coding Style**（缩进 Tab = 8 空格宽度）
- 内核模块严格遵循内核风格
- 用户态工具可适当调整（缩进 4 空格），但同一模块内须一致
- 行宽不超过 100 字符

### 7.2 命名
- 函数/变量：`snake_case`
- 宏/常量：`UPPER_SNAKE_CASE`
- 类型定义（typedef）：`snake_case_t`（仅用于不透明类型，避免滥用）
- 头文件保护：`#ifndef FLANGE_MODULE_NAME_H`

### 7.3 头文件
- 使用 `#pragma once` 或传统 include guard
- 系统头文件在前，项目头文件在后，按字母排序
- 头文件应自包含（self-contained）

### 7.4 内存与资源
- 分配的资源必须有对应的释放路径
- 使用 `goto cleanup` 模式处理错误路径（内核风格）
- 禁止在嵌入式代码中使用不受限的动态内存分配

---

## 8. Python 规范

用于构建工具、脚本辅助等场景。

### 8.1 基本要求
- 最低支持 Python 3.12（见 `pyproject.toml` 的 `requires-python`）
- 解释器声明：`#!/usr/bin/env python3`
- 使用 `pyproject.toml` 管理项目元数据和依赖

### 8.2 风格
- 遵循 PEP 8
- 缩进：4 空格
- 行宽不超过 100 字符
- 使用 type hints（类型注解）
- 函数/变量：`snake_case`
- 类名：`PascalCase`
- 常量：`UPPER_SNAKE_CASE`

---

## 9. 目录结构约定

顶层目录按"代码 / 内容 / 产物"三层划分，每层职责互不交叉：

```
flange/
├── pyproject.toml      # Python 项目配置
├── envsetup.sh         # Python 环境初始化与 lunch 薄包装
├── docker-compose.yml  # Docker 编排配置
├── CLAUDE.md           # AI Agent 行为指引
├── ProjectSpec.md      # 本文档
│
├── builder/            # 【代码层】Python 构建引擎（唯一顶层 Python 包）
│   ├── cli.py          #   Python 公共入口与参数解析
│   ├── commands.py     #   CLI 命令组与工作区服务分派
│   ├── workspace.py    #   工作区、目标、状态与路径
│   ├── graph.py        #   TaskPlan / InputSpec / TaskFingerprint
│   ├── artifacts.py    #   必需产物声明与 manifest
│   ├── engine.py       #   依赖计划、锁、调度与原子发布
│   ├── dev.py          #   App / Package 资源优先 CLI
│   ├── app_spec.py     #   App 描述数据模型与解析
│   ├── app.py          #   系统组件与 AppBuilder 的适配入口
│   ├── app_build.py    #   App 隔离构建、依赖前缀与产物发布
│   ├── app_resolver.py #   来源解析与完整依赖闭包
│   ├── app_model.py    #   AppBuildResult / AppBuildReport
│   ├── package_build.py #  Package 显式 build action 的产物流水线
│   ├── toolchain.py    #   目标 ABI 与构建系统工具变量
│   ├── deploy.py       #   manifest 部署、测试、GDB 与会话记录
│   ├── base.py         #   ComponentBuilder 基类
│   ├── paths.py        #   工具仓库默认锚点与纯路径辅助
│   ├── docker.py       #   Docker 容器执行封装
│   ├── source.py       #   源码仓库管理
│   ├── cache.py        #   按计划与产物完整性判断缓存
│   ├── digest.py       #   文件/目录摘要，包含权限与符号链接
│   ├── locking.py      #   进程间锁与原子写入
│   ├── rootfs_base.py  #   共用 Phase 1 计划与执行
│   ├── rootfs_storage.py # rootfs/recovery 原生活树与安全清理
│   ├── chroot.py       #   ChrootContext（mount/umount 管理）
│   ├── snapshot.py     #   Phase 1 base 快照存取与 LRU 回收
│   ├── lunch_tui.py    #   lunch 的层级目标选择界面
│   ├── flash/          #   刷写系统（构建期与宿主机执行期分离）
│   │   ├── model.py    #     flash-config.json 的 schema（两侧共享）
│   │   ├── plan.py     #     分区映射与 pre_flash 推导（构建期）
│   │   ├── generate.py #     flash-config.json 生成（构建期）
│   │   ├── spi.py      #     spi.img 合成（构建期）
│   │   ├── strategy.py #     平台刷写策略（宿主机）
│   │   └── execute.py  #     刷写执行与 CLI 入口（宿主机）
│   ├── config/         #   配置子系统
│   │   ├── jsonnet.py  #     Jsonnet 求值与固定层级组合
│   │   ├── registry.py #     Jsonnet 配置注册表
│   │   ├── query.py    #     target 解析与层级目标树（给 CLI lunch 用）
│   │   ├── schema.py   #     系统/复用配置结构与严格类型
│   │   ├── validate.py #     字段组合与平台语义
│   │   └── summary.py  #     目标配置摘要表
│   ├── partition/      #   分区表系统
│   │   ├── __init__.py #     中间格式（PartitionTable/Partition）
│   │   ├── layout.py   #     PartitionLayout：分区几何的单一事实源
│   │   ├── size.py     #     分区大小解析（扇区数 / 容量后缀）
│   │   └── rockchip.py #     Rockchip parameter.txt 转换
│   └── platforms/      #   平台构建策略（代码）
│       └── rockchip/
│           ├── kernel.py      # RockchipKernelBuilder
│           ├── bootloader.py  # RockchipBootloaderBuilder
│           ├── rootfs.py      # RockchipRootfsBuilder
│           └── image.py       # RockchipImageBuilder
│
├── components/         # 【内容层】仓库携带的原料（版本控制跟踪）
│   ├── config/         #   Jsonnet 公共函数与平台共享数据
│   ├── platform/       #   平台/SoC 配置（固定组合的中间两层）+ patches
│   │   └── rockchip/
│   │       ├── config.jsonnet #  Rockchip 平台配置
│   │       ├── patches/    #     平台级补丁（kernel/bootloader）
│   │       └── rk3566/
│   │           └── config.jsonnet # RK3566 SoC 配置
│   ├── board/          #   板级配置（基础组合第四层）+ 板级数据
│   │   └── <board-name>/
│   │       ├── config.jsonnet #  板级配置（含 products/variants 声明）
│   │       ├── overlay/    #     文件系统覆盖层
│   │       └── patches/    #     板级补丁
│   ├── app/            #   App 定义
│   ├── packages/       #   component package（package.py，可选 config.jsonnet）
│   └── rootfs/         #   rootfs 基线配置与 overlay
│
├── docker/             # Docker 构建环境定义
│   ├── Dockerfile
│   └── entrypoint.sh
├── tests/              # 测试套件
├── openspec/           # 工程规格管理
├── docs/               # 设计文档
│
├── .build/             # 【产物层】运行时派生物（git ignored）
│   ├── cache/          #   apt / rootfs-base / 工具缓存
│   ├── sources/        #   共享仓库与下载
│   ├── locks/          #   目标与共享资源锁
│   ├── work/           #   按目标隔离的源码、组件与 App 中间目录
│   └── target/         #   构建产物
│       └── <board>/<product>/<variant>/
└── .flange/            # 运行时状态（git ignored）
```

> 上述目录树仅示意核心模块。`builder/` 下另有 app/deb 打包、deploy、output、
> recovery、overlays、scaffold 等支撑模块；各 `builder/platforms/<vendor>/` 除
> kernel/bootloader/rootfs/image 外还可有 boot.py、recovery.py。完整列表执行
> `rg --files builder` 查看。

分层契约：
- **代码层** 仅放可 import 的 Python 模块；`builder/` 是项目唯一顶层包。
- **内容层** 仅放仓库携带的原料；不得出现派生物。平台的"数据部分"（patches/config）在 `components/platform/`，"逻辑部分"（builder 子类）在 `builder/platforms/`。
- **产物层** 聚合所有运行时生成物；可 `rm -rf .build/` 触发完整重建。
- 运行期路径 MUST 来自显式 WorkspaceContext；`builder.paths` 只提供工具默认根与纯路径辅助。
  不得在下层通过 cwd、全局 BUILD_ROOT 或旧顶层目录重新推断工作区。

### 9.1 App 来源查找优先级

所有入口通过 AppResolver 解析，显式路径相对调用目录，`build.deps` 中的路径相对声明 App。
名称查找依次为工作区 `[apps]`、相对基准下的真实目录、工作区 `app_dirs`，再进入工具来源注册表。
多个 `app_dirs` 命中同名 App 必须显式注册消歧；已命中但缺少 app.yaml 不得静默回退。

工具来源注册表依次查找：

1. `<tool_root>/components/app/<name>/`。
2. canonical config 的 `external_apps[<name>]`：`local_path` 与 `git` 必须互斥。
3. config 的 `external_app_dirs`，按声明顺序查找 `<dir>/<name>/app.yaml`。

系统 Jsonnet 中的相对外部路径相对工具根归一化；工作区的 `[apps]` / `app_dirs` 相对 `flange.toml`。
工具内容、工作区状态和用户源码各有明确所有者；同名不同源码不能进入同一依赖闭包。
`flange app list` 展示来源；`flange app plan <name-or-path>` 查看实际解析结果。

---

## 10. Git 规范

### 10.1 分支策略
- `main`：稳定分支，始终可构建
- `dev/*`：开发分支，按功能命名，如 `dev/kernel-build`
- `fix/*`：修复分支，如 `fix/rootfs-permission`
- `release/*`：发布分支，如 `release/v1.0`

### 10.2 Commit Message
格式：
```
<类型>(<范围>): <简述>

<详细说明（可选）>
```

类型：
| 类型 | 说明 |
|------|------|
| `feat` | 新功能 |
| `fix` | 缺陷修复 |
| `docs` | 文档变更 |
| `refactor` | 重构（不影响功能） |
| `build` | 构建系统变更 |
| `ci` | CI/CD 配置变更 |
| `test` | 测试相关 |
| `chore` | 杂项（依赖更新等） |

范围示例：`kernel`、`rootfs`、`board`、`scripts`

示例：
```
feat(kernel): 添加内核编译支持

实现基于 ubuntu-base 的内核交叉编译流程，
支持自定义 defconfig 和增量补丁。
```

### 10.3 提交粒度
- 每个 commit 只包含**一个功能或一个目的**的改动，不同功能的变更必须分开提交
- 例如「添加新板级支持」和「切换 U-Boot 分支」是两个独立功能，应分为两个 commit
- 即使两项改动发生在同一次开发中，也必须拆分为独立 commit 以保持历史清晰可追溯

### 10.4 .gitignore
- `.build/` 整棵派生物树必须被忽略（含 cache/sources/target）；`output/`、`.flange/` 亦必须忽略；根目录 `target` 软链接不提交
- 编译产物、临时文件不得入库
- 大文件（>1MB）使用 Git LFS

---

## 11. 构建系统约定

### 11.1 Python 构建引擎
- Python 是项目的构建引擎语言，所有构建/刷写操作通过 `flange` 命令执行
- 组件间依赖由 `builder/engine.py` 的依赖图自动推断，变更后基于内容哈希仅增量重建
- 通过 `flange target select` 或 `lunch` 选择目标，状态保存在当前工作区 `.flange/current_config`
- 计划、执行、缓存与解释必须使用同一输入声明，所有必需产物完整且摘要吻合才允许命中

### 11.2 Docker 构建环境
- 所有编译构建操作**必须在 Docker 容器内**完成
- Dockerfile 基于 Ubuntu 24.04 LTS，安装交叉编译工具链及构建依赖；另装 kernel.org crosstool gcc-10.5 到 `/opt/aarch64-gcc10` 作为 AArch64 u-boot/kernel 默认工具链，并安装 Arm GNU Toolchain 10.3-2021.07 到 `/opt/arm-linux-gcc10` 供 RK3506B ARM32 u-boot/kernel 使用（见 §11.3）
- 工具根、工作区、输出根和外部源码通过同绝对路径 volume mount 映射到容器内
- 源码仓库目录 `.build/sources/` 和 APT 缓存 `.build/cache/apt/` 通过 volume 持久化
- rootfs/recovery 活树使用容器原生磁盘，不在宿主共享卷解包；需要同时为 Docker 原生磁盘和宿主产物目录预留空间。
- 宿主机 `~/.ssh` 以只读方式挂载，通过 entrypoint 脚本修正权限
- 系统镜像、rootfs 等需要 mount（挂载）的调用必须显式启用容器特权模式；普通 App、Package 编译默认非特权
- 特权模式通过 Compose（容器编排）服务的 `privileged` 属性配置，默认关闭；禁止将 `docker run` 的
  `--privileged` 参数传给 `docker compose run`。DockerRunner 每次在子进程环境中显式设置
  `FLANGE_BUILD_PRIVILEGED=true/false`，不得继承宿主同名变量的权限选择或修改宿主进程环境
- `envsetup.sh` 自动准备宿主 Python 虚拟环境。Jsonnet 依赖缺少可用 wheel 时安装阶段
  需要宿主 C++ 工具；这与目标代码统一在 Docker 编译的约定不同，不应宣称宿主零依赖

### 11.3 交叉编译
- **u-boot / kernel 构建**按目标架构使用容器内独立固定的 gcc-10 工具链。AArch64 默认使用 kernel.org crosstool **gcc-10.5**（前缀 `/opt/aarch64-gcc10/bin/aarch64-linux-`），由 `builder/base.py` 的 `ComponentBuilder.CROSS` 声明；RK3506B ARM32 通过 SoC 配置覆盖为 ATK SDK 同款 Arm GNU Toolchain **gcc-10.3.1**（前缀 `/opt/arm-linux-gcc10/bin/arm-none-linux-gnueabihf-`）。不得把 Ubuntu 24.04 的系统 gcc-13 用于这些老 Rockchip 低层产物；RK3576 的实机根因详见 openspec `selfbuild-rk3576-spi-image`，RK3506B 的工具链约束详见 openspec `add-rk3506b-atk-rk3506b`
- **app / deb 组件构建**（`builder/app_build.py`、`builder/toolchain.py`）使用 Docker 系统包交叉编译器（`gcc-aarch64-linux-gnu` / `gcc-arm-linux-gnueabihf`）
- 平台策略类（builder/platforms/）直接调用交叉编译器，无需额外工具链注册机制
- 板级配置通过 `config.jsonnet` 声明（rootfs/platform/SoC/board 固定组合）

### 11.4 输出管理
- 构建产物发布到工作区 `build_root/target/<board>/<product>/<variant>/`（git ignored）；路径以 `flange status` 为准
- 内核产出按 FINAL_CONFIG 路由：ARM64/extlinux 通常为 `Image`、精确目标 DTB、modules；
  ARM32/vendor FIT 通常为 `zImage`、精确目标 DTB、modules 与 FIT `boot.img`
- 内核构建支持 out-of-tree 模块：通过 `kernel.oot_modules` 配置声明，在 `make modules` 后独立编译并统一安装到 rootfs；OOT 编译入口若是独立 git 仓库（如 vendor WiFi/BT 包），通过 `kernel.oot_sources` 声明源（每次 ensure 后路径作为 `{<name>_src}` 模板变量注入），仓库 git HEAD 入 kernel hash；安装末尾跑 `depmod -b` 重建 modules.{dep,alias,symbols}+`.bin` 索引，开机 PCI/USB hotplug 才能自动 load
- `flash-config.json` 由 `builder/flash/generate.py` 在构建期生成，宿主机侧由 `builder/flash/execute.py` 读取执行
- 分区配置由 `builder/partition/` 从 config 自动转换
- 块设备 GPT image 输出 `raw.img`；SPI NAND MUST 输出 parameter 与具名刷写 manifest，
  MUST NOT 生成或整片写入无法表达 OOB/ECC/坏块的 `raw.img`
- 使用 `flange clean` 清理当前配置的构建产物

---

## 12. 部署与刷写约定

### 12.1 刷写环境
- 刷写操作在**宿主机**上执行（非 Docker 容器内）
- 通过 USB 连接目标设备，使用平台对应的刷写工具
- 刷写脚本应检测设备连接状态，未连接时给出明确提示

### 12.2 组件级刷写
- 支持单独刷写各组件到设备的特定分区
- 刷写通过 `flange flash [partition]` 执行（如清单包含该分区时使用 `flange flash boot`）
- 全量刷写：`flange flash`（重写分区表 + 所有分区）
- `flash-config.json` 由构建引擎生成，声明各分区的镜像、偏移、大小与保护属性
- 任何持久写入前必须完成本地产物 preflight；parameter 与 flash config 应使用摘要及
  name/offset/size 交叉校验。支持身份读取的平台还必须拒绝多设备，并核对 SoC/存储介质

### 12.3 平台适配
- 每块板子的 `config.jsonnet` 声明所属 platform/SoC；平台层声明刷写工具
- 刷写侧根据 FINAL_CONFIG 中的 `flash_tool` 字段选择刷写工具
- 平台特有的刷写逻辑位于 `builder/flash/strategy.py`（宿主机执行期），分区映射与 pre_flash 推导位于 `builder/flash/plan.py`（构建期）

---

## 13. 安全规范

- 构建脚本不得包含硬编码的密钥、密码或 token
- 敏感信息通过环境变量或独立的配置文件（git ignored）传入
- 下载外部资源时必须校验 hash（SHA256）
- 禁止在构建脚本中使用 `curl | bash` 模式

---

## 14. 输出规范

构建输出首先回答开发者的问题：正在构建哪个目标、当前执行什么动作、是否仍在运行、最终结果是什么、
失败后在哪里查看证据以及怎样继续。终端呈现和日志记录由一次构建的单一输出服务管理。

公共 CLI 支持 `--json`、`--no-color`、`--no-interaction`、`--target` 和 `-C/--workspace`。
机器输出带 `schema_version`，过程与诊断走 stderr；非交互场景不弹菜单。
退出码为 0 成功、1 操作失败、2 参数/配置错误、130 取消；App/test 保留程序退出码，测试超时为 124。
Shell 与 CI 不解析中文状态文案。完整用户旅程与本轮实际日志评审见 [CLI 评审](docs/cli-experience-review.md)。

### 14.1 输出层级

| 层级 | 内容 | 显示条件 |
|------|------|---------|
| L1 目标与结果 | 当前目标、本次请求、阶段结果和最终结论 | 始终保留；QUIET 使用紧凑摘要 |
| L2 当前动作 | 实际步骤、源码准备、缓存决策和关键事件 | NORMAL、VERBOSE 显示 |
| L3 工具原文 | Git、make、apt 和其他子进程的输出 | 全部写入日志；VERBOSE 展开，失败时提取相关上下文 |

NORMAL 使用短文本与缩进表达目标、阶段、动作和结果，不绘制全宽横线、错误框或耗时占比条。
资源名称足以定位时不显示内部 resource_id 摘要。正文布局宽度上限约 96 列；
不能为了对齐把耗时放到宽终端的最右边。日志路径、异常原文和重试命令应完整、可复制。

### 14.2 输出级别

`flange build`、`flange app build`、`flange package build` 使用相同的互斥选项：

| CLI 标志 | 行为 |
|---------|------|
| 默认 NORMAL | 目标、阶段、当前动作和紧凑结果；工具原文仅在失败时提取上下文 |
| `-v` / `--verbose` | 展开完整工具原文，结束时可显示简洁组件状态与耗时记录 |
| `-q` / `--quiet` | 保留摘要、必要失败上下文和日志位置 |

所有级别都保留完整日志。输出级别是执行选项，不写入配置，不改变构建输入指纹或缓存结论。
工具 warning 原文仅在 VERBOSE 展示，始终写入日志。

### 14.3 语义颜色

公共 CLI、构建、刷写和目标选择共用 `builder/term.py` 的语义角色与样式接口。
调用方根据结构化结果选择角色，不从整段文字中的关键词猜测状态；颜色仅辅助定位，文字与符号必须保留。

| 语义 | 样式 | 典型内容 |
|------|------|---------|
| 标题、正常需构建、进行中 | 蓝色，标题加粗 | 阶段、需构建、正在编译 |
| 成功、可复用 | 绿色 | 完成、检查通过、缓存复用 |
| 警告、受阻待准备、取消 | 黄色 | 缺少前置条件、用户取消 |
| 错误、失败 | 红色加粗 | 失败、无效配置、根因 |
| 路径、命令 | 青色 | 日志位置、下一步命令 |
| 正文 | 终端默认前景 | 名称、字段值、说明 |
| 次要说明 | 默认前景并降低亮度 | 耗时、辅助标签、工具原文 |

首次构建或输入变化导致的缓存未命中是正常“需构建”，不能显示成警告或失败。
成功和复用必须来自执行报告与产物验证，目录存在不能单独作为依据。

按实际输出流动态判断终端能力；stdout 与 stderr 分别检测。非 TTY、`TERM=dumb`、
存在 `NO_COLOR`（包括空值）或指定 `--no-color` 时，普通命令禁用颜色、动画和光标重绘。
交互目标菜单禁色后仍保留导航所需绘制与焦点反显；非 TTY 不进入菜单。
JSON 使用原始结果，stdout 只有一份结果文档；其 stderr 过程与持久化日志也不含 ANSI（终端控制序列）。
正文不强制白色或固定背景色。

### 14.4 当前动作与长任务

有能力的 NORMAL 交互终端最多显示一条实时活动行，内容为当前阶段、动作和实际已耗时。
活动行可按窄终端宽度缩短，关键结果与完整路径仍要落成普通文本。
源码准备与编译子进程不得同时直写终端，避免 Git 回车进度插进活动行。

NORMAL/VERBOSE 在非 TTY、无颜色等无法重绘的场景，步骤开始时立即输出动作文本，结束时再给出结果；
QUIET 保留最终摘要。
不能等一个耗时 45 分钟的编译结束后才第一次显示“编译内核”。
真实阶段顺序或已完成数量可以展示，但不换算成百分比；组件工作量不同，数量不能预测时间进度。
不输出未经测量的 ETA（预计完成时间），缓存跳过不虚构执行耗时。
即时状态只说明当前事实，不开启计时，也不自动确认一次动作成功。
步骤结果与耗时必须对应实际执行范围，不能把后续编译耗时归到“源码已就绪”等通知上。
计时使用 monotonic（单调时钟），避免系统时间调整导致负数或跳变；嵌套步骤各自保留真实执行范围。

### 14.5 构建结果

结束时停止并清除活动行，再输出一次紧凑结论：结果、阶段完成/复用等真实计数、实际总耗时和日志位置。
阶段计数不等于重新编译的 App 数量；App 自身的缓存复用由逐项状态与构建报告说明。
NORMAL 不重复完整阶段耗时表；VERBOSE 可列出组件、状态和耗时，不绘制条形图。
成功编译、缓存复用、配置关闭、执行失败和用户取消必须区分，取消不能标为成功。

### 14.6 日志持久化

- 全量状态与工具原文写入 `WorkspaceContext.target_dir/build.log`，默认路径为工作区的
  `.build/target/<board>/<product>/<variant>/build.log`。
- 系统、App、Package 构建在取得目标锁后初始化日志，先轮转旧日志再执行；默认保留 3 份历史，
  `FLANGE_LOG_KEEP` 控制保留数量。等待锁的请求不得提前轮转正在使用的日志。
- 日志流式记录命令与上下文，移除 ANSI 和原地刷新残留，保留实际时间信息。
- 成功、失败和取消均关闭日志，终端结果只提供一次完整日志位置。

### 14.7 错误呈现与继续工作

失败诊断集中在一个区域：失败阶段/动作、真实原因、相关命令上下文、日志位置和适用的恢复提示。
匹配到 `error:`、`undefined reference`、`E:`、`dpkg: error` 等错误时优先展示相关行；
无匹配时使用该失败命令的有限尾部。早先成功命令的输出不能冒充后续配置错误的原因。
失败命令的上下文绑定到实际异常，后续 rm、umount 等清理命令不能覆盖它；
已被业务捕获并恢复的失败不能污染新的无关异常。清理另有错误时附加诊断并保留主操作异常，
只有清理自身失败时也必须报告失败。
完整 traceback 写入日志，终端不用错误框或多次复制异常。

内层已经呈现的失败由 Docker 与外层 CLI 传播状态，不再重复同一原因，
也不能把笼统的“Docker 命令失败”追加成新的根因。容器未启动或未呈现过的外层故障仍需独立诊断。
JSON 保留单一结构化结果和真实失败状态。

恢复提示以本次请求为准：默认 image 构建提示修复后 `flange build`，指定 kernel 则保留 `flange build kernel`；
适用时保留工作区和临时目标信息。先修复根因再重试，不默认建议 `clean` 或强制重建。
重试时仍以输入和实际产物校验决定复用，不能向用户保证所有已完成阶段一定跳过。

### 14.8 Python 输出接口

- 构建模块通过 `builder/output.py` 的 `BuildOutput` 输出状态，禁止在已建立的构建管线中直接 `print()`
  或 `logging.info()` 竞争终端。
- 系统构建由 `BuildEngine`，独立资源构建由 `development_output.run_logged` 管理输出生命周期；
  实例注入构建器、Docker 和源码/子进程执行通道。
- 子进程负责提供原文，BuildOutput 负责日志、过滤、计时和终端绘制；宿主转发内层已格式化结果，不另建竞争状态行。
- `status(msg)` 是即时信息；`step(label)` 上下文管理器或 `spinner_start` / `spinner_stop`
  标明实际步骤的开始和结束，只有这些明确边界才输出步骤结果与耗时。
- `BuildOutput` 的 `retry_command` 可携带本次工作区、目标和资源请求；恢复提示只展示命令，不自动执行。
- 进程通道在失败时调用 `command_failed(error)` 保存异常所属命令的诊断；
  `command_start` 仍为下一条命令建立独立活动缓冲，不能使用全局“第一条失败”替代异常归属。
- 颜色通过 `Role` 与 `style(text, role, *, stream=None)` 表达，传递实际输出流，不另行维护调色板。

---

## 15. 规范执行

- 本规范随项目演进持续更新
- 对规范的修改需通过 OpenSpec 变更流程提案
- AI Agent 在生成代码时必须遵循本规范
- Code Review 时应检查是否符合本规范

### 15.1 当前文档与历史记录

- [README](README.md) 提供公开入口和任务分流；[入门指南](docs/first-steps.md)解释必要概念，
  提供无需设备的第一次成功与后续学习路径；[开发指南](docs/development-guide.md)提供从 clone 到构建、
  刷写、App 开发、验证与调试的完整操作参考。
- [维护指南](docs/maintenance-guide.md)说明如何定位代码、复现、验证和提交；
  [扩展指南](docs/extension-guide.md)说明 App、产品、Package、板卡与平台的扩展落点。
- 教程应明确运行目录、前置条件、预期结果与下一步，区分计划、实际编译和设备验收。
  图示应有文字解释，主要导航使用 GitHub 可直接访问的 Markdown 链接；Wiki 核心概念指向当前参考，
  不能重复维护已被替代的命令和路径模型。
- [架构指南](docs/build-system-design.md) 描述当前模块职责，本规格规定约束，
  `openspec/specs/` 记录能力契约；新增或改变用户可见行为必须在同一变更中同步相关文档。
- 历史设计、实验记录与路线图保留当时事实，必须标识历史范围；新的目标设计不能写成当前实现。
- 代码与规范矛盾时记录缺陷或通过 OpenSpec 修正规范，不能靠删除失败检查来宣称一致。
- README 命令、配置样例、路径链接、支持矩阵与实际 CLI / schema / 注册表应交叉验证；
  当前 pytest 和 OpenSpec 语法校验尚不能自动证明全部文档语义同步。

### 15.2 开源许可

flange 自有代码与文档采用根目录 [Apache License 2.0](LICENSE)。第三方源码、固件、工具、
补丁和生成镜像内的软件包保留各自许可，详见[许可说明](docs/licensing.md)。
标准许可证原文保持原语言；不能用根目录许可覆盖已有第三方权利声明。
