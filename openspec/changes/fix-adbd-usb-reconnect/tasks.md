## 1. 修复共享 USB 线程清理

- [x] 1.1 检查全部工作线程返回及停止调用路径，保存显式完成状态的最小源码补丁（预计 1 小时）。
- [ ] 1.2 运行 `tests/adbd_usb_reconnect.py --allow-pid-change` 实机回归，验证旧版失败、新版无需人工重启且在 30 秒内恢复（预计 30 分钟）。

## 2. 构建与追溯

- [x] 2.1 在 Docker 内按固定源码与补丁构建 arm64 静态 adbd，核对架构、静态链接与摘要（预计 1 小时）。
- [x] 2.2 在 Docker 内按同一源码与补丁构建 armhf 静态 adbd，核对架构、静态链接与摘要（预计 1 小时）。
- [x] 2.3 更新两个预编译二进制及 README，记录补丁、构建命令、摘要和实际验证边界（预计 30 分钟）。

## 3. 设备部署与验收

- [ ] 3.1 备份目标设备旧 adbd，部署 arm64 修复并确认 SSH、USB ADB、TCP ADB 可用（预计 30 分钟）。
- [ ] 3.2 连续执行 `soft_connect` 断开/恢复，验证 USB shell、TCP 重新连接及 daemon/loop 无泄漏，记录循环次数及结果（预计 30 分钟）。
- [ ] 3.3 请用户物理插拔数据线，确认 ADB 自动恢复并记录结果（预计 10 分钟，需用户配合）。

## 当前验证记录（2026-08-31）

- 旧版实机回归：一次断连后等待 8 秒仍为 `offline`；修复版连续 9 轮自动恢复 USB shell。
- 第 10 轮时 GDM（图形登录管理器）触发系统挂起，USB 与 SSH 同时不可达；已请用户唤醒，
  10 轮完整回归、TCP 恢复、进程数量及物理插拔验收仍待继续，不能将休眠中断记为通过。
- 设备 `/usr/bin/adbd` 已替换为修复版；原文件与日志备份在
  `/var/tmp/flange-adb-reconnect-before/`，未修改 USB 脚本或长期电源配置。
- `flange build app adbd` 成功，生成的 arm64 deb 内二进制摘要与修复版一致；
  `tests/builder/test_adbd_service.py` 4 项通过，OpenSpec 严格校验及 `git diff --check` 通过。
