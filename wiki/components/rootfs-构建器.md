---
title: rootfs 构建器
type: component
status: stable
sources:
  - builder/platforms/rockchip/rootfs.py
  - builder/platforms/allwinnera733/rootfs.py
  - builder/rootfs.py
  - builder/chroot.py
related:
  - "[[ComponentBuilder 基类]]"
  - "[[rootfs 两阶段缓存]]"
  - "[[chroot 上下文]]"
  - "[[deb 打包引擎]]"
  - "[[app 打包系统]]"
  - "[[源码管理 SourceManager]]"
updated: 2026-05-06
---

## TL;DR

ubuntu-base + apt + overlay + deb 两阶段 rootfs 构建。Phase 1 可缓存（纯 apt），Phase 2 含 deb 安装与 overlay 覆盖。Rockchip / Allwinner 共用基类 `RootfsBuilder`，通用能力（overlay、`extra_debs`、`extra_firmware`）下沉到基类。

## 关键设计要点

- **package_sets 基线**：`components/rootfs/config.py` 定义 `ROOTFS["package_sets"]`（`base`/`debug`/`release`），platform/board 通过 `rootfs.package_set` 选用、`+package_set` 按 variant 激活，registry 展开为 `rootfs.packages` 扁平列表
- **Phase 1 — base**：解压 ubuntu-base，chroot 内 `apt-get install` `rootfs.packages`；tar 存 base cache，下次跳过
- **Phase 2 顺序**（`_build_phase2`）：app deb (`custom_packages`) → `extra_debs` → kernel modules → `extra_firmware` → `apply_overlays`（最后覆盖，优先级最高） → `_set_root_password` + 校验
- **App 注入**：engine 在 rootfs 前完成 App deb 并注入 `config["rootfs"]["custom_packages"]`
- **`extra_debs`**（基类 `_install_extra_debs`）：声明式下载并安装第三方 deb（不在 Ubuntu 官方源、又不便发布到 app 体系的预编译包）；通过 [[源码管理 SourceManager]] sha256 校验，批量 `dpkg -i` 后 `ldconfig`
- **`extra_firmware`**（基类 `_install_extra_firmware`）：`source` 多类型（`repo` 默认 / `kernel` / `bootloader` / `oot:<name>`），后三种复用同 build 已 ensure 的源不重复 clone（如 `oot:rkwifibt` 复用 [[out-of-tree 模块]] 已有源拷 BT 固件）；`files` 元素支持 `str` 或 `{src, dest}` dict 形态做重命名（如给无后缀 vendor 固件统一补 `.bin`）
- **继承**：`RockchipRootfsBuilder` / `AllwinnerA733RootfsBuilder` → `RootfsBuilder` → `ComponentBuilder`；`apply_overlays` / `_install_extra_debs` / `_install_extra_firmware` 复用基类
- **chroot**：`ChrootContext` bind-mount proc/sys/dev/pts + QEMU；`__exit__` umount

## 关键代码位置

- [`builder/platforms/rockchip/rootfs.py:_build_phase1`](../../builder/platforms/rockchip/rootfs.py) — Phase 1，L108
- [`builder/platforms/rockchip/rootfs.py:_build_phase2`](../../builder/platforms/rockchip/rootfs.py) — Phase 2，L133
- [`builder/rootfs.py:RootfsBuilder.apply_overlays`](../../builder/rootfs.py) — overlay，L24
- [`builder/rootfs.py:RootfsBuilder._install_extra_debs`](../../builder/rootfs.py) — 第三方 deb，L69
- [`builder/chroot.py:ChrootContext`](../../builder/chroot.py) — chroot，L8

## 易踩坑

- base cache 依赖 packages 哈希；包列表变更自动失效，无需手动清理
- _modules_staging 的 source/build symlink 须由内核构建器预先删除，详见 [[kernel 构建器]]
