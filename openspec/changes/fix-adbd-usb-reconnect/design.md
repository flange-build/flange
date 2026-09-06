## Context

设备运行基于 `standalone-linux-adbd` 的 `v36.0.1-linux.2` 静态构建。
断连后，`daemon/usb.cpp` 的 `StopWorker()` 以 `pthread_kill(thread, 0) == ESRCH`
判断工作线程退出；glibc 对已退出但尚未 join（回收）的线程仍可返回 0。
因此 monitor（监控线程）持续等待，主线程卡在回收 monitor，FunctionFS（用户态 USB 功能文件系统）
重开线程等待清理完成；即使 UDC（USB 设备控制器）恢复 `configured`，主机仍为 `offline`。

实机修复版在断连后约 69 毫秒再次记录 `opening ep0`，证明原线程清理死锁已解除。
设备 RK3588 的 6.1.115 内核 `f_fs.c` 中，`no_disconnect` 仅延迟解绑；重新打开 ep0（控制端点）时，
`ffs_data_opened → ffs_data_reset → ffs_closed → unregister_gadget_item` 仍使 UDC 解绑。
现有 `usbdevice` 脚本已内建恢复路径并会重启 adbd，因此进程编号变化符合该设备现有恢复机制。

## Goals / Non-Goals

**目标：** USB 断连清理能够结束，无需人工重启 adbd 或主机 ADB 服务，USB 在 30 秒内恢复 shell。
TCP 允许随内建服务恢复路径中断，但恢复后可重新连接，不得永久卡死。

**非目标：** 不改变 gadget（USB 功能组合）状态脚本、认证策略和依赖版本，不增加外部定时重启；
不为维持同一进程或 TCP 会话扩大修复范围。

## Decisions

1. 在共享工作线程路径明确记录完成状态，由停止逻辑读取，不再将 `pthread_kill(..., 0)` 的返回值当作退出证明。
   完成标志必须以原子方式发布，并覆盖工作线程所有返回路径；保留信号中断阻塞 `io_submit` 的现有机制。
   只删除等待循环可能留下阻塞 I/O；只重启服务则无法修复同一路径的后续断连。
2. 保留现有 App 的按架构预编译安装方式，在 Docker 内从相同源码版本应用同一补丁构建 arm64 和 armhf。
   仓库仅保存交付所需二进制、补丁、最小回归检查和 README；临时源码及构建目录留在 `.build/`。
3. 最小回归检查直接运行实际二进制，使用 `tests/adbd_usb_reconnect.py --allow-pid-change`
   以 `soft_connect` 连续断开/恢复，验证旧版失败、新版在 30 秒内恢复 USB shell（命令行会话）。
   另检查 TCP 可重新连接、adbd daemon（守护进程）和服务 loop（循环进程）数量未累积；
   物理插拔由用户最后确认，不另写复制线程实现的模拟测试。

## Risks / Trade-offs

- [完成状态发布遗漏或顺序错误] → 检查全部工作线程返回路径，使用原子状态，并保留线程回收。
- [新二进制不可用] → 部署前核对架构、静态链接及 SHA256，备份设备旧文件，失败时通过 SSH（安全远程登录）回滚。
- [armhf 无独立 USB 实机] → 编译并进行可用环境下的运行检查，明确记录未覆盖的硬件验证，不宣称全平台实测。
- [软件断连未覆盖电气变化] → 自动验证后仍保留物理插拔验收项。
- [现有内核与服务恢复会重启 adbd] → 允许 TCP 会话短暂中断，验收恢复后的重新连接，不修改 USB 脚本。

## 部署与回滚

先完成容器构建与检查，再备份目标设备 adbd、替换文件并重启相关服务。
SSH 保持独立可用；验证失败即恢复备份，不改分区和用户配置。
部署及测试结果完成后才更新任务状态、二进制摘要和实测说明。
