# flange 构建工具规格

本文档是 flange 构建系统的完整技术规格，合并自 26 个组件级 spec，按架构层次组织。

---

## 1. 构建环境

### 1.1 Docker 构建容器

#### Requirement: Docker 构建容器基于 Ubuntu 24.04
构建容器 SHALL 基于 `ubuntu:24.04` 镜像，使用 `linux/amd64` 平台架构。

#### Requirement: 容器内预装 Bazel 8.x
构建容器 SHALL 通过 bazelisk 安装 Bazel，版本由项目根目录的 `.bazelversion` 文件锁定为 8.x 系列。

#### Requirement: 容器内预装 aarch64 交叉编译工具链
构建容器 SHALL 预装 `gcc-aarch64-linux-gnu` 和 `g++-aarch64-linux-gnu` 交叉编译工具链、`qemu-user-static` 用于跨架构 chroot 构建 rootfs、`zstd` 用于 base rootfs 的高速压缩和解压、以及 `e2fsprogs`（mkfs.ext4）、`dosfstools`（mkfs.vfat）、`parted`、`fdisk`、`kpartx` 用于镜像打包。

#### Requirement: Docker Compose 定义构建服务
项目 SHALL 提供 `docker-compose.yml`，定义名为 `build` 的构建服务，以 `privileged: true` 模式运行，支持 rootfs 构建所需的 chroot 和 mount 操作。

#### Requirement: Bazel 缓存通过 volume 持久化
Docker Compose 配置 SHALL 将 Bazel output base 映射到宿主机 `output/bazel/` 目录，确保容器重建后保留构建缓存。

#### Requirement: APT 下载缓存通过 volume 持久化
Docker Compose 配置 SHALL 将宿主机 `./cache/apt` 目录映射到容器内 `/cache/apt` 目录，确保 rootfs 构建过程中下载的 .deb 文件跨构建持久化。

#### Requirement: Bazelisk 下载缓存通过 volume 持久化
Docker Compose 配置 SHALL 将宿主机 `./cache/bazelisk` 目录映射到容器内 `/root/.cache/bazelisk`，确保 bazelisk 下载的 Bazel 二进制文件跨容器重建持久化。

#### Requirement: 项目目录挂载到容器
Docker Compose 配置 SHALL 将宿主机项目根目录挂载到容器内的工作目录。

#### Requirement: SSH 密钥挂载与权限修正
Docker Compose 配置 SHALL 将宿主机 `~/.ssh` 目录以只读方式挂载到容器内 `/tmp/.ssh-host`。容器 entrypoint SHALL 在启动时将 SSH 配置复制到 `/root/.ssh` 并修正权限，确保 Git 仓库的 SSH 访问可用。entrypoint.sh 使用 `set -e` 运行。

### 1.2 交叉编译工具链

#### Requirement: Bazel CC toolchain 注册 aarch64-linux-gnu
项目 SHALL 在 `toolchain/BUILD.bazel` 中定义 `cc_toolchain` 和 `toolchain`，声明 aarch64-linux-gnu 交叉编译工具链。工具链 SHALL 在 `MODULE.bazel` 中通过 `register_toolchains` 注册。

#### Requirement: aarch64 linux platform 定义
项目 SHALL 在 `toolchain/BUILD.bazel` 中定义 `platform(name = "aarch64_linux")`，声明目标操作系统为 linux、目标 CPU 为 aarch64。

#### Requirement: --config=aarch64 快捷配置
`.bazelrc` SHALL 保留 `build:aarch64` 配置，映射到 `--platforms=//toolchain:aarch64_linux`。板级配置（如 `--config=radxa-zero3w`）SHALL 复用此 platform 声明。

#### Requirement: 交叉编译产出 aarch64 ELF
使用已注册的 toolchain 编译 C 代码 SHALL 产出 aarch64 架构的 ELF 可执行文件。

#### Requirement: cc_toolchain_config 包含正确的 include 路径
`cc_toolchain_config.bzl` SHALL 在 `cxx_builtin_include_directories` 中声明容器内 aarch64-linux-gnu 交叉编译器的系统头文件路径。

### 1.3 APT 缓存持久化

#### Requirement: APT 下载缓存 Docker volume 挂载
`docker-compose.yml` SHALL 将宿主机 `./cache/apt` 目录挂载到容器内 `/cache/apt`。

#### Requirement: rootfs_base 策略脚本使用 APT 缓存
rootfs base 平台构建脚本 SHALL 将 `ROOTFS_APT_CACHE_DIR` 目录 bind-mount 到 chroot 的 `/var/cache/apt/archives/`，使 apt-get install 命中已缓存的 .deb 文件。构建完成后 SHALL 正确 unmount。APT 缓存目录不存在时跳过 bind-mount。

---

## 2. Bazel 构建系统

### 2.1 项目骨架

#### Requirement: MODULE.bazel 定义项目模块
项目根目录 SHALL 包含 `MODULE.bazel` 文件，声明项目名称为 `flange`。

#### Requirement: 顶层 BUILD.bazel 存在
项目根目录 SHALL 包含 `BUILD.bazel` 文件，作为 Bazel workspace 的根 package。

#### Requirement: .bazelrc 配置 output base
`.bazelrc` SHALL 通过 `startup --output_base` 将 Bazel output base 指向 `/workspace/output/bazel`（容器内路径），对应宿主机的 `output/bazel/` 目录。

#### Requirement: .gitignore 忽略构建产物
项目 SHALL 包含 `.gitignore` 文件，忽略 `output/`、`target/`、`.flange/`、`bazel-*` 等构建产物和运行时状态。

#### Requirement: .bazelversion 锁定 Bazel 版本
项目根目录 SHALL 包含 `.bazelversion` 文件，锁定 Bazel 8.x 系列的具体版本号，供 bazelisk 使用。

### 2.2 配置路由

#### Requirement: platform 级 config_setting 定义
`build/BUILD.bazel` SHALL 定义 platform 级的 `config_setting` 规则，匹配 `--define platform=<vendor>` flag。首个实例为 `platform_rockchip`。

#### Requirement: board 级 config_setting 定义
`build/BUILD.bazel` SHALL 定义 board 级的 `config_setting` 规则，匹配 `--define board=<name>` flag。首个实例为 `board_radxa_zero3w`。

#### Requirement: .bazelrc 提供板级快捷配置
`.bazelrc` SHALL 为每个已注册板子提供 `build:<board-name>` 配置，映射到正确的 platform、board define 和 platforms flag。

#### Requirement: config_setting 具有公共可见性
`build/BUILD.bazel` 中的 `config_setting` 规则 SHALL 设置 `visibility = ["//visibility:public"]`。

---

## 3. 配置系统

### 3.1 配置注册表

#### Requirement: 配置注册表提供 get_board_config 函数
`build/config_registry.bzl` SHALL 提供 `get_board_config(board_name)` 函数，接受板子名称字符串，返回经过三层合并（platform → SoC → board）的完整配置 dict。

#### Requirement: 查询不存在的板子名称时报错
`get_board_config()` 在传入未注册的板子名称时 SHALL 立即 `fail()`，给出包含板子名称的明确错误信息。

#### Requirement: 注册表导出已注册板子列表
`build/config_registry.bzl` SHALL 导出 `REGISTERED_BOARDS` 列表或函数，供其他规则查询所有已注册的板子名称。

### 3.2 深度合并

#### Requirement: deep_merge 函数合并两个 dict
`build/deep_merge.bzl` SHALL 提供 `deep_merge(base, override)` 函数，返回深度合并后的新 dict。合并规则：dict 类型合并子 dict（最多支持两层嵌套），非 dict 类型后者覆盖前者，`base` 中存在但 `override` 中不存在的 key 保留。

> **实现约束**：由于 Starlark 不支持递归，当前实现通过 `_merge_flat` 辅助函数处理第二层，最多支持两层嵌套的 dict 合并。

#### Requirement: deep_merge 不修改输入 dict
`deep_merge` 函数 SHALL NOT 修改传入的 `base` 或 `override` dict，MUST 返回全新的 dict 对象。

### 3.3 板级配置

#### Requirement: 板级配置文件声明完整构建参数
`board/radxa-zero3w/board.bzl` SHALL 导出板级配置 dict，包含：`board`（板子名称）、`soc`（SoC 型号）、`platform`（所属平台）、`dts`（设备树名称）、`kernel`（含 `repo`/`branch`/`defconfig`）、`bootloader`（含 `repo`/`branch`/`defconfig`）、`boot`（含 `kernel_args`/`dtb_overlays`/`default_overlays`）、`rootfs`（含 `url`/`packages`/`custom_packages`）。

#### Requirement: 板级 BUILD.bazel 声明 filegroup
`board/radxa-zero3w/BUILD.bazel` SHALL 声明板级资源的 `filegroup`（如补丁、overlay），供组件构建规则通过 `deps` 引用。

### 3.4 平台配置

#### Requirement: Rockchip 平台级配置声明
`platform/rockchip/config.bzl` SHALL 导出 `ROCKCHIP_PLATFORM` dict，至少包括 `vendor` 和 `flash_tool`（值为 `"upgrade_tool"`，项目内置工具）。

#### Requirement: RK3566 SoC 级配置声明
`platform/rockchip/rk3566/config.bzl` SHALL 导出 `RK3566_SOC` dict，包含 `soc`、`arch`、`platform` 字段。

#### Requirement: platform 目录仅含配置声明文件
`platform/rockchip/` 及其子目录 SHALL 仅包含 `.bzl` 配置文件和 `BUILD.bazel`，MUST NOT 包含补丁、脚本、数据文件等。

---

## 4. 组件架构

### 4.1 目录结构与路由

#### Requirement: 组件目录按平台分子目录
差异度高的组件目录（kernel、bootloader、image、rootfs）SHALL 按平台建立子目录，每个子目录包含独立的 `BUILD.bazel` 和平台特有的构建脚本、补丁文件。

#### Requirement: bootloader 目录取代 uboot 目录
项目 SHALL 使用 `bootloader/` 作为引导加载程序的组件目录名。该目录下按平台建子目录，可容纳 U-Boot、ABL/XBL 等不同 bootloader 实现。

#### Requirement: 组件目录遵循顶层 alias + select() 路由模式
每个嵌入式组件 SHALL 在顶层目录提供 alias target，通过 `select()` 按平台 `config_setting` 路由到平台子目录的具体实现。

#### Requirement: 三层职责分离
- `platform/` 负责声明"用什么"（配置值）
- 组件平台子目录负责"怎么做"（构建实现和平台通用数据）
- `board/` 负责"板子特殊化"（板级补丁、DTS、overlay）

#### Requirement: 补丁归属判断规则
影响该平台所有板子的补丁放置在组件平台子目录（如 `kernel/rockchip/patches/`），仅影响特定板子的补丁放置在板级目录（如 `board/rk3588-evb/patches/kernel/`）。

### 4.2 自定义 deb 包

#### Requirement: 自定义 deb 包目录结构
`packages/` 目录 SHALL 按软件组件组织，每个组件一个子目录，子目录内包含 `.deb` 文件。

#### Requirement: packages 目录统一 filegroup 导出
`packages/BUILD.bazel` SHALL 通过 `filegroup` 使用 `glob(["**/*.deb"])` 导出所有 deb 文件，供 `rootfs_customize` rule 引用。

#### Requirement: 自定义包通过 board.bzl 配置安装策略
board.bzl 的 `rootfs.custom_packages` 字段声明需要安装的组件名列表，对应 `packages/` 下的子目录名。

---

## 5. Bootloader 构建

### 5.1 框架规则

#### Requirement: bootloader_build rule 采用框架+策略脚本架构
`build/bootloader_build.bzl` SHALL 提供 `bootloader_build` rule。rule 本身（框架）负责源码生命周期管理和产物收集，实际编译和打包由平台 `build_script` 执行。rule MUST NOT 硬编码任何平台特有参数。

属性：`bootloader_src`（Label，必选）、`build_script`（Label，必选）、`firmware_src`（Label，可选）、`defconfig`（string，必选）、`ini_prefix`（string，默认空）、`trust_ini_prefix`（string，默认空）、`platform_patches`（label_list）、`board_patches`（label_list）、`jobs`（int，默认 0）。

#### Requirement: 平台构建脚本通过环境变量契约通信

**框架 → 脚本（输入）：**
- `BOOTLOADER_DIR` — U-Boot 源码目录
- `BOOTLOADER_DEFCONFIG` — U-Boot defconfig 名称
- `BOOTLOADER_JOBS` — make 并行任务数
- `FIRMWARE_DIR` — 固件仓库路径（可能为空）
- `RKBIN_INI_PREFIX` — rkbin RKBOOT INI 文件前缀
- `RKBIN_TRUST_INI_PREFIX` — rkbin RKTRUST INI 文件前缀

**脚本 → 框架（输出）：**
- `BOOTLOADER_IMG` — bootloader.img 绝对路径（FIT image）
- `BOOTLOADER_IDBLOADER` — idbloader.img 绝对路径（IDB 格式）
- `BOOTLOADER_MINILOADER` — miniloader.bin 绝对路径（MiniLoader 格式）

#### Requirement: 持久化构建目录支持增量编译
通过 `git reset --hard HEAD` 重置源码（保留 `.o` 等编译中间产物），实现增量编译。

#### Requirement: 构建 action 使用 no-sandbox 执行
`execution_requirements = {"no-sandbox": "1", "no-remote": "1"}`。

### 5.2 Rockchip 平台实现

#### Requirement: Rockchip Bootloader 使用 rkbin 预编译固件
使用 rkbin 仓库提供的预编译 BL31 和 BL32 (OP-TEE) 固件，MUST NOT 从源码编译 ATF。

#### Requirement: 通过 INI 文件驱动固件路径
从 RKTRUST INI 解析 BL31 和 BL32 路径，从 RKBOOT INI 解析 DDR 和 SPL 路径，MUST NOT 硬编码固件文件名。

#### Requirement: 使用 mkimage 生成 idbloader.img
使用 U-Boot 编译产出的 `tools/mkimage`，以 `mkimage -n rk3568 -T rksd -d DDR:SPL` 将 rkbin 的 DDR init 和 SPL 打包为 IDB 格式 idbloader.img，用于磁盘启动（写入 sector 64）。

#### Requirement: 使用 boot_merger 生成 miniloader.bin
使用 rkbin 的 `tools/boot_merger` 配合 `RKBOOT/${ini_prefix}MINIALL.ini` 生成 MiniLoader 格式 miniloader.bin，用于 upgrade_tool USB 上传（DB 命令）。

#### Requirement: U-Boot 编译传入 BL31 和 BL32
将 rkbin 的 bl31.elf 和 tee.bin（BL32，若存在）拷贝至源码根目录。构建分两阶段：先完整 `make` 编译 U-Boot，再 `make u-boot.itb` 显式生成 FIT image。

#### Requirement: Rockchip 构建产出三个文件
- `idbloader.img`：IDB 格式（mkimage -T rksd），rkbin DDR+SPL，写入 sector 64
- `bootloader.img`：FIT image（U-Boot + BL31 + DTB），写入 sector 0x4000
- `miniloader.bin`：MiniLoader 格式（boot_merger），用于 upgrade_tool USB 上传

#### Requirement: Rockchip BUILD.bazel 使用 select() 分发板级参数
通过 `select()` 按 `config_setting` 分发 bootloader_src、defconfig、ini_prefix、trust_ini_prefix、board_patches。

#### Requirement: 配置分层——rkbin 配置归属
- platform 层：rkbin 的 `repo` 和 `branch`
- SoC 层：rkbin 的 `ini_prefix`、`trust_ini_prefix`
- board 层：U-Boot 的 `repo`、`branch`、`defconfig`

### 5.3 路由与收集

#### Requirement: Bootloader 顶层 alias 按平台路由
`bootloader/BUILD.bazel` 通过 `select()` 路由到平台子目录。未指定平台时报错。

#### Requirement: Bootloader 产物收集
收集 `idbloader.img`、`bootloader.img`、`miniloader.bin` 到 `target/<board>/bootloader/`。

---

## 6. Rootfs 构建

### 6.1 Base 阶段

#### Requirement: rootfs_base 框架 rule 定义
`build/rootfs_base.bzl` 定义 `rootfs_base` rule，从 ubuntu-base tarball 构建基础 rootfs，产出 `base-rootfs.tar.zst`。

属性：`rootfs_src`（tarball label，必选）、`build_script`（必选）、`packages`（apt 包列表，默认空列表）、`arch`（默认 arm64）、`jobs`（默认 0）。

环境变量契约：`ROOTFS_TARBALL`、`ROOTFS_PACKAGES`、`ROOTFS_APT_CACHE_DIR`、`ROOTFS_ARCH` → 脚本设置 `ROOTFS_BASE_OUTPUT`。

### 6.2 Customize 阶段

#### Requirement: rootfs_customize 框架 rule 定义
`build/rootfs_customize.bzl` 定义 `rootfs_customize` rule，在 base rootfs 上应用自定义 deb 包和 overlay，产出 `rootfs.tar.gz`。

属性：`base`（必选）、`build_script`（必选）、`custom_packages`、`custom_packages_dir`、`overlay`、`arch`。

环境变量契约：`ROOTFS_BASE`、`ROOTFS_CUSTOM_PACKAGES`、`ROOTFS_PACKAGES_DIR`、`ROOTFS_OVERLAY_DIR`、`ROOTFS_ARCH` → 脚本设置 `ROOTFS_OUTPUT`。

### 6.3 源码仓库

#### Requirement: rootfs_source repository rule
`build/rootfs_source.bzl` 定义 `rootfs_source` repository rule，通过 HTTP 下载 ubuntu-base tarball。接受 `url`（必需）和 `sha256`（可选）属性。

### 6.4 Rockchip 平台实现

#### Requirement: Rockchip 平台 rootfs 构建脚本
- `build_base.sh`：解压 tarball → qemu-user-static → APT 缓存 bind-mount → chroot 安装 apt 包 → 清理 → 打包 base-rootfs.tar.zst
- `build_customize.sh`：解压 base → 自定义 deb 安装 → overlay 应用 → 设置 root 密码（root:1234，通过 chpasswd）→ 打包 rootfs.tar.gz

#### Requirement: chroot 环境正确挂载和卸载
挂载 `/proc`、`/sys`、`/dev`、`/dev/pts`，完成或异常退出后正确卸载。

#### Requirement: Rockchip rootfs BUILD.bazel 实例化
实例化 `rootfs_base` 和 `rootfs_customize` 两个 rule，通过 `select()` 按板级配置传入参数。

### 6.5 路由与收集

#### Requirement: rootfs 顶层 alias + select() 路由
`rootfs/BUILD.bazel` 通过 `select()` 路由到平台 customize target。

#### Requirement: rootfs module extension 注册源码仓库
`build/extensions.bzl` 包含 `rootfs_sources` module extension，从 board.bzl 配置注册 `rootfs_source` repository rule。

---

## 7. 镜像打包

### 7.1 框架规则

#### Requirement: image_build 框架 rule 定义
`build/image_build.bzl` 定义 `image_build` rule。框架负责组件产物聚合和最终镜像收集，策略脚本负责分区表创建和镜像组装。rule MUST NOT 硬编码平台参数。

属性：`boot`（必选）、`bootloader`（必选）、`rootfs`（必选）、`build_script`（必选）、`partition_config`（可选）。

环境变量契约：`IMAGE_BOOT`、`IMAGE_BOOTLOADER_DIR`（含 idbloader.img、bootloader.img、miniloader.bin）、`IMAGE_ROOTFS`、`IMAGE_PARTITION_CONFIG` → 脚本设置 `IMAGE_OUTPUT`。

#### Requirement: image_build 产出 raw.img
内部产出 `raw.img`，为完整磁盘镜像，包含分区表和所有分区数据。

#### Requirement: image_collect 收集产物
`build/image_collect.bzl` 将镜像产物收集到 `target/<board>/image/`，raw.img 重命名为 `<board>_firmware_<date>.img`。

### 7.2 Boot 分区

#### Requirement: boot_partition 框架 rule 定义
`build/boot_partition.bzl` 定义 `boot_partition` rule。

属性：`kernel`（必选）、`build_script`（必选）、`image_name`（默认 "Image"）、`dts`（必选）、`dts_dir`（必选）、`default_overlays`、`kernel_args`、`boot_size_mb`（默认 256）。

环境变量：`BOOT_KERNEL_IMAGE`、`BOOT_DTB`、`BOOT_DTBOS_TAR`、`BOOT_DTS`、`BOOT_DTS_DIR`、`BOOT_DEFAULT_OVERLAYS`、`BOOT_KERNEL_ARGS`、`BOOT_SIZE_MB` → 脚本设置 `BOOT_IMG_OUTPUT`。

#### Requirement: extlinux.conf 使用固定 PARTUUID 标识 rootfs
`append` 行使用 `root=PARTUUID=614e0000-0000-4000-8000-000000000000 rootfstype=ext4 rootwait rw`，后接内核参数。无需动态 UUID 替换。

### 7.3 Rockchip 平台实现

#### Requirement: Rockchip 平台 boot 分区构建脚本
`image/rockchip/build_boot.sh`：创建目录结构 → 复制 Image 和 DTB → 解压 DTBO（从 dtbos.tar.gz）→ 生成 extlinux.conf → mkfs.ext4 打包为 boot.img。

#### Requirement: Rockchip 平台镜像打包脚本
`image/rockchip/build_image.sh` 流程：
1. 解析 parameter.txt 获取分区偏移
2. 创建空白镜像 + GPT 分区表（先建表再写数据）
3. 设置 rootfs 分区 PARTUUID（`614e0000-0000-4000-8000-000000000000`，通过 sfdisk）
4. dd idbloader.img 到 sector 64（IDB 格式）
5. dd bootloader.img 到 uboot 分区偏移
6. 写入 boot.img
7. 创建 rootfs ext4 → 解压 rootfs.tar.gz → 写入镜像
8. 产出 raw.img

#### Requirement: Rockchip parameter.txt 分区定义
定义默认分区布局（GPT），至少包含 uboot、boot、rootfs 分区的偏移和大小。

#### Requirement: Rockchip 镜像产物收集
收集到 `target/<board>/image/`：`<board>_firmware_<date>.img`、`idbloader.img`、`bootloader.img`、`miniloader.bin`、`boot.img`、`rootfs.tar.gz`、`parameter.txt`。

### 7.4 路由

#### Requirement: image 顶层 alias + select() 路由
`image/BUILD.bazel` 通过 `select()` 路由到平台子目录。`collect` target 同样路由。

---

## 8. 刷写系统

### 8.1 主入口脚本

#### Requirement: 刷写主入口脚本
`scripts/flange-flash.sh` 作为宿主机刷写主入口，解析参数，从 `target/<board>/image/` 读取产物，调用平台刷写模块。

支持三种模式：
- **整盘 dd**：`--raw --device /dev/sdX` → dd 写入 `*_firmware_*.img`
- **USB 整盘**：默认模式 → `upgrade_tool DB miniloader.bin` → `upgrade_tool WL 0 *_firmware_*.img` → `upgrade_tool RD`
- **组件级**：`--component kernel|bootloader` → DB miniloader.bin 后写入对应分区

### 8.2 平台刷写模块

#### Requirement: 平台刷写模块化架构
平台刷写逻辑通过 `scripts/flash/<platform>.sh` 实现，主脚本通过 source 加载。

#### Requirement: Rockchip 刷写模块
`scripts/flash/rockchip.sh` 使用项目内置的 `tools/<host_platform>/upgrade_tool/upgrade_tool`（根据 `uname -s` 自动选择 linux/macos），不依赖系统安装。

刷写流程：
1. `DB miniloader.bin` — 上传 MiniLoader 初始化设备存储
2. `WL 0 *_firmware_*.img` — 写入完整磁盘镜像
3. `RD` — 重启设备

组件级刷写同样先执行 DB，再按偏移写入对应分区。

### 8.3 安全与检测

#### Requirement: 刷写工具检测
执行前检测 `tools/<host_platform>/upgrade_tool/upgrade_tool` 是否存在且可执行。

#### Requirement: 刷写安全确认
dd 模式在执行前要求用户确认。USB 模式检测设备是否处于 Maskrom/Loader 模式。

---

## 9. CLI 用户接口

### 9.1 环境初始化

#### Requirement: envsetup.sh 初始化开发环境
通过 `source envsetup.sh` 注入 `lunch` 和 `flange` 函数，设置 `FLANGE_DIR` 环境变量。

#### Requirement: lunch 交互式板级选择
自动扫描 `board/*/board.bzl`，支持交互式菜单或直接 `lunch <board>` 指定。设置 `FLANGE_BOARD` 环境变量。

#### Requirement: 前置检查
- **构建类命令**（build/kernel/bootloader/rootfs/collect/clean）：检查 board + Docker
- **刷写命令**（flash）：仅检查 board
- **工具命令**（shell）：仅检查 Docker
- **信息命令**（status）：无检查

### 9.2 子命令

#### Requirement: flange build 构建完整镜像
等价于 `docker compose run --rm --build build bazel build //image --config=$FLANGE_BOARD`。

#### Requirement: flange kernel/bootloader/rootfs 单组件构建
分别构建对应组件，均通过 `docker compose run --rm --build build bazel build //<component> --config=$FLANGE_BOARD`。

#### Requirement: flange collect 收集构建产物
等价于 `docker compose run --rm --build build bazel run //image:collect --config=$FLANGE_BOARD`。

#### Requirement: flange flash 刷写
在宿主机调用 `scripts/flange-flash.sh --board $FLANGE_BOARD`，额外参数透传。

#### Requirement: flange shell 交互式 shell
等价于 `docker compose run --rm --build build bash`。

#### Requirement: flange clean 清理构建产物
删除 `target/$FLANGE_BOARD/` 并在容器内执行 `bazel clean`。

#### Requirement: flange status 显示状态
显示当前板级配置、Docker 运行状态和构建产物状态。

#### Requirement: flange 无参数显示帮助
输出所有可用子命令及简要描述。
