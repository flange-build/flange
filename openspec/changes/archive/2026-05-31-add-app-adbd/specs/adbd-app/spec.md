## ADDED Requirements

### Requirement: adbd App 工程结构

adbd SHALL 作为 service 类型 App 存在于 `app/adbd/` 目录，包含以下文件：

- `app.yaml` — App 描述文件，type 为 service
- `BUILD.bazel` — Bazel 构建与 flange_deb 打包规则
- `bin/adbd-arm64` — 预编译 64-bit ARM adbd 二进制
- `bin/adbd-armhf` — 预编译 32-bit ARM adbd 二进制
- `scripts/usbdevice` — USB gadget 管理脚本
- `conf/usbdevice.conf` — 默认配置文件
- `systemd/usbdevice.service` — systemd 服务文件
- `udev/61-usbdevice.rules` — udev 规则文件

#### Scenario: App 目录结构完整

- **WHEN** 开发者查看 `app/adbd/` 目录
- **THEN** 目录包含 app.yaml、BUILD.bazel、bin/、scripts/、conf/、systemd/、udev/ 子目录或文件，且结构符合 `docs/app-architecture.md` 的 service 类型模板

### Requirement: 预编译二进制按架构选择

BUILD.bazel SHALL 通过 Bazel `select()` 机制按目标架构选择对应的 adbd 预编译二进制：
- `//toolchain:aarch64` 条件下选择 `bin/adbd-arm64`
- `//toolchain:armhf` 条件下选择 `bin/adbd-armhf`

#### Scenario: arm64 目标架构构建

- **WHEN** 使用 `--platforms=//toolchain:aarch64_linux` 构建 adbd deb 包
- **THEN** 打出的 .deb 包中 `/usr/bin/adbd` 为 arm64 架构的二进制文件

#### Scenario: armhf 目标架构构建

- **WHEN** 使用 armhf 平台配置构建 adbd deb 包
- **THEN** 打出的 .deb 包中 `/usr/bin/adbd` 为 armhf 架构的二进制文件

### Requirement: flange_deb 打包产出

adbd App SHALL 通过 `flange_deb` 规则打包为单个 .deb 包，包含以下文件安装映射：

| 源文件 | 安装路径 |
|--------|---------|
| adbd 二进制（按架构选择） | `/usr/bin/adbd` |
| `scripts/usbdevice` | `/usr/bin/usbdevice` |
| `conf/usbdevice.conf` | `/etc/usbdevice.conf` |
| `systemd/usbdevice.service` | `/lib/systemd/system/usbdevice.service` |
| `udev/61-usbdevice.rules` | `/usr/lib/udev/rules.d/61-usbdevice.rules` |

.deb 包 SHALL 声明 `/etc/usbdevice.conf` 为 conffiles，确保 dpkg 升级时不覆盖用户修改。

`flange_deb` 的 `systemd.auto_start` SHALL 设置为 `True`，使 deb postinst 中执行 `systemctl enable usbdevice.service`。

#### Scenario: deb 包安装后文件就位

- **WHEN** 在 rootfs chroot 中执行 `dpkg -i adbd_*.deb`
- **THEN** `/usr/bin/adbd`、`/usr/bin/usbdevice`、`/etc/usbdevice.conf`、`/lib/systemd/system/usbdevice.service`、`/usr/lib/udev/rules.d/61-usbdevice.rules` 均存在且权限正确（二进制和脚本为 755）

#### Scenario: systemd 服务自动启用

- **WHEN** deb 包安装完成
- **THEN** `usbdevice.service` 已被 `systemctl enable`，将在系统启动时自动拉起

### Requirement: 板级配置集成

板级配置（如 `board/radxa-zero3w/board.bzl`）的 `rootfs.custom_packages` 列表中添加 `"adbd"` 后，adbd deb 包 SHALL 被自动安装到该板子的 rootfs 中。

#### Scenario: Radxa Zero 3W 启用 adbd

- **WHEN** `board/radxa-zero3w/board.bzl` 的 `custom_packages` 包含 `"adbd"`
- **THEN** 构建该板子的 rootfs 时，adbd .deb 包被安装到 rootfs 中
