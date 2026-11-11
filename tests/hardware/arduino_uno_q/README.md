# UNO Q 实板 Bridge 验证

本目录提供 MCU/Linux 双向 RPC（远程过程调用）验证与只读运行信息采集。
整体环境、上传方式和实测范围见[UNO Q 板卡文档](../../../docs/boards/arduino-uno-q.md)。

## Bridge 测试

`bridge_validation/bridge_validation.ino` 提供 `flange.echo` 回显，每秒通过
`flange.tick` 向 Linux 发送递增计数，使用 core 0.90.0、RouterBridge 0.4.3。
上传会替换 MCU 程序；官方 `flash_sketch.cfg` 还会检查 Zephyr 基础固件，不匹配时一起重写。
执行前按板卡说明核对实际写入范围。

在已加载测试 sketch、能访问 `/run/arduino-router.sock` 且安装 msgpack 的 Linux 环境中，
运行 `python3 verify_bridge.py`，例如把该文件放入板上官方 Python App 容器后执行。
脚本注册通知接口，在 15 秒内检查三次回显和至少三个连续 MCU 计数；成功时打印“双向 Bridge 通过”的结果行。
它不执行刷写，不以 Router 版本查询代替 MCU 通信。

2026-11-08，UNO Q 4GB/32GB、`default-debug`、官方 python-apps-base 0.12.0 已完成上传与实测：
三次回显正确，计数为 18、19、20；Router 重启后约 6 秒恢复通信。此结果不覆盖 PC 端 ADB/网络上传。

## 只读运行信息采集

`collect_runtime.py` 在宿主使用 ADB（Android 调试桥）采集板卡、槽位、服务、网络和日志，
必须指定 `--serial` 与 `--output`。可先运行 `python3 collect_runtime.py --help` 查看参数。
脚本先核对板卡 compatible；报告中的设备枚举不等于完整功能验收。
