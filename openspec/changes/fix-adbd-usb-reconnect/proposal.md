## Why

ROCK5B 在 USB 数据线重新插入后，ADB（Android 调试桥）长期显示 `offline`。
当前 adbd 将 `pthread_kill(thread, 0)` 当作线程退出检测，在 glibc 上无法识别已退出但尚未回收的线程，阻塞 USB 连接清理及后续重连。

## What Changes

- 修复上游 `daemon/usb.cpp` 的共享工作线程退出判断，保留中断阻塞 I/O（输入输出）的信号处理。
- 在 Docker（容器）内重建 arm64、armhf 静态二进制，保留源码补丁、构建方式与 SHA256 摘要。
- 部署 arm64 修复到现有设备，以可运行回归检查验证无需人工重启即可恢复 USB，并确认 TCP（传输控制协议）可重新连接。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `adbd-app`：明确 USB 断连后的自动恢复行为，以及携带本地修复的预编译二进制追溯要求。

## Impact

仅涉及 `components/app/adbd/` 中的预编译二进制、补丁及说明，和对应回归检查。
设备端只替换 adbd 并重启相关服务，不刷写分区、不修改用户配置。

## 非目标

- 不修改 USB 状态脚本，不增加 watchdog（看门狗）或定时重启服务。
- 不升级无关依赖，不改变 USB/TCP 协议、认证策略或板级配置。
- 不要求 adbd 进程编号保持不变，允许现有 USB 服务内建恢复路径自动重启 adbd。
- 不以软件断连测试代替最终物理插拔确认。
