## Context

现有 Rockchip 策略已提供 DB（下载引导程序）与 SSD（切换存储）封装。
仓库附带工具手册 §1.8 限定 EL（扇区擦除）只支持 eMMC，因此使用 EF（全片擦除）及当前目标的 miniloader。

## Goals / Non-Goals

目标：为 ROCK 5B 提供独立 SPI NOR 全片擦除命令；能力以 Rockchip 策略和设备 SPINOR 支持判断。
非目标：不改构建配置，不自动刷系统，不执行实机操作。

## Decisions

- `--erase-spi` 与分区名、`--raw`、`--list`、`--spi-firmware`、`--provision-ufs` 互斥。
- 执行器验证策略能力和 loader 文件后再等待设备；无需系统分区镜像。
- MaskROM（芯片下载模式）下先 DB，Loader 模式复用已有 loader；无法识别设备时停止。
- 校验 SoC 身份，但不套用系统盘的 storage_patterns，因为本操作面向另一存储介质。
- SSD 显式选择 SPINOR，并再次读取 SSD 列表确认激活标记；失败不执行 EF。
- SSD 列表查询输入 Q 正常退出时可能返回非零值，查询成功以列表项和激活标记为准；
  `SSD <编号>` 的实际切换仍要求零退出码。ROCK 5B 用户日志已复现该退出码行为。
- `EF <miniloader>` 擦除选定介质。实机日志确认 EF 自带复位，因此不得追加 RD；`--no-reboot` 在访问设备前拒绝。
- `--no-wait` 仅跳过轮询，保留一次设备检测及多设备拒绝。
- 不使用固定 SPI 容量或零填充镜像，不使用仅支持 eMMC 的 EL。

## Risks / Trade-offs

- SPI 原有启动固件会丢失：帮助与文档明确这是独立全片擦除操作。
- 工具版本或 loader 不支持 SPINOR：列表读取、切换和激活标记检查失败时中止，不回退默认介质。
- mock（模拟）测试无法证明 USB 和实际擦除效果：标注仍需 ROCK 5B 实机验收。

## Migration Plan

现有 flash-config 可直接使用；无需重建系统。移除选项即可回到既有命令行为。
