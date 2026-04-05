## ADDED Requirements

### Requirement: rootfs_customize 接受 deb target 列表

`rootfs_customize` 规则 SHALL 新增 `custom_deb_targets` 属性（`label_list`），接受 Bazel 构建产出的 .deb 文件 target。

该属性与现有 `custom_packages_dir` 机制并存，不影响已有的预置 .deb 安装流程。

#### Scenario: 声明 Bazel 构建的 deb target

- **WHEN** `rootfs_customize` 中声明 `custom_deb_targets = ["//app/adbd:adbd-deb"]`
- **THEN** 构建 rootfs 时，adbd-deb target 先被构建，产出的 .deb 传递给 customize script 安装

#### Scenario: custom_deb_targets 为空

- **WHEN** `custom_deb_targets` 为空列表或未指定
- **THEN** rootfs 构建行为与修改前完全一致

#### Scenario: 同时使用两种 deb 来源

- **WHEN** 同时指定 `custom_packages_dir`（预置 .deb）和 `custom_deb_targets`（Bazel 构建 .deb）
- **THEN** 两种来源的 .deb 均被安装到 rootfs 中

### Requirement: customize script 接收 deb 路径

`rootfs_customize` 规则 SHALL 将 `custom_deb_targets` 的 .deb 文件路径通过 `ROOTFS_DEB_TARGETS` 环境变量传递给 customize script，路径间以空格分隔。

customize script SHALL 将这些 .deb 文件复制到 chroot 内，使用 `find -printf` 生成 chroot 内路径列表后执行 `dpkg -i` 安装。不使用 shell glob 展开，以避免 chroot 内路径解析问题。

#### Scenario: deb target 安装到 rootfs

- **WHEN** `ROOTFS_DEB_TARGETS` 包含一个或多个 .deb 文件路径
- **THEN** customize script 将 .deb 复制到 `${ROOTFS}/tmp/bazel-debs/`，用 `find -printf` 生成 chroot 内路径列表，执行 `chroot dpkg -i` 安装

#### Scenario: ROOTFS_DEB_TARGETS 为空

- **WHEN** `ROOTFS_DEB_TARGETS` 为空字符串
- **THEN** customize script 跳过 deb target 安装步骤

### Requirement: Bazel 依赖自动构建

当 `rootfs_customize` 声明了 `custom_deb_targets` 时，Bazel SHALL 自动先构建这些 target 的 .deb 产出，然后再执行 rootfs customize action。

#### Scenario: deb target 变更触发 rootfs 重建

- **WHEN** `app/adbd` 的源文件被修改（如 usbdevice 脚本更新）
- **THEN** Bazel 检测到 `adbd-deb` target 变化，自动重新构建 .deb 并重新执行 rootfs customize

### Requirement: rootfs/rockchip/BUILD.bazel 集成 adbd

`rootfs/rockchip/BUILD.bazel` 的 `rootfs_customize` 调用 SHALL 在 `custom_deb_targets` 中包含 `//app/adbd:adbd-deb`（通过 board select 路由）。

#### Scenario: Radxa Zero 3W 构建包含 adbd

- **WHEN** 使用 `--config=radxa-zero3w` 构建 rootfs
- **THEN** adbd .deb 被自动构建并安装到 rootfs 中
