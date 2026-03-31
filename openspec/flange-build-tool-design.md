# flange 构建工具设计方案

本文档是 flange 构建系统的设计方案，描述架构决策、技术选型和实现策略。与 `flange-build-tool-spec.md`（规格）配套使用。

---

## 1. 背景与目标

### 1.1 问题陈述

嵌入式 Linux 系统构建面临以下痛点：
- **Buildroot/Yocto 学习曲线陡峭**：配置复杂，构建时间长，调试困难
- **环境不可复现**：宿主机环境差异导致构建结果不一致
- **全量重建浪费时间**：修改一个内核配置需要重新编译整个系统
- **刷写流程碎片化**：不同平台的刷写工具和流程各不相同

### 1.2 设计目标

flange 的设计目标是提供一个**快速、可预测、可复现**的嵌入式 Linux 系统构建框架：

1. **快速验证**：内核/文件系统/全系统级别的快速验证通道
2. **可预测构建**：基于 ubuntu-base + apt 包，构建结果确定可控
3. **增量构建**：只重建变更影响的组件
4. **多平台支持**：Rockchip、Allwinner、Qualcomm 等平台，新增平台不改框架
5. **产品级输出**：可直接刷写的完整磁盘镜像

---

## 2. 架构设计

### 2.1 分层架构

```
用户接口层    envsetup.sh → flange 命令（lunch/build/flash/clean/status）
    │
配置层        platform/ → SoC → board/（三层继承 + deep_merge）
    │         config_registry.bzl（注册表）、config_setting（Bazel 条件路由）
    │
构建层        Docker 容器 + Bazel
    │         build/*.bzl（框架规则）+ <component>/<platform>/build.sh（策略脚本）
    │
产物层        target/<board>/image/（<board>_firmware_<date>.img + 组件镜像）
    │
部署层        flange flash → scripts/flash/<platform>.sh → upgrade_tool（宿主机执行）
```

### 2.2 核心架构决策

| 决策 | 选择 | 理由 |
|------|------|------|
| 构建隔离 | Docker 容器 | 环境可复现，不污染宿主机 |
| 构建系统 | Bazel | 增量构建、依赖自动推断、缓存复用 |
| 基础系统 | ubuntu-base + apt | 包生态成熟，减少自编译工作量 |
| rootfs 压缩 | base 用 zstd，最终用 gzip | zstd 解压快（增量构建），gzip 兼容性好（刷写） |
| 分区表 | GPT | 现代标准，支持大容量存储 |
| rootfs 定位 | 固定 PARTUUID | 避免动态 UUID 替换的复杂性和脆弱性 |
| 刷写工具 | 项目内置 upgrade_tool | 不依赖系统安装，版本可控 |

### 2.3 构建与部署分离

```
┌─────────────────────────────────┐     ┌───────────────────────────────┐
│        Docker 容器（构建）        │     │        宿主机（刷写）           │
│                                 │     │                               │
│  aarch64 交叉编译工具链           │     │  tools/<os>/upgrade_tool/     │
│  Bazel 8.x + 自定义构建规则      │     │  scripts/flash/<platform>.sh  │
│  qemu-user-static（chroot）     │     │  USB → 目标设备                │
│                                 │     │                               │
│  产出 → target/<board>/image/   │────▶│  读取 → target/<board>/image/ │
└─────────────────────────────────┘     └───────────────────────────────┘
```

- 构建操作通过 `docker compose run --rm --build build` 自动触发镜像构建
- 刷写操作在宿主机直接执行，通过 USB 连接目标设备

---

## 3. 配置系统设计

### 3.1 三层配置继承

```
platform/rockchip/config.bzl          ← vendor、flash_tool、rkbin repo/branch
    └── platform/rockchip/rk3566/config.bzl  ← soc、arch、ini_prefix、trust_ini_prefix
            └── board/radxa-zero3w/board.bzl  ← board、dts、kernel/bootloader repo+defconfig
```

合并通过 `build/deep_merge.bzl` 实现，支持两层嵌套 dict 合并。`build/config_registry.bzl` 提供 `get_board_config(board_name)` 统一查询接口。

### 3.2 Bazel 条件路由

```
.bazelrc:
  build:radxa-zero3w --define=platform=rockchip --define=board=radxa-zero3w --platforms=//toolchain:aarch64_linux

build/BUILD.bazel:
  config_setting(name = "platform_rockchip", define_values = {"platform": "rockchip"})
  config_setting(name = "board_radxa_zero3w", define_values = {"board": "radxa-zero3w"})

各组件 BUILD.bazel:
  alias(actual = select({"//build:platform_rockchip": "//kernel/rockchip", ...}))
```

新增板子只需：
1. `board/<name>/board.bzl` 声明配置
2. `.bazelrc` 添加一行 `build:<name>` 配置
3. `build/BUILD.bazel` 添加 `config_setting`

---

## 4. 框架+策略分离

### 4.1 设计原则

构建规则严格分为**框架层**（`build/*.bzl`）和**策略层**（`<component>/<platform>/build.sh`）：

- **框架层**：通用流程编排（源码管理、补丁应用、产物收集），MUST NOT 包含平台假设
- **策略层**：平台特有的编译命令和打包逻辑，通过环境变量接收输入、声明输出
- **通信契约**：框架设置输入环境变量（如 `BOOTLOADER_DIR`），策略脚本设置输出变量（如 `BOOTLOADER_IMG`）

### 4.2 组件构建规则

| 规则 | 框架文件 | 输入变量 | 输出变量 |
|------|---------|---------|---------|
| `bootloader_build` | `build/bootloader_build.bzl` | `BOOTLOADER_DIR`、`BOOTLOADER_DEFCONFIG`、`FIRMWARE_DIR` 等 | `BOOTLOADER_IMG`、`BOOTLOADER_IDBLOADER`、`BOOTLOADER_MINILOADER` |
| `rootfs_base` | `build/rootfs_base.bzl` | `ROOTFS_TARBALL`、`ROOTFS_PACKAGES`、`ROOTFS_APT_CACHE_DIR` | `ROOTFS_BASE_OUTPUT` |
| `rootfs_customize` | `build/rootfs_customize.bzl` | `ROOTFS_BASE`、`ROOTFS_OVERLAY_DIR`、`ROOTFS_CUSTOM_PACKAGES` | `ROOTFS_OUTPUT` |
| `boot_partition` | `build/boot_partition.bzl` | `BOOT_KERNEL_IMAGE`、`BOOT_DTB`、`BOOT_KERNEL_ARGS` 等 | `BOOT_IMG_OUTPUT` |
| `image_build` | `build/image_build.bzl` | `IMAGE_BOOT`、`IMAGE_BOOTLOADER_DIR`、`IMAGE_ROOTFS` | `IMAGE_OUTPUT` |

所有构建 action 使用 `no-sandbox` 执行，因为需要 chroot、mount、losetup 等特权操作。

---

## 5. Rockchip 启动链设计

### 5.1 启动流程

```
BootROM → idbloader.img (sector 64) → bootloader.img (sector 0x4000) → boot.img → rootfs
           │                            │                                │          │
           IDB 格式                      FIT 格式                        ext4       ext4
           DDR init + SPL               U-Boot + BL31 + BL32 + DTB     Image+DTB  ubuntu-base
           (mkimage -T rksd)            (make u-boot.itb)              extlinux    apt 包 + overlay
```

### 5.2 三种 Bootloader 产物

| 产物 | 格式 | 生成工具 | 用途 |
|------|------|---------|------|
| `idbloader.img` | IDB（BootROM 可识别） | `mkimage -n rk3568 -T rksd -d DDR:SPL` | 磁盘启动，写入 firmware.img sector 64 |
| `bootloader.img` | FIT（u-boot.itb） | U-Boot `make` + `make u-boot.itb` | 磁盘启动，写入 firmware.img sector 0x4000 |
| `miniloader.bin` | MiniLoader（含 USB 协议） | rkbin `boot_merger` | USB 刷写，`upgrade_tool DB` 上传到设备 RAM |

关键区分：**IDB 格式**（磁盘启动）和 **MiniLoader 格式**（USB 上传）使用相同的 rkbin DDR+SPL 二进制，但打包方式不同。boot_merger 输出包含 usbplug，不能写入磁盘 sector 64。

### 5.3 固件镜像布局

```
<board>_firmware_<date>.img:
  sector 0-33     GPT 分区表（parted 创建）
  sector 64       idbloader.img（IDB 格式，BootROM 读取）
  sector 0x4000   bootloader.img（FIT，SPL 加载）
  sector 0x8000   boot.img（ext4，U-Boot extlinux 加载）
  sector 0x40000  rootfs.img（ext4，PARTUUID=614e0000-0000-4000-8000-000000000000）
```

GPT 分区表先建后写数据，避免 `parted mklabel gpt` 覆盖已写入的 bootloader 数据。rootfs 分区使用固定 PARTUUID（通过 `sfdisk --part-uuid` 设置），extlinux.conf 直接引用该 PARTUUID。

### 5.4 USB 刷写流程

```
upgrade_tool DB miniloader.bin       ← MiniLoader 上传到设备 RAM，初始化 eMMC 访问
upgrade_tool WL 0 <firmware>.img     ← 整盘写入 firmware 镜像
upgrade_tool RD                      ← 重启设备，从 eMMC 启动
```

组件级刷写同样先 DB 上传 miniloader，再按分区偏移写入对应组件。

---

## 6. Rootfs 两阶段构建

### 6.1 设计动机

将 rootfs 构建拆分为 **base** 和 **customize** 两阶段，优化增量构建速度：

- **base 阶段**（慢，~5min）：解压 ubuntu-base + chroot apt-get install → `base-rootfs.tar.zst`
- **customize 阶段**（快，~10s）：解压 base + overlay + 自定义 deb + 设置密码 → `rootfs.tar.gz`

修改 overlay 或自定义包时，只需重新执行 customize 阶段，跳过耗时的 apt 安装。

### 6.2 缓存策略

- **APT 包缓存**：`cache/apt` 通过 Docker volume 持久化，chroot 内 bind-mount 到 `/var/cache/apt/archives/`
- **base rootfs 缓存**：`base-rootfs.tar.zst` 作为 Bazel 产物缓存，apt 包列表不变时不重建
- **zstd 压缩**：base 阶段使用 zstd（解压速度 ~1.5GB/s），customize 阶段解压 base 几乎瞬间完成

---

## 7. CLI 设计

### 7.1 用户交互流程

```bash
source envsetup.sh          # 注入 lunch/flange 函数
lunch radxa-zero3w           # 选择板级配置 → FLANGE_BOARD
flange build                 # Docker 内 Bazel 全量构建
flange collect               # 收集产物到 target/<board>/image/
flange flash                 # 宿主机 USB 刷写
```

### 7.2 Docker 透明化

用户不直接操作 Docker，`flange` 命令自动：
1. `--build` 确保 Docker 镜像与 Dockerfile 同步
2. 挂载项目目录、Bazel 缓存、APT 缓存、SSH 密钥
3. 透传 Bazel 命令和额外参数

### 7.3 命令与前置检查

| 命令 | 执行环境 | 前置检查 |
|------|---------|---------|
| `flange build/kernel/bootloader/rootfs/collect/clean` | Docker | board + Docker |
| `flange flash` | 宿主机 | board |
| `flange shell` | Docker | Docker |
| `flange status` | 宿主机 | 无 |

---

## 8. 目录结构

```
flange/
├── board/radxa-zero3w/          ← 板级配置、overlay、补丁
│   ├── board.bzl
│   ├── BUILD.bazel
│   └── overlay/etc/hostname
├── bootloader/rockchip/         ← Bootloader 平台实现
│   ├── build.sh
│   ├── BUILD.bazel
│   └── patches/
├── build/                       ← Bazel 自定义规则（框架层）
│   ├── bootloader_build.bzl
│   ├── boot_partition.bzl
│   ├── config_registry.bzl
│   ├── deep_merge.bzl
│   ├── extensions.bzl
│   ├── image_build.bzl
│   ├── image_collect.bzl
│   ├── rootfs_base.bzl
│   └── rootfs_customize.bzl
├── docker/                      ← Docker 构建环境
│   ├── Dockerfile
│   └── entrypoint.sh
├── image/rockchip/              ← 镜像打包平台实现
│   ├── build_boot.sh
│   ├── build_image.sh
│   ├── BUILD.bazel
│   └── parameter.txt
├── kernel/rockchip/             ← 内核平台实现
├── platform/rockchip/           ← 平台配置声明
│   ├── config.bzl
│   └── rk3566/config.bzl
├── rootfs/rockchip/             ← Rootfs 平台实现
│   ├── build_base.sh
│   ├── build_customize.sh
│   └── BUILD.bazel
├── scripts/                     ← 宿主机刷写脚本
│   ├── flange-flash.sh
│   └── flash/rockchip.sh
├── tools/                       ← 平台刷写工具（内置）
│   ├── linux/upgrade_tool/
│   └── macos/upgrade_tool/
├── toolchain/                   ← Bazel CC toolchain
├── docker-compose.yml
├── envsetup.sh
├── MODULE.bazel
├── .bazelrc
└── ProjectSpec.md
```

---

## 9. 扩展性设计

### 9.1 新增板子

只需配置，不改代码：
1. `board/<name>/board.bzl` — 板级配置
2. `.bazelrc` — `build:<name>` 快捷配置
3. `build/BUILD.bazel` — `config_setting`
4. `MODULE.bazel` — `kernel.source(board = "<name>")` 等

### 9.2 新增平台

添加策略脚本，不改框架：
1. `platform/<vendor>/config.bzl` — 平台配置
2. `bootloader/<vendor>/build.sh` + `BUILD.bazel` — Bootloader 实现
3. `kernel/<vendor>/build.sh` + `BUILD.bazel` — Kernel 实现
4. `rootfs/<vendor>/build_base.sh` + `build_customize.sh` + `BUILD.bazel` — Rootfs 实现
5. `image/<vendor>/build_image.sh` + `BUILD.bazel` — 镜像打包实现
6. `scripts/flash/<vendor>.sh` — 刷写模块
7. 各组件顶层 `BUILD.bazel` 的 `select()` 添加一行路由

框架层（`build/*.bzl`）无需修改。

### 9.3 当前实现状态

| 平台 | 打样设备 | 状态 |
|------|---------|------|
| Rockchip | Radxa Zero 3W (RK3566) | 已实现，已验证启动 |
| Allwinner | — | 未实现 |
| Qualcomm | — | 未实现 |
