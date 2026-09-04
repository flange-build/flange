# ProjectSpec — flange 项目规格

本文档是 flange 项目的权威规格文档，涵盖项目目标、架构设计、编码规范、开发规范与维护规范。所有贡献者（人类与 AI Agent）均须遵守。

---

## 1. 项目目标

flange 是一个嵌入式 Linux 系统构建框架，基于 ubuntu-base 构建，定位类似 Buildroot / Yocto 但更快速、更可预测。

### 1.1 核心目标
1. 提供内核快速验证通道
2. 提供文件系统快速验证通道
3. 提供全系统级别快速验证通道
4. 提供产品级烧录镜像输出，支持 UFS、eMMC、SPI、SD 卡等多种存储介质

### 1.2 核心优势
- 比 Buildroot / Yocto 支持更可靠、可预期的组件配置
- 更快速的编译构建速度
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

- **构建环境**：所有编译、打包操作在 Docker 容器内完成，确保环境一致性和可复现性
- **部署环境**：镜像刷写在宿主机执行，通过 USB 连接目标设备
- `.build/target/` 目录作为容器与宿主机之间的产物桥梁（通过 volume mount；根目录 `target` 软链接直达）

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

Python 构建引擎 (builder/engine.py) 管理组件依赖图，基于内容哈希实现增量构建。产物收集到 .build/target/<board>/<product>/<variant>/（可经根目录软链接 target 访问）。

| 组件 | 构建命令 | 刷写命令 |
|------|---------|---------|
| Bootloader | `flange build bootloader` | `flange flash bootloader` |
| Kernel | `flange build kernel` | `flange flash kernel` |
| Rootfs | `flange build rootfs` | `flange flash rootfs` |
| Recovery | `flange build recovery` | `flange flash recovery` 或 USB ADB 在线写 |
| 全量镜像 | `flange build` | `flange flash` |

- 组件构建：在 Docker 容器内执行，构建引擎自动推断组件间依赖并基于内容哈希决定增量构建范围
- 产物收集：构建完成后自动收集到 `.build/target/<board>/<product>/<variant>/`（根目录 `target` 软链接直达）
- 组件刷写：在宿主机执行，读取构建期生成的 `flash-config.json` 并按平台策略调用刷写工具
- 全量刷写：重写设备全部分区（分区表 + 所有组件镜像）

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
  禁止依赖 `adb exec:` service 或 `shell:v2` protocol —— flange 选用的
  adbd（android-tools-4.2.2）不支持这两个 service
- **安全策略**：bootloader/raw 与 recovery 自身默认 protected；强制写入
  需要 `--force` 双重确认（host 输入 `YES` + device 端要求 `--sha256`）
- **不属于范围**：OTA / A/B 切换 / 网络烧录 / recovery 自升级

详细用户文档与排障：[`docs/recovery.md`](docs/recovery.md)。

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

Shell 脚本是构建系统的核心语言。

### 5.1 基本要求
- 解释器声明：`#!/bin/bash`（明确使用 bash，不用 `#!/bin/sh`）
- 文件权限：可执行脚本必须有 `+x` 权限
- 文件扩展名：可执行脚本使用 `.sh`，被 source 的库文件无扩展名或使用 `.inc`

### 5.2 安全与健壮性
- 脚本开头必须设置：`set -euo pipefail`（构建/编排脚本建议追加 `-x` 输出执行轨迹，即 `set -xeuo pipefail`）
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
- 配置选择：`lunch <board>-<product>-<variant>` 选择配置，持久化到 `.flange/current_config`；
  无参数时进入层级选择界面（平台 → SoC → 板 → product → variant），末级目标展示其配置表，
  非 TTY 环境回退编号列表
- 配置解析：`resolve_config(board, product, variant)` 返回已校验的 canonical JSON dict
- 新增板级支持只需创建 `components/board/<name>/config.jsonnet`，无需修改框架代码

### 6.3 框架与策略分离
- **框架层**（`builder/base.py`）：ComponentBuilder 基类，负责源码生命周期、补丁管理、增量编译
- **策略层**（`builder/platforms/<vendor>/*.py`）：平台子类，实现 `configure()`、`compile()`、`collect()` 方法
- 配置通过求值后的 Python dict 传入（无环境变量契约）
- 新增平台时只需在 `builder/platforms/` 下添加策略子类，MUST NOT 修改框架层代码

### 6.4 构建与刷写约定
- 构建命令：`flange build [component]`（component 可选：kernel、bootloader、rootfs，默认 image）
- 刷写命令：`flange flash [component]`（读取 `.build/target/.../flash-config.json`）
- 增量构建：基于内容哈希（config + source commit + patches），由 `builder/cache.py` 管理
- 产物目录：`.build/target/<board>/<product>/<variant>/`（根目录 `target` 软链接指向此）

### 6.5 配置驱动原则
- 新增板级支持时，**只允许创建配置文件**（`components/board/<name>/config.jsonnet`），不得修改框架层代码
- 所有可变信息从 FINAL_CONFIG dict 获取
- 违反此原则说明框架抽象不足，应先重构框架再新增支持

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
├── envsetup.sh         # CLI 入口（source 加载，自动创建 target 软链接）
├── docker-compose.yml  # Docker 编排配置
├── CLAUDE.md           # AI Agent 行为指引
├── ProjectSpec.md      # 本文档
│
├── builder/            # 【代码层】Python 构建引擎（唯一顶层 Python 包）
│   ├── engine.py       #   依赖图 + 调度
│   ├── base.py         #   ComponentBuilder 基类
│   ├── paths.py        #   PROJECT_ROOT/COMPONENTS_ROOT/BUILD_ROOT 锚点
│   ├── docker.py       #   Docker 容器执行封装
│   ├── source.py       #   源码仓库管理
│   ├── cache.py        #   增量构建缓存（内容哈希）
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
│   ├── board/          #   板级配置（第三层）+ 板级数据
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
│   ├── cache/          #   工具缓存（apt 等）
│   ├── sources/        #   源码仓库 clone/下载
│   └── target/         #   构建产物
│       └── <board>/<product>/<variant>/
├── target -> .build/target  # envsetup.sh 创建的便捷软链接（git ignored）
└── .flange/            # 运行时状态（git ignored）
```

> 上述目录树仅示意核心模块。`builder/` 下另有 app/deb 打包、deploy、output、
> recovery、overlays、scaffold 等支撑模块；各 `builder/platforms/<vendor>/` 除
> kernel/bootloader/rootfs/image 外还可有 boot.py、recovery.py。完整列表执行
> `find builder -name '*.py'` 查看。

分层契约：
- **代码层** 仅放可 import 的 Python 模块；`builder/` 是项目唯一顶层包。
- **内容层** 仅放仓库携带的原料；不得出现派生物。平台的"数据部分"（patches/config）在 `components/platform/`，"逻辑部分"（builder 子类）在 `builder/platforms/`。
- **产物层** 聚合所有运行时生成物；可 `rm -rf .build/` 触发完整重建。
- 跨层路径解析 MUST 通过 `builder.paths` 暴露的 `COMPONENTS_ROOT`/`BUILD_ROOT` 等锚点拼接，不得直接使用旧顶层名字面量。

### 9.1 App 来源查找优先级

App 源可来自三个层级，构建系统按下述顺序查找，任一命中即终止（不回退）：

1. **本地层** — `<project_root>/components/app/<name>/`，始终扫描，不受配置影响
2. **external_apps** — FINAL_CONFIG 中 `external_apps[<name>]` 显式注册：
   - `local_path` 分支：指向宿主机任意目录，不触发 git
   - `git` 分支：由 `SourceManager` 克隆到 `.build/sources/apps/<name>/`
   - 两分支 MUST 互斥声明；同时存在或均不存在时配置解析阶段立即报错
3. **external_app_dirs** — FINAL_CONFIG 顶层 `list[str]`，每项是一个父目录；按顺序检查 `<dir>/<name>/app.yaml`，首个命中即采用

`local_path` 与 `external_app_dirs[*]` 均支持 `~` 展开，相对路径相对 **project_root** 解析，
并在配置加载时统一 resolve 为绝对路径存入 FINAL_CONFIG（详见 `builder/config/apps.py`）。

`flange list apps` 遍历全部三层并为每行加来源标签 `[local]` / `[external:local]` /
`[external:git]` / `[dir:<path>]`；同名多来源时以优先级最高者为主来源，其它来源以
`(also found in: ...)` 形式在次行展示。

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
- 通过 `lunch <board>-<product>-<variant>` 选择配置，状态持久化到 `.flange/current_config`
- 增量构建基于内容哈希（config + source commit + patches），无需全量重建

### 11.2 Docker 构建环境
- 所有编译构建操作**必须在 Docker 容器内**完成
- Dockerfile 基于 Ubuntu 24.04 LTS，安装交叉编译工具链及构建依赖；另装 kernel.org crosstool gcc-10.5 到 `/opt/aarch64-gcc10` 作为 AArch64 u-boot/kernel 默认工具链，并安装 Arm GNU Toolchain 10.3-2021.07 到 `/opt/arm-linux-gcc10` 供 RK3506B ARM32 u-boot/kernel 使用（见 §11.3）
- 项目根目录通过 volume mount 映射到容器内
- 源码仓库目录 `.build/sources/` 和 APT 缓存 `.build/cache/apt/` 通过 volume 持久化
- 宿主机 `~/.ssh` 以只读方式挂载，通过 entrypoint 脚本修正权限

### 11.3 交叉编译
- **u-boot / kernel 构建**按目标架构使用容器内独立固定的 gcc-10 工具链。AArch64 默认使用 kernel.org crosstool **gcc-10.5**（前缀 `/opt/aarch64-gcc10/bin/aarch64-linux-`），由 `builder/base.py` 的 `ComponentBuilder.CROSS` 声明；RK3506B ARM32 通过 SoC 配置覆盖为 ATK SDK 同款 Arm GNU Toolchain **gcc-10.3.1**（前缀 `/opt/arm-linux-gcc10/bin/arm-none-linux-gnueabihf-`）。不得把 Ubuntu 24.04 的系统 gcc-13 用于这些老 Rockchip 低层产物；RK3576 的实机根因详见 openspec `selfbuild-rk3576-spi-image`，RK3506B 的工具链约束详见 openspec `add-rk3506b-atk-rk3506b`
- **app / deb 组件构建**（`builder/app.py`）仍用 Docker 系统包交叉编译器（`gcc-aarch64-linux-gnu` / `gcc-arm-linux-gnueabihf`）
- 平台策略类（builder/platforms/）直接调用交叉编译器，无需额外工具链注册机制
- 板级配置通过 `config.jsonnet` 声明（rootfs/platform/SoC/board 固定组合）

### 11.4 输出管理
- 构建产物收集到 `.build/target/<board>/<product>/<variant>/`（git ignored，根目录 `target` 软链接直达）
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
- 刷写通过 `flange flash [component]` 执行（如 `flange flash kernel`）
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

构建系统的终端输出和日志持久化遵循本节规范。

### 14.1 输出层级

| 层级 | 内容 | 显示条件 |
|------|------|---------|
| L1 阶段标题 | 组件名 + 状态标记（`▸`/`✓`/`✗`/`⊘`） | 始终显示 |
| L2 状态行 | 阶段进度、缓存决策、关键事件 | NORMAL 和 VERBOSE 显示 |
| L3 工具输出 | make/git/apt 等外部命令原始输出 | 仅 VERBOSE 全量显示；NORMAL 仅在失败时显示错误上下文 |

### 14.2 Verbose 级别

| CLI 标志 | 行为 |
|---------|------|
| （默认） | L1 + L2 + L3 仅错误上下文 |
| `-v` | L1 + L2 + L3 全量（灰色 `│` 前缀） |
| `-q` | L1 仅摘要行 |

### 14.3 颜色编码

| 元素 | 颜色 | ANSI 码 | 符号 |
|------|------|---------|------|
| 阶段标题 | 蓝色加粗 | `\033[1;34m` | `▸` |
| 成功状态 | 绿色 | `\033[0;32m` | `✓` |
| 警告信息 | 黄色 | `\033[1;33m` | `⚠` |
| 错误信息 | 红色加粗 | `\033[1;31m` | `✗` |
| 跳过状态 | 灰色 | `\033[0;90m` | `⊘` |
| 工具输出 | 暗灰 | `\033[0;90m` | `│` |
| 错误框线 | 红色 | `\033[0;31m` | `┄` |

非 TTY 环境（管道/重定向/CI）自动禁用颜色和 Spinner。

### 14.4 Spinner

编译等长时间操作进行中显示 braille 旋转动画 + 实时计时器：
- 字符集：`⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏`
- 格式：`⠹ 编译内核...  38s`（`\r` 原地刷新）
- 完成后替换为 `✓ 编译完成  42.3s`

### 14.5 构建摘要

每次构建结束（成功或失败）打印摘要：
- 分隔线 + 成功/失败状态 + 总耗时
- 各组件状态表：名称、状态（构建/跳过/失败）、耗时、耗时占比条形图
- 日志文件路径

### 14.6 日志持久化

- 全量构建输出（L1 + L2 + L3）写入 `.build/target/<board>/<product>/<variant>/build.log`
- 每次构建覆盖写入（非追加），避免日志无限增长
- 日志文件不含 ANSI 颜色码
- 摘要末尾打印日志文件路径

### 14.7 错误呈现

- 外部命令失败时，从捕获的输出中匹配错误模式行（`error:`, `make[N]: ***`, `undefined reference`, `^E:`, `dpkg: error`, `fatal:`）
- 匹配行用红色 `┄` 框线包裹高亮显示
- 无匹配时 fallback 显示最后 20 行输出
- 构建摘要重复列出失败组件名称

### 14.8 Python 输出接口

- 所有构建模块通过 `builder/output.py` 的 `BuildOutput` 类输出用户可见信息
- 构建管线内禁止直接 `print()` 或 `logging.info()` 输出
- `BuildOutput` 由 `BuildEngine` 创建，通过 `DockerRunner` 和 `ComponentBuilder` 注入
- Warning 仅在 VERBOSE 模式显示，但始终写入日志文件

---

## 15. 规范执行

- 本规范随项目演进持续更新
- 对规范的修改需通过 OpenSpec 变更流程提案
- AI Agent 在生成代码时必须遵循本规范
- Code Review 时应检查是否符合本规范
