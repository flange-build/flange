# 验证记录：add-alpine-distro-layer

2026-11-09，宿主 Ubuntu 24.04 x86_64，Docker 28.5.1。工作区 `../flange-alpine-ws`
（tool_root=`../flange-layer`，layers=`["../flange-layer-alpine"]`），目标
`luckfox-pico-pro-max-alpine-release`。以下均为真实 Docker 构建结果，未上板。

## 环境与 SDK（任务 1.x、4.1、4.2）

- `flange docker build` 生成 `flange-alpine:3.24`：apk-tools-static 3.0.9 与 alpine-keys 2.6
  按 SHA256 校验；armv7 SDK 由 `apk.static --arch armv7 --keys-dir ...` 验签安装
  （musl 1.2.6、gcc/libstdc++ 15.2.0、zlib 1.4）。
- Ubuntu archive 当时仅 48 kB/s 且超时，改为复用 flange-build 镜像随 Swift 提供的
  clang 21 / lld / llvm-*（`/opt/swift-embedded`），不再安装第二套 LLVM。
- C++（libstdc++、std::thread、zlib）交叉编译产物解释器为 `/lib/ld-musl-armhf.so.1`，
  `qemu-arm-static -L /opt/flange-sdk/armv7` 运行输出 `flange-alpine-thread zlib=1.4`。
- `apk.static mkpkg` 生成的 apk v3 包经 `apk adbdump` 校验 info/depends/paths；
  后端将 staging 目录统一为 root:root、0755（否则 mkpkg 记录宿主属主与 0700 根目录）。

## rootfs（任务 3.x）

- Phase 1：minirootfs 3.24.4 + 16 个基线包，`apk update/upgrade/add` 在 qemu chroot 中完成并缓存快照。
- Phase 2：核心账号逻辑原样复用（shadow/sudo/bash）；debugfs 检查临时 ext4 构建：
  - `ttyFIQ0::respawn:/sbin/getty -L 0 ttyFIQ0 vt100`
  - runlevel：sysinit `devfs dmesg udev udev-trigger udev-settle`；boot `bootmisc hostname modules
    networking seedrng sysctl syslog`；default `chronyd crond sshd udev-postmount usbmoded`
  - `/etc/sudoers.d/00-flange-sudo-group` 0440 root；flange UID/GID 1000 入 sudo 组；root `!*`
  - sshd drop-in `10-flange.conf` 且主配置含 Include；qemu 模拟器已清除；内核模块 6.1.115
- 包清单 124 个 apk（含 adbd、usbmoded、python3、eudev），无 systemd/dpkg/apt。
- 最终 `rootfs.ubi` 约 20 MB（解包约 72 MB），UBI volume 位于 mtd3。

## App 链路（任务 2.x、4.3、5.1）

- adbd、usbmoded 打成 apk：只含 OpenRC 脚本，无 systemd 文件；usbmoded 经 post-install
  加入 default runlevel；`/usr/lib/usbmoded/notify` 与 udev 规则就位。
- `qemu-arm-static` 在 rootfs 中以 musl Python 3.14 导入 `usbmoded.capabilities.daemon` 与 yaml 成功。
- 层内 `musl-check`（CMake/C++/Threads/ZLIB）：`flange app build musl-check` 生成
  `musl-check-1.0.0.apk`；装入 rootfs 时依赖 libstdc++ 由仓库解析；在该 rootfs 中运行输出
  `musl-check: libc=musl thread=ok zlib=1.4`。
- `flange build` 完整目标通过，生成 idblock、u-boot.itb、boot.img、rootfs.ubi、parameter.txt、
  flash-config.json。

## 回归

- flange-layer 全量 `pytest tests`：2407 passed, 15 skipped；Rockchip golden 零 diff。
- Alpine 层 `pytest tests`：9 passed。

## 未验证

- 实机启动、串口登录、以太网、SSH、adb 连接与 `flange app deploy/run/log`（任务 5.2）。
- usbmoded 在 OpenRC 下的 USB 插拔重连（依赖 eudev 触发 notify）。
