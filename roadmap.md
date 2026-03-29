# flange 实施路线图

自底向上分阶段实施，以 Rockchip RK3566 (Radxa Zero 3W) 为首个打样平台。

---

## 已完成

### Phase 0 — 基础骨架
- Docker 构建环境（ubuntu:24.04 + bazelisk）
- Bazel 8 bzlmod 项目结构（MODULE.bazel）
- docker-compose.yml（volume mount、SSH 只读挂载）

### Phase 1 — 交叉编译工具链
- `toolchain/BUILD.bazel`：aarch64-linux-gnu cc_toolchain + platform 定义
- `toolchain/cc_toolchain_config.bzl`：工具路径和 include 路径声明
- `.bazelrc`：`--config=aarch64` 和 `--config=radxa-zero3w` 快捷配置

### Phase 2 — 配置体系
- `build/deep_merge.bzl`：dict 深度合并工具
- `build/config_registry.bzl`：三层配置注册（platform → SoC → board）、`get_board_config()` 查询
- `build/BUILD.bazel`：`config_setting`（`platform_rockchip`、`board_radxa_zero3w`）
- `platform/rockchip/config.bzl`、`platform/rockchip/rk3566/config.bzl`：平台/SoC 配置
- `board/radxa-zero3w/board.bzl`：板级配置（repo URL、branch、defconfig、DTS）

### Phase 3 — 内核构建
- `build/kernel_build.bzl`：框架+策略脚本架构（框架层无平台硬编码）
- `build/kernel_source.bzl`：repository rule 浅克隆内核源码
- `build/extensions.bzl`：module extension 从 config_registry 注册源码仓库
- `kernel/BUILD.bazel`：顶层 alias + select() 路由
- `kernel/rockchip/build.sh`：Rockchip 平台构建脚本（ARCH=arm64, Image+DTB）
- `kernel/rockchip/BUILD.bazel`：kernel_build 实例化 + select() 板级参数

---

## Phase 4 — Bootloader 构建（U-Boot + ATF）

### 目标
`bazel build //bootloader --config=radxa-zero3w` 产出 Rockchip 引导镜像。

### 背景
Rockchip 平台的引导流程：
```
BootROM → TPL(DDR init) → SPL(ATF loader) → ATF(BL31) → U-Boot → Kernel
```

产出两个关键文件：
- `idbloader.img`：TPL + SPL 合并，通过 `tools/mkimage` 生成
- `u-boot.itb`：ATF(BL31) + U-Boot proper + DTB 打包为 FIT image

### 涉及源码
- U-Boot：`https://github.com/radxa/u-boot`，分支 `next-dev-buildroot`
- ATF（ARM Trusted Firmware）：需要 `bl31.elf`，通常从 Rockchip rkbin 仓库获取或自行编译

### 要做的事
1. **源码拉取**
   - 扩展 `build/extensions.bzl`，新增 `bootloader_sources` module extension
   - 新增 `build/bootloader_source.bzl`（或复用 `kernel_source.bzl` 的 repository rule）
   - 在 `board.bzl` 中已有 bootloader repo/branch 配置

2. **构建规则**
   - `build/bootloader_build.bzl`：框架 rule，复用 kernel_build 的框架+策略模式
   - 环境变量契约：`BOOTLOADER_DIR`、`BOOTLOADER_DEFCONFIG`、`BOOTLOADER_BOARD` → `BOOTLOADER_IDBLOADER`、`BOOTLOADER_UBOOT_ITB`

3. **Rockchip 平台实现**
   - `bootloader/rockchip/build.sh`：Rockchip U-Boot 构建脚本
     - `make <board>_defconfig`
     - `make CROSS_COMPILE=aarch64-linux-gnu- BL31=<bl31.elf>`
     - 收集 `idbloader.img` + `u-boot.itb`
   - `bootloader/rockchip/BUILD.bazel`：bootloader_build 实例化
   - `bootloader/rockchip/patches/`：平台通用补丁

4. **顶层路由**
   - `bootloader/BUILD.bazel`：alias + select() 路由

5. **ATF/rkbin 处理**
   - 需要决策：自编译 ATF 还是使用 Rockchip 预编译的 `bl31.elf`
   - 如果用预编译：新增 repository rule 拉取 rkbin 仓库
   - `board.bzl` 中需新增 `atf` 或 `rkbin` 配置项

### 验证标准
- `bazel build //bootloader --config=radxa-zero3w` 产出 `idbloader.img` + `u-boot.itb`
- 产出文件可用 `rkdeveloptool` 刷入设备启动

---

## Phase 5 — Rootfs 构建（ubuntu-base + deb）

### 目标
`bazel build //rootfs --config=radxa-zero3w` 产出可用的根文件系统镜像。

### 背景
基于 ubuntu-base（minimal rootfs tarball）构建，不走 debootstrap 全量安装。流程：
```
ubuntu-base tarball → 解压 → chroot 安装 deb 包 → 应用 overlay → 打包 ext4 image
```

### 要做的事
1. **ubuntu-base 源获取**
   - `build/rootfs_source.bzl`：repository rule 下载 ubuntu-base tarball（带 SHA256 校验）
   - 或通过 `http_archive` 在 MODULE.bazel 声明
   - 板级配置中已有 `rootfs.base = "noble"` 标识版本

2. **构建规则**
   - `build/rootfs_build.bzl`：框架 rule
   - 需要 `qemu-user-static` 在 Docker 中做 aarch64 chroot（或使用 `debootstrap --foreign` + `chroot` 模式）
   - 输入：ubuntu-base tarball、包列表、overlay 文件、内核模块（可选）
   - 输出：`rootfs.ext4`（或 `rootfs.img`）

3. **rootfs 配置**
   - `rootfs/BUILD.bazel`：rootfs_build 实例化（扁平结构，不按平台分子目录）
   - 包列表文件：基础包 + 板级额外包（通过 board 配置传入）
   - `board/<name>/overlay/`：文件系统覆盖层（配置文件、启动脚本等）

4. **自定义 deb 包支持**
   - `packages/` 目录下的自定义软件可打包为 `.deb`
   - rootfs 构建时安装自定义 deb 包

### 关键挑战
- chroot 环境需要 binfmt_misc + qemu-user-static（Docker 中可能需要 `--privileged`）
- ext4 镜像生成需要 `mkfs.ext4`、`mount`（需要 root 权限或 fakeroot）
- Bazel 的 no-sandbox 模式已可支持这些需求

### 验证标准
- 产出 `rootfs.ext4` 可挂载并包含完整的 ubuntu-base 文件系统
- 包含基础网络工具（`ip`、`ssh`）
- overlay 文件正确覆盖到目标路径

---

## Phase 6 — 镜像打包 + 刷写

### 目标
- `bazel build //image --config=radxa-zero3w` 产出完整刷写镜像
- `bazel run //image:flash --config=radxa-zero3w` 执行整盘刷写
- `bazel run //kernel:flash --config=radxa-zero3w` 执行单组件刷写

### 背景
Rockchip 刷写使用 `rkdeveloptool` 或 `upgrade_tool`，设备进入 Maskrom/Loader 模式后通过 USB 刷写。分区布局：
```
| 偏移      | 分区          | 内容                    |
|-----------|--------------|------------------------|
| 0x0000    | idbloader    | TPL + SPL              |
| 0x4000    | uboot        | u-boot.itb             |
| 0x8000    | misc         | 启动模式标记            |
| 0xC000    | boot         | Image + DTB (extlinux) |
| 0x40000   | rootfs       | ext4 根文件系统         |
```

### 要做的事
1. **分区表定义**
   - `image/rockchip/parameter.txt`（或 GPT 分区定义）
   - 板级可覆盖分区大小（通过 board 配置）

2. **镜像打包规则**
   - `build/image_build.bzl`：框架 rule，聚合各组件产物
   - 输入：idbloader.img、u-boot.itb、Image、DTB、rootfs.ext4
   - 输出：完整刷写镜像（raw image 或 Rockchip 格式）
   - `image/BUILD.bazel`：顶层 alias + select()
   - `image/rockchip/build.sh`：Rockchip 打包脚本

3. **刷写规则**
   - `build/flash.bzl`：通用刷写框架 rule
   - 刷写在**宿主机**执行（非 Docker 容器内），需要特殊处理
   - `bazel run` 的脚本检测设备连接状态、调用平台刷写工具
   - 组件级刷写：`//kernel:flash` 只刷 boot 分区，`//bootloader:flash` 只刷 idbloader + uboot 分区
   - 全量刷写：`//image:flash` 重写分区表 + 所有分区

4. **宿主机刷写工具**
   - Rockchip：`rkdeveloptool`（需要用户在宿主机安装）
   - 刷写脚本检查工具是否存在，不存在时给出安装提示

### 关键挑战
- `bazel run` 默认在 Docker 容器内执行，但刷写需要宿主机 USB 访问
- 可能需要两阶段：容器内 build 产出镜像 → 宿主机脚本执行刷写
- 或使用 `--run_under` 指定在宿主机执行

### 验证标准
- `bazel build //image` 产出完整镜像文件
- `bazel run //image:flash` 成功刷入 Radxa Zero 3W 并启动
- 单组件刷写（kernel、bootloader）可独立工作

---

## Phase 7 — CLI 脚手架

### 目标
提供用户友好的命令行入口，简化日常开发操作。

### 要做的事
1. **envsetup.sh**
   - `source envsetup.sh` 初始化开发环境
   - 自动检测 Docker 环境、设置 shell alias
   - 提供板级选择菜单（`lunch` 风格）

2. **flange 命令**
   - `flange build` — 等价于 `docker compose run --rm build bazel build //image --config=<board>`
   - `flange flash` — 在宿主机调用刷写工具
   - `flange kernel` — 单独构建内核
   - `flange shell` — 进入 Docker 构建环境交互式 shell
   - `flange clean` — 清理构建产物
   - `flange status` — 显示当前配置和构建状态

3. **开发者体验**
   - Tab 补全支持（bash/zsh）
   - 彩色输出、进度显示
   - 错误信息包含修复建议

### 验证标准
- `source envsetup.sh && flange build` 完成完整构建
- `flange flash` 完成刷写
- 新用户可在 5 分钟内完成首次构建

---

## 架构约束（贯穿所有阶段）

- **框架与策略分离**：`build/*.bzl` 框架层禁止平台硬编码，平台逻辑通过策略脚本注入
- **三层职责分离**：`platform/` 声明配置 → 组件平台子目录实现构建 → `board/` 板级特殊化
- **环境变量契约**：框架与策略脚本通过约定的环境变量通信
- **增量构建**：所有组件支持增量编译，避免全量重建
- **打样不等于硬编码**：以 Radxa Zero 3W 验证，但框架必须保持平台无关
