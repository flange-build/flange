## ADDED Requirements

### Requirement: Alpine 发行版层
Alpine 层 MUST 以外部层形式提供 `alpine` 发行版、构建环境、musl 工具链与 `apk` 包格式，
flange 核心 MUST NOT 引用其内容。rootfs MUST 由 SHA256 固定的 Alpine minirootfs 与 `apk add` 构建，
init 系统为 OpenRC。

#### Scenario: 生成 Alpine rootfs
- **WHEN** 工作区启用 Alpine 层并选择 `luckfox-pico-pro-max-alpine-release`
- **THEN** rootfs 含 musl、busybox、OpenRC、openssh，且不含 systemd、dpkg、apt
- **AND** 包清单记录每个 apk 包名与版本

### Requirement: musl App 构建与 apk 包
目标为 Alpine 时，C/C++ App MUST 由 musl 目标 SDK 编译、打包为 `.apk` 并能装入 rootfs 与设备；
App 报告 MUST 记录 Alpine 发行版与 SDK 身份。

#### Scenario: 动态链接程序在目标运行
- **WHEN** 构建依赖 musl libc 与 libstdc++ 的 C++ App 并装入 Alpine rootfs
- **THEN** 程序解释器为 `/lib/ld-musl-armhf.so.1`，在 QEMU chroot 与实机上运行成功
