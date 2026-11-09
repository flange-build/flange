# UNO Q 实板 Bridge 验证

`bridge_validation/bridge_validation.ino` 提供 `flange.echo` 回显，并每秒通过
`flange.tick` 向 Linux 发送递增计数。固定 core 0.90.0、RouterBridge 0.4.3 编译通过。
该 sketch 不操作外部引脚，但上传会替换用户现有 MCU 程序，必须先确认允许替换。

`verify_bridge.py` 在能访问 `/run/arduino-router.sock`、安装 msgpack 的 Linux 环境中运行，
例如 UNO Q 的 Arduino Python App 容器。它注册通知处理接口，并在 15 秒内验证三次回显和
至少三个连续 MCU 计数。脚本只通信，不执行刷写，也不把 Router 版本查询当作 MCU 验证。

注意：官方 `flash_sketch.cfg` 会校验 Zephyr 基础固件，内容不匹配时一并重写。
执行上传前必须确认实际写入范围；不要将“未调用 burn-bootloader”等同于“只写 sketch 区”。

按用户要求，最终 MCU 上传及实板验收留在烧入阶段执行；当前 sketch 仅已编译通过。

`collect_runtime.py` 在宿主使用 ADB 只读采集板卡、槽位、服务、网络和日志，需明确指定
`--serial` 与 `--output`。它先核对板卡 compatible，报告不会把设备枚举等同于完整功能通过。
