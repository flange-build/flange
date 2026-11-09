## Why

ROCK 5B 的 SPI NOR（串行非易失闪存）可能残留旧启动固件，需要通过统一刷写入口清空。
现有 `flange flash` 仅提供系统分区刷写，缺少显式 SPI 擦除操作。

## What Changes

- 添加独立 `flange flash --erase-spi` 操作，复用 Rockchip 工具和设备发现流程。
- 显式切换到 SPINOR，确认选择结果后擦除整个 SPI；任一步骤失败立即停止。
- 与其他刷写操作互斥，支持等待控制，并拒绝与自动复位冲突的 --no-reboot，并更新测试和文档。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `flash-script`: 增加 Rockchip SPI NOR 独立擦除契约，覆盖 ROCK 5B。

## Impact

影响宿主机 `builder/flash/execute.py`、`builder/flash/strategy.py`、相关测试及刷写文档。
不改变构建产物、配置 schema 或缓存身份，不引入工具依赖。

## 非目标

不自动在普通刷写时清空 SPI，不擦除 eMMC/SD/UFS，不刷写新的 SPI 固件，不执行实机擦除。
