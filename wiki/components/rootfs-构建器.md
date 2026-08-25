---
title: rootfs 构建器
type: component
status: stable
sources:
  - builder/platforms/rockchip/rootfs.py
  - builder/platforms/allwinnera733/rootfs.py
  - builder/rootfs.py
  - builder/chroot.py
  - docker/Dockerfile
  - components/rootfs/config.jsonnet
  - components/rootfs/overlay/etc/bash.bashrc
  - components/rootfs/overlay/etc/sysctl.d/10-console-quiet.conf
  - components/rootfs/overlay/etc/skel/.bashrc
  - components/rootfs/overlay/root/.bashrc
related:
  - "[[ComponentBuilder 基类]]"
  - "[[rootfs 两阶段缓存]]"
  - "[[chroot 上下文]]"
  - "[[deb 打包引擎]]"
  - "[[app 打包系统]]"
  - "[[源码管理 SourceManager]]"
updated: 2026-07-14
---

## TL;DR

ubuntu-base + apt + overlay + deb 两阶段 rootfs 构建；按 `arch` 选择 QEMU，按 `rootfs.image_format` 输出 ext4 或 UBI。[[atk-rk3506b]] 使用 armhf + `qemu-arm-static` + UBIFS，其余既有块设备路径保持 ext4。

## 关键设计要点

- **package_sets 基线**：`components/rootfs/config.jsonnet` 定义 `ROOTFS["package_sets"]`（`base`/`debug`/`release`），platform/board 通过 `rootfs.package_set` 选用、`+package_set` 按 variant 激活，registry 展开为 `rootfs.packages` 扁平列表
- **Phase 1 — base**：解压 ubuntu-base，chroot 内 `apt-get install` `rootfs.packages`；tar 存 base cache，下次跳过
- **Phase 2 顺序**（`_build_phase2`）：app deb (`custom_packages`) → `extra_debs` → kernel modules → `extra_firmware` → `apply_overlays`（最后覆盖，优先级最高） → `_configure_users`（账号一体化）
- **App 注入**：engine 在 rootfs 前完成 App deb 并注入 `config["rootfs"]["custom_packages"]`
- **`extra_debs`**（基类 `_install_extra_debs`）：声明式下载并安装第三方 deb（不在 Ubuntu 官方源、又不便发布到 app 体系的预编译包）；通过 [[源码管理 SourceManager]] sha256 校验，批量 `dpkg -i` 后 `ldconfig`
- **`extra_firmware`**（基类 `_install_extra_firmware`）：`source` 多类型（`repo` 默认 / `kernel` / `bootloader` / `oot:<name>`），后三种复用同 build 已 ensure 的源不重复 clone（如 `oot:rkwifibt` 复用 [[out-of-tree 模块]] 已有源拷 BT 固件）；`files` 元素支持 `str` 或 `{src, dest}` dict 形态做重命名（如给无后缀 vendor 固件统一补 `.bin`）
- **继承**：`RockchipRootfsBuilder` / `AllwinnerA733RootfsBuilder` → `RootfsBuilder` → `ComponentBuilder`；`apply_overlays` / `_install_extra_debs` / `_install_extra_firmware` 复用基类
- **chroot**：`ChrootContext` bind-mount proc/sys/dev/pts + QEMU；`__exit__` umount
- **ARM32**：SoC 配置选择 Ubuntu Base armhf 与 `qemu-arm-static`；Docker 同时提供 armhf 运行库和 gcc-10 hard-float 工具链，宿主机无需 ARM32 环境
- **UBI**：`rootfs.image_format=ubi` 时先以 `mkfs.ubifs` 按 min-I/O/LEB/max-LEB 生成 volume，再用 `ubinize` 按 PEB/subpage/VID offset 封装 `rootfs.ubi`；`space_fixup=true` 对应 `mkfs.ubifs -F`，首次挂载可修复 NAND 空闲页
- **API 文件系统**：rootfs 固化 `/proc`、`/sys`、`/dev`、`/dev/pts`、`/run`、`/sys/kernel/config` 等挂载点，保证 systemd 与模块化 USB gadget 冷启动可用
- **用户与 sudo 体系**（基类 `_configure_users`，跨平台共享）：声明式配置 `rootfs.{users, default_user, disable_root_login, root_password, groups}`；`groups` 顶层声明同时承担"幂等 `groupadd -f` 预创"与"每个 user 默认入组集"双职。每 user 的 `sudo` 三态：`True`（默认入 sudo group）/ `False`（从入组集中扣除 `sudo`）/ `{"nopasswd": True}`（额外写 `/etc/sudoers.d/90-<name>` 0440 NOPASSWD ALL，构建期 `visudo -cf` 校验）。`disable_root_login: true` 同时锁 `/etc/shadow`（`passwd -l root`）与写 `/etc/ssh/sshd_config.d/10-flange.conf` 的 `PermitRootLogin no`，但 **adb 调试通道不受影响**（adbd 不走 PAM）；该开关启用但 `users` 空时框架在构建期 `raise ValueError`。`bash-completion` 进 base 包；overlay `etc/skel/.bashrc` 与 `root/.bashrc` 同款配置（PS1、ls/grep 彩色、`ll/la/l` alias、`sudo<TAB>` completion），让 ssh 登录与 `adb shell` 拿到的 root bash 体验对齐 ubuntu 桌面

## 关键代码位置

- [`builder/platforms/rockchip/rootfs.py:_build_phase1`](../../builder/platforms/rockchip/rootfs.py) — Phase 1，L108
- [`builder/platforms/rockchip/rootfs.py:_build_phase2`](../../builder/platforms/rockchip/rootfs.py) — Phase 2，L133
- [`builder/rootfs.py:RootfsBuilder.apply_overlays`](../../builder/rootfs.py) — overlay，L24
- [`builder/rootfs.py:RootfsBuilder._install_extra_debs`](../../builder/rootfs.py) — 第三方 deb，L69
- [`builder/rootfs.py:RootfsBuilder._configure_users`](../../builder/rootfs.py) — 账号一体化
- [`builder/chroot.py:ChrootContext`](../../builder/chroot.py) — chroot，L8

## 易踩坑

- base cache 依赖 packages 哈希；包列表变更自动失效，无需手动清理
- _modules_staging 的 source/build symlink 须由内核构建器预先删除，详见 [[kernel 构建器]]
- `disable_root_login: true` 仅锁串口 / SSH 通道，不锁 adb（adbd 不走 PAM）— 这是显式 feature，不是 bug；用于"开发期 adb 留口、生产期对外封锁"双场景
- `adb shell` 体验依赖 `/etc/bash.bashrc` 而非 `/root/.bashrc`：adbd 以 `argv[0]="sh"` 启动 `/bin/bash`，触发 POSIX 模式，bash 不读 `~/.bashrc`；ubuntu 编译时 `SYS_BASHRC` 把 `/etc/bash.bashrc` 钉死在交互启动路径上（POSIX 仍读），故 PS1 / 环境补齐 / alias 全放该文件。`HOME` / `USER` 等变量在文件早期无条件设（adbd 不走 PAM 进来环境为空，btop 等程序读 `$HOME` 立即失败）
- 账号子树（`users` / `default_user` / `disable_root_login` / `groups` / `root_password`）整体进 rootfs cache hash；改任一字段触发完整 rootfs 重建
- UBI 几何必须来自目标 NAND：`leb_size = peb_size - data_offset`，volume/预留 PEB 与分区容量均在构建期校验；不要从其他 SPI NAND 型号复制参数
