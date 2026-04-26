---
title: rootfs 构建器
type: component
status: stable
sources:
  - builder/platforms/rockchip/rootfs.py
  - builder/rootfs.py
  - builder/chroot.py
related:
  - "[[ComponentBuilder 基类]]"
  - "[[rootfs 两阶段缓存]]"
  - "[[chroot 上下文]]"
  - "[[deb 打包引擎]]"
  - "[[app 打包系统]]"
updated: 2026-04-26
---

## TL;DR

ubuntu-base + apt + overlay + deb 两阶段 rootfs 构建。Phase 1 可缓存（纯 apt），Phase 2 含 App deb 安装。`RockchipRootfsBuilder` 具体实现。

## 关键设计要点

- **Phase 1 — base**（`_build_phase1`，L117）：解压 ubuntu-base，chroot 内 `apt-get install` `rootfs.packages`；tar 存 base cache，下次跳过
- **Phase 2**（`_build_phase2`，L142）：board overlay；rsync _modules_staging；`dpkg -i` `custom_packages`（含 App deb）；`_set_root_password` + 校验
- **fstab**（`_install_fstab`，L69）：按分区表写 `/etc/fstab`，rootfs PARTUUID 固定
- **App 注入**：engine 在 rootfs 前完成 App deb 并注入 `config["rootfs"]["custom_packages"]`
- **两层继承**：`RockchipRootfsBuilder`（L15）→ `RootfsBuilder`（L13）→ `ComponentBuilder`；`apply_overlays` 在基类层复用
- **chroot**：`ChrootContext`（L8）bind-mount proc/sys/dev/pts + QEMU；`__exit__` umount

## 关键代码位置

- [`builder/platforms/rockchip/rootfs.py:_build_phase1`](../../builder/platforms/rockchip/rootfs.py) — Phase 1，L117
- [`builder/platforms/rockchip/rootfs.py:_build_phase2`](../../builder/platforms/rockchip/rootfs.py) — Phase 2，L142
- [`builder/rootfs.py:RootfsBuilder.apply_overlays`](../../builder/rootfs.py) — overlay，L19
- [`builder/chroot.py:ChrootContext`](../../builder/chroot.py) — chroot，L8

## 易踩坑

- base cache 依赖 packages 哈希；包列表变更自动失效，无需手动清理
- _modules_staging 的 source/build symlink 须由内核构建器预先删除，详见 [[kernel 构建器]]
