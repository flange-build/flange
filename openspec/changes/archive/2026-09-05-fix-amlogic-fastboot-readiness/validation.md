# 验证记录

## 证据与边界

- 用户日志：首次从 MaskROM 上传 U-Boot 后 `oem format` 等待，中断重试后 GPT、bootloader、boot 完成，rootfs 进入写入流程；不能据此宣布整机刷写与启动验收完成。
- 后续串口日志确认 U-Boot 2024.10、Khadas VIM3、A311D/G12B 已进入 fastboot。用户补充：仅 MacBook USB-C to USB-C 连接触发首次等待。
- 对照实际构建源码：`drivers/fastboot/fb_getvar.c` 提供只读版本变量；`drivers/usb/gadget/dwc2_udc_otg_xfer_dma.c` 的 `dwc2_udc_get_status` 打印 `crq->brequest:0x0`，该行不是错误判据。
- 修改前代码仅休眠 3 秒便写 GPT；现场只读 `fastboot devices` 检查曾超过 5 秒，由检查脚本终止。
- 修改后本机只运行就绪探测，30 秒内未枚举到 fastboot 设备，按预期报告超时并退出。未执行 U-Boot 上传、GPT、分区写入或重启；本次检查不能验证 C-to-C 冷启动恢复。

## 自动化验证

- 相关刷写测试：127 passed，3.93 秒。覆盖 Amlogic、Radxa Zero、通用执行器与 Rockchip 刷写回归。
- 真实假工具进程测试：首次 `getvar version` 休眠挂起，探测器终止并回收进程；第二次握手成功，原进程 PID 已不存在。
- 模拟延迟枚举、枚举与握手超时、空响应、命令失败、重复序列号、多设备、取消，以及 `--no-wait` 路径。
- 执行器验证：握手失败不写 GPT；GPT 失败或超时只调用一次，不继续写分区或重启。
- 新测试文件 Ruff 检查通过；既有文件不扩大历史 lint 问题。
- 归档并同步主规格后，严格规格校验 78 passed，治理测试 136 passed，`git diff --check` 通过。

## 待现场复测

使用触发问题的 C-to-C 连接，从 MaskROM 重新执行 `flange flash`，确认“fastboot 已就绪”后自动进入 GPT 和分区刷写，无需 Ctrl-C 重试。已有镜像无需重建。实际 Type-C/USB 驱动原因仍未由本次软件测试证明。
