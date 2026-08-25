# adbd-app Specification

## Purpose

定义 adbd 作为 Python AppBuilder 管理的 service App 的目录、架构选择、deb 打包和 rootfs 集成契约。

## Requirements
### Requirement: adbd App 工程结构

adbd SHALL 作为 service 类型 App 存在于 `components/app/adbd/` 目录，包含以下文件：

- `app.yaml` — Python AppBuilder 的唯一 App 描述与打包数据源，type 为 service
- `bin/adbd-arm64` — 预编译 64-bit ARM adbd 二进制
- `bin/adbd-armhf` — 预编译 32-bit ARM adbd 二进制
- `scripts/usbdevice` — USB gadget 管理脚本
- `conf/usbdevice.conf` — 默认配置文件
- `systemd/usbdevice.service` — systemd 服务文件
- `udev/61-usbdevice.rules` — udev 规则文件

工程 SHALL NOT 依赖 `BUILD.bazel`、Starlark 或旧顶层 `app/` 目录。

#### Scenario: App 目录结构完整

- **WHEN** 开发者查看 `components/app/adbd/` 目录
- **THEN** 目录包含 app.yaml、bin/、scripts/、conf/、systemd/、udev/ 子目录或文件，不包含必需的 BUILD.bazel，且结构符合 `docs/app-architecture.md` 的 service 类型模板

### Requirement: 预编译二进制按架构选择

Python AppBuilder SHALL 按 FINAL_CONFIG 的 `arch` 和 `bin/adbd-<arch>` 文件名后缀选择预编译二进制，并在 deb 数据树中把架构后缀移除：

- `aarch64` 目标选择 `bin/adbd-arm64`
- `armhf` 目标选择 `bin/adbd-armhf`

#### Scenario: arm64 目标架构构建

- **WHEN** 在 `architecture.userspace=aarch64` 的 lunch target 下执行 `flange build app adbd`
- **THEN** 打出的 .deb 包中 `/usr/bin/adbd` 来自 `bin/adbd-arm64`

#### Scenario: armhf 目标架构构建

- **WHEN** 在 `architecture.userspace=armhf` 的 lunch target 下执行 `flange build app adbd`
- **THEN** 打出的 .deb 包中 `/usr/bin/adbd` 来自 `bin/adbd-armhf`

### Requirement: 板级配置集成

板级配置（如 `components/board/radxa-zero3w/config.jsonnet`）的 `rootfs.custom_packages` 列表中添加 `"adbd"` 后，构建引擎 SHALL 先通过 AppBuilder 生成 adbd deb，再由 rootfs Phase 2 自动安装。

#### Scenario: Radxa Zero 3W 启用 adbd

- **WHEN** `components/board/radxa-zero3w/config.jsonnet` 的 `rootfs.custom_packages` 包含 `"adbd"`
- **THEN** 构建该板子的 rootfs 时，adbd .deb 包在 rootfs 之前生成并安装到镜像中

### Requirement: Python deb 打包产出

adbd App SHALL 由 `AppBuilder` 解析 `app.yaml`，并通过 `DebBuilder` 打包为单个 .deb 包，包含以下文件安装映射：

| 源文件 | 安装路径 |
|--------|---------|
| adbd 二进制（按架构选择） | `/usr/bin/adbd` |
| `scripts/usbdevice` | `/usr/bin/usbdevice` |
| `conf/usbdevice.conf` | `/etc/usbdevice.conf` |
| `systemd/usbdevice.service` | `/lib/systemd/system/usbdevice.service` |
| `udev/61-usbdevice.rules` | `/usr/lib/udev/rules.d/61-usbdevice.rules` |

`app.yaml` SHALL 声明 `/etc/usbdevice.conf` 为 conffiles，确保 dpkg 升级时不覆盖用户修改；`systemd.auto_start` SHALL 为 `true`，使 deb postinst 执行 `systemctl enable usbdevice.service`。

#### Scenario: deb 包安装后文件就位

- **WHEN** 在 rootfs chroot 中执行 `dpkg -i adbd_*.deb`
- **THEN** `/usr/bin/adbd`、`/usr/bin/usbdevice`、`/etc/usbdevice.conf`、`/lib/systemd/system/usbdevice.service`、`/usr/lib/udev/rules.d/61-usbdevice.rules` 均存在且权限正确（二进制和脚本为 755）

#### Scenario: systemd 服务自动启用

- **WHEN** deb 包安装完成
- **THEN** `usbdevice.service` 已被 `systemctl enable`，将在系统启动时自动拉起
