## ADDED Requirements

### Requirement: USB 断连后自动恢复

adbd SHALL 在 USB 数据线断开后完成旧连接清理，在主机重新连接后 30 秒内恢复可用状态，
无需人工重启 adbd 或主机 ADB 服务；允许现有 USB 服务内建恢复路径自动重启 adbd。
工作线程停止逻辑 MUST 明确同步线程完成状态，不得依赖 `pthread_kill(thread, 0)` 返回 `ESRCH` 判断线程退出。
清理过程 MUST 保留中断阻塞 I/O（输入输出）的能力，不得使 adbd 永久卡死。
TCP（传输控制协议）会话允许随内建重启中断，但恢复后的通道 MUST 能重新连接。

#### Scenario: 连续重新连接 USB

- **WHEN** 已建立 ADB（Android 调试桥）连接的设备反复断开并恢复 USB
- **THEN** 每次重连后 30 秒内 `adb devices` 恢复 `device`，`adb shell` 可执行，
  无需人工重启服务，adbd 与 USB 服务循环进程数量不累积

#### Scenario: glibc 工作线程已经退出

- **WHEN** USB 工作线程已经退出，但 glibc 的 `pthread_kill(thread, 0)` 仍返回 0
- **THEN** 停止逻辑通过明确的完成状态结束等待并回收线程，后续连接清理继续执行

#### Scenario: USB 重连后 TCP 可重新连接

- **WHEN** TCP ADB 可用，USB 连接断开并重新建立
- **THEN** USB 清理不会使整个 adbd 长期无响应，即使内建恢复路径重启 adbd，TCP ADB 仍可重新连接并执行命令

### Requirement: 本地修复的预编译产物可追溯

携带本地修复的 arm64、armhf adbd SHALL 来自同一固定源码版本及同一 USB 修复补丁，并在 Docker（容器）内构建。
App 目录 MUST 保存补丁和说明，记录源码版本、构建方式、各架构 SHA256 摘要及实际验证范围。

#### Scenario: 核对新预编译产物

- **WHEN** 开发者检查 `components/app/adbd/` 中的预编译二进制
- **THEN** 能根据 README 找到对应源码版本、补丁和容器构建方式，文件摘要与记录一致，未实测的架构明确标注
