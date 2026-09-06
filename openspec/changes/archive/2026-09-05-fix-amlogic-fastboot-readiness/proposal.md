## Why

Khadas VIM3 首次从 MaskROM 上传 U-Boot 后，`flange flash` 卡在 `fastboot oem format`，中断重试才恢复。当前实现以固定 3 秒休眠代替 fastboot 就绪检查，且 GPT 命令没有超时，USB 模式切换期间的等待被错误地呈现为正在写分区。

## What Changes

- 上传 U-Boot 后，以及复用已有 fastboot 设备时，先有界等待 USB 枚举并执行只读通信握手。
- 后续命令绑定握手成功的唯一设备序列号，多设备时拒绝继续。
- 握手失败时停止在写入前；GPT 命令超时后明确报告结果未知，不自动重放写命令。
- 同步使用说明、项目规格和回归测试。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `amlogic-flash`：声明 fastboot 就绪门槛、设备绑定与 GPT 操作超时。

## Impact

宿主机 Amlogic 刷写策略及其测试、文档；不新增依赖，无需重建已有镜像。

## 非目标

不修改 U-Boot 固件、分区布局、rootfs 镜像格式或其他平台的刷写协议；不自动重试持久写入命令。
