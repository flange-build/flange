## Why

分层设计（`add-layer-composition`）已开放发行版、构建环境、工具链与包格式策略，并用 Debian 13 验证过
glibc + DEB 的外部发行版。但 Debian 与 Ubuntu 同属 glibc/APT/systemd 体系，没有验证"异构"发行版。
Alpine Linux（musl + apk + OpenRC + busybox）基础系统仅数 MB，适合 RV1106 这类 128/256 MB 内存、
256 MB SPI NAND 的设备，也是检验分层接口是否真正与发行版解耦的最好对象。

评估显示，分层接口能承接 rootfs 基础系统、包格式和工具链，但有三处耦合仍在核心：
1. **init 系统**：AppSpec 强制 service App 声明 systemd unit，`app_build`/`deploy` 直接调用 `systemctl`/`journalctl`；
2. **默认包格式**：App 包格式默认 `deb`，rootfs 安装与依赖声明（`depends`、`build.apt_packages`）是 Debian 语义；
3. **usbmoded**：默认 USB 服务直接调用 `systemctl` 并依赖 sd_notify。

## What Changes

### flange 核心（flange-layer 分支）
- 新增 init 系统抽象 `builder/init_system.py`：`InitSystem` 描述服务文件目录、启用方式与
  restart/is-active/MainPID/日志命令；内建 `systemd`（现状）与 `openrc`。
- `DistroBackend` 增加 `init_system` 与 `package_format` 属性，`AptDistro` 默认 `systemd`/`deb`。
- AppSpec 新增可选 `openrc:` 段（`script`、`auto_start`、`runlevel`）；service App 只需提供目标
  init 系统对应的服务文件，校验推迟到目标确定后。`openrc/` 目录约定安装到 `/etc/init.d/`。
- App 默认包格式由目标发行版决定；`packaging.depends` 支持按格式声明依赖（`apk:` 列表）。
- App 报告记录 init 系统；`flange app run/log/debug` 经 `InitSystem` 生成设备命令。
- rootfs 安装 App 包移入 `DistroBackend.install_apps`，删除 Ubuntu 专属的 "仅支持 DEB" 硬拒绝位置。
- usbmoded 抽出服务管理后端：systemd 走 `systemctl`，OpenRC 走 `rc-service`；无 `NOTIFY_SOCKET` 时跳过 sd_notify；
  adbd、usbmoded 补 OpenRC 服务脚本。

### Alpine 层（/home/eki/Project/flange/flange-layer-alpine，独立仓库）
- `layer.toml`：`name = "alpine"`，`requires = ["flange"]`，提供 `distro.alpine`、`environment.alpine`、
  `toolchain.alpine`、`packaging.apk`。
- `ApkDistro`：Alpine minirootfs（3.24，按架构选择归档与 SHA256）+ `qemu-arm-static` chroot + `apk add`；
  `/etc/apk/cache` 绑定共享缓存；安装 `shadow`/`sudo`/`bash` 以复用核心账号逻辑；OpenRC 服务启用；
  包清单经 `apk info -v` 导出。
- 构建环境：基于 `flange-build:latest`（保留内核/U-Boot 用的 gcc-10），加入 `apk.static`、clang/lld，
  以及用 `apk --root --arch` 生成的 Alpine 目标 SDK（musl-dev、gcc 运行库、libstdc++ 等）。
- 工具链：`armv7-alpine-linux-musleabihf`（及 aarch64 对应）clang 包装脚本，`target_sysroot` 指向 SDK。
- 包格式：`ApkPackageBackend` 用 `apk mkpkg` 生成 apk v3 包，设备与 rootfs 用 `apk add --allow-untrusted` 安装。
- 发行版基线 `components/distro/alpine/`：包集合、inittab（串口 getty）、网络、sshd、OpenRC runlevel。
- 板级：在核心 `luckfox-pico-pro-max` 上追加 `alpine` product（`distro: 'alpine'`），装 adbd + usbmoded。

## Capabilities

### New Capabilities
- `init-system-abstraction`: 发行版声明 init 系统，App 服务、部署与运行命令按 init 系统生成。
- `alpine-distro`: Alpine 外部发行版层的 rootfs、环境、SDK、apk 包格式契约。

### Modified Capabilities
- `usb-mode-service`: 服务启停不再假定 systemd。

## Impact

- 核心：`builder/app_spec.py`、`app.py`、`app_build.py`、`deploy.py`、`distro.py`、`rootfs.py`、
  `packaging/`、`components/app/{adbd,usbmoded}`；Ubuntu 目标行为与 golden 必须不变。
- 依赖 `add-rv1106-luckfox-pico-pro-max` 提供的板级 BSP。
- Alpine 层是独立仓库，flange 核心不引用其内容；验证工作区在层仓库外创建。

## 非目标

- 为现有板卡提供 Alpine product；厂商 glibc 用户态（Mali、RGA/MPP、fastrpc、L4T 等）在 musl 上运行。
- 自动把 systemd unit 翻译为 OpenRC 脚本；Debian/Alpine 包名自动映射。
- recovery 系统改用 Alpine；apk 仓库签名与远端发布。
