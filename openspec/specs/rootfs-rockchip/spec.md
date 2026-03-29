### Requirement: Rockchip 平台 rootfs 构建脚本
`rootfs/rockchip/build.sh` SHALL 实现 Rockchip 平台的 rootfs 构建流程：解压 ubuntu-base tarball -> 设置 qemu-user-static -> chroot 安装 apt 包 -> 安装自定义 deb 包 -> 应用 overlay -> 清理 -> 打包 rootfs.tar.gz。

#### Scenario: 完整构建流程
- **WHEN** rootfs_build 框架调用 `rootfs/rockchip/build.sh`
- **THEN** 依次执行解压、chroot 包安装、overlay 应用、打包步骤，产出 rootfs.tar.gz

#### Scenario: qemu-user-static 设置
- **WHEN** build.sh 准备 chroot 环境
- **THEN** 复制 `qemu-aarch64-static` 到 rootfs 的 `/usr/bin/`，构建完成后移除

### Requirement: chroot 环境正确挂载和卸载
build.sh SHALL 在 chroot 前挂载 `/proc`、`/sys`、`/dev`、`/dev/pts`，在 chroot 操作完成后正确卸载，避免资源泄漏。

#### Scenario: chroot 挂载
- **WHEN** build.sh 进入 chroot 环境
- **THEN** `/proc`、`/sys`、`/dev`、`/dev/pts` 已挂载

#### Scenario: chroot 卸载
- **WHEN** build.sh 完成 chroot 操作（包括异常退出）
- **THEN** 所有挂载点已正确卸载

### Requirement: 自定义 deb 包选择性安装
build.sh SHALL 根据 `ROOTFS_CUSTOM_PACKAGES` 环境变量中的组件名，在 `ROOTFS_PACKAGES_DIR` 对应子目录中查找 `.deb` 文件并安装到 chroot 环境中。

#### Scenario: 安装指定的自定义包组件
- **WHEN** `ROOTFS_CUSTOM_PACKAGES="gpu-driver wifi-firmware"`
- **THEN** 安装 `${ROOTFS_PACKAGES_DIR}/gpu-driver/*.deb` 和 `${ROOTFS_PACKAGES_DIR}/wifi-firmware/*.deb`

#### Scenario: 未指定自定义包
- **WHEN** `ROOTFS_CUSTOM_PACKAGES` 为空
- **THEN** 跳过自定义 deb 包安装步骤

### Requirement: overlay 文件覆盖
build.sh SHALL 将 `ROOTFS_OVERLAY_DIR` 中的文件覆盖到 rootfs 根目录，保持目录结构和文件权限。

#### Scenario: overlay 目录非空
- **WHEN** `ROOTFS_OVERLAY_DIR` 包含 `etc/hostname` 文件
- **THEN** rootfs 中的 `/etc/hostname` 被覆盖为 overlay 中的版本

#### Scenario: overlay 目录为空
- **WHEN** `ROOTFS_OVERLAY_DIR` 为空或不存在
- **THEN** 跳过 overlay 步骤，不报错

### Requirement: Rockchip rootfs BUILD.bazel 实例化
`rootfs/rockchip/BUILD.bazel` SHALL 实例化 `rootfs_build` rule，通过 `select()` 按板级配置传入参数。

#### Scenario: radxa-zero3w 构建参数
- **WHEN** 使用 `--config=radxa-zero3w` 构建
- **THEN** 使用 `@rootfs_src_radxa_zero3w` 源、board.bzl 中的包列表、`//board/radxa-zero3w:overlay`
