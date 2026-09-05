---
title: chroot 上下文
type: subsystem
status: stable
sources:
  - builder/chroot.py
related:
  - "[[rootfs 构建器]]"
  - "[[deb 打包引擎]]"
updated: 2026-09-05
---

## TL;DR

`ChrootContext` 是上下文管理器（`with` 语句），为 rootfs 内执行软件包安装命令准备 `/proc`、`/sys`、`/dev`、`/dev/pts` 挂载。它在初始化中途失败和正常退出时都回收本次资源，并保留原构建异常。chroot（改变进程所见根目录）使安装命令作用于正在制作的目标文件系统。先读 [rootfs 构建器](../components/rootfs-构建器.md)了解它在完整流程中的位置。

## 关键设计要点

- **挂载列表**：`__enter__` 依次挂载 proc 到 `/proc`、sysfs 到 `/sys`，再 bind-mount（绑定挂载）`/dev` 和 `/dev/pts`；挂载点记录在实例变量中
- **配置恢复**：进入时原子保存原有 `resolv.conf` 与 `policy-rc.d`，结束恢复内容、权限、所有权或链接；原来不存在才删除临时文件，不覆盖目标原有服务策略
- **进入回滚**：`__enter__` 的任一步骤失败都会回滚已保存文件和已建立挂载，避免 Python 尚未进入 `with` 正文时留下资源
- **退出清理**：每个恢复/卸载动作独立尝试，始终逆序使用普通 `umount`，不用 lazy detach（延迟分离）掩盖仍被占用的挂载。已有主异常时附加清理诊断并保留主异常；清理自身首次失败则报告该错误
- **活树边界**：rootfs/recovery 整棵可变树由 `rootfs_storage.py` 建立在容器原生 `/var/tmp`。删除前检查 mountinfo，剩余挂载会阻止递归删除，避免沿 `/dev` 等绑定挂载清理内容
- **Docker 特权依赖**：mount 系统调用需要 CAP_SYS_ADMIN；`ChrootContext` 始终通过 `DockerRunner.run_privileged` 在特权容器内执行
- **`run` 方法**：`ChrootContext.run` 包装 `chroot <rootfs_dir> <cmd>` 调用，传入 label 供 `BuildOutput` 展示
- **额外挂载**：`bind_mount(src, dest)` 允许调用方在 `with` 块内追加自定义绑定，例如让已发布的 App 软件包在 chroot 内可见；目录由调用者传入，不是固定的 `.build/deb/`

## 关键代码位置

- [`builder/chroot.py:ChrootContext`](../../builder/chroot.py) — 挂载、命令执行与退出清理
- [`builder/rootfs_storage.py`](../../builder/rootfs_storage.py) — 原生活树作用域与残留挂载门禁
