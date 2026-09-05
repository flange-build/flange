## Context

`pre_flash` 在 pyamlboot 返回后固定休眠 3 秒，随后允许 `oem format` 无限等待。用户首次调用卡住、中断重试成功，说明这个状态边界缺乏验证；目前不能仅凭日志确定具体 USB 驱动故障。现场只读检查中，宿主机 fastboot 33.0.2 的 `devices` 也发生 5 秒超时。

补充现场证据：串口日志已到达 U-Boot fastboot 入口；`crq->brequest:0x0` 来自 DWC2 `dwc2_udc_get_status` 的普通打印，并非错误分支。用户进一步确认仅 MacBook 的 USB-C to USB-C 连接触发首次卡住。它缩小了复现条件，但尚不能证明具体 Type-C 角色协商、线材或 USB 驱动原因；验收应包含这种连接方式的冷启动首刷。

## Goals / Non-Goals

目标：明确区分引导代码上传、USB 枚举、fastboot 通信就绪、持久写入；等待有界、失败可诊断。

非目标：修改板端固件或自动重放 GPT/分区写入。

## Decisions

1. 保留 Amlogic 策略作为协议边界。`pre_flash` 的两条入口都等待 `fastboot devices` 返回唯一设备，并执行 `fastboot -s <serial> getvar version`。本次构建使用的 U-Boot `drivers/fastboot/fb_getvar.c` 已实现该只读变量；成功退出且有版本响应才算就绪。仅增加休眠无法证明通信可用。
2. 使用 monotonic 时钟，整体等待 30 秒，每次枚举/握手最多 5 秒且受剩余总时限约束。失败仅重试只读探测，每次启动新进程，`subprocess.run` 负责超时终止与回收。
3. 策略只在握手成功时记录设备序列号，每次准备前清空；GPT、分区与重启命令要求这个就绪状态，并显式携带 `-s`。多个 fastboot 设备（含重复序列号）都拒绝继续。
4. GPT 控制命令设置 30 秒超时，超时表示设备端结果未知，停止后续流程且不重放。较长的镜像传输不套用这个短时限。
5. `--no-wait` 仅跳过最初的通用设备等待，不绕过持久写入前的协议握手。

## Risks / Trade-offs

- 设备可能在握手后断开：GPT 仍有超时兜底，分区传输保持原有工具行为。
- 模式切换硬件时序不能由模拟测试完全覆盖：使用模拟子进程验证超时回收与重试，实际冷启动首刷仍需现场复测。
- fastboot 序列号绑定不能证明板卡型号；本改动只保证会话设备不被其他序列号替换，不增加不存在的型号校验承诺。

## Migration Plan

源码更新后直接运行 `flange flash`。已有构建产物可复用，无需重建或更改环境。
