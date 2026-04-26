---
title: chroot 上下文
type: subsystem
status: stable
sources:
  - builder/chroot.py
related:
  - "[[rootfs 构建器]]"
  - "[[deb 打包引擎]]"
updated: 2026-04-26
---

## TL;DR

`ChrootContext` 是上下文管理器（`with` 语句），自动在进入时挂载 `/dev`、`/proc`、`/sys`、`/dev/pts` 到 rootfs 目录，退出时（无论是否异常）按序卸载，保证 rootfs Phase 2 阶段 `dpkg -i` 安全执行。

## 关键设计要点

- **绑定挂载列表**：`__enter__` 依次 bind-mount `/dev`、proc 类型挂 `/proc`、sysfs 挂 `/sys`、devpts 挂 `/dev/pts`；挂载点列表记录在实例变量便于逆序卸载
- **exception-safe 清理**：`__exit__` 捕获所有异常，在 finally 块内逆序 `umount -l`（lazy unmount），即使内部命令崩溃也不留悬挂挂载点
- **Docker 特权依赖**：mount 系统调用需要 CAP_SYS_ADMIN；`ChrootContext` 始终通过 `DockerRunner.run_privileged` 在特权容器内执行
- **`run` 方法**：`ChrootContext.run` 包装 `chroot <rootfs_dir> <cmd>` 调用，传入 label 供 `BuildOutput` 展示
- **额外挂载**：`bind_mount(src, dest)` 允许调用方在 with 块内追加自定义绑定（如挂载 `.build/deb/` 目录供 dpkg 读取）

## 关键代码位置

- [`builder/chroot.py:ChrootContext`](../../builder/chroot.py) — 主类，L8
- [`builder/chroot.py:ChrootContext.__enter__`](../../builder/chroot.py) — 挂载序列，L23
- [`builder/chroot.py:ChrootContext.__exit__`](../../builder/chroot.py) — 安全卸载，L45
- [`builder/chroot.py:ChrootContext.run`](../../builder/chroot.py) — chroot 命令，L60
- [`builder/chroot.py:ChrootContext.bind_mount`](../../builder/chroot.py) — 追加挂载，L68
