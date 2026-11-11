# Q6A 的 DP 中断风暴与 UFS 压测

适用范围：2026-10-14，Radxa Dragon Q6A、未连接显示器、radxa/kernel 7.0.2 固定提交
`7473a9fca2b08623319e497f4f811746baddb7bc`、Samsung KLUDG4UHGC-B0E1 UFS（固件 3203）。
[板卡用法](../boards/radxa-dragon-q6a.md)

## 故障与处理

CPU 与文件 I/O 同时施压时，DP（DisplayPort）STATUS2 显示流中断持续触发，CPU0 hardirq 占用约 90%，
最终出现 soft lockup（软锁死）与 ADB 迟滞。停止该中断源后吞吐恢复。
该实验确认中断风暴的来源，没有证明 UFS 控制器有缺陷，也不能排除其他独立存储问题。

仓库补丁 [0008-drm-msm-dp-gate-stream-irqs-with-clocks.patch](../../components/platform/qualcommqcs6490/patches/kernel/0008-drm-msm-dp-gate-stream-irqs-with-clocks.patch)
让 STATUS2 使能跟随 link/pixel 时钟，自旋锁串行化 ISR 与掩码变更，ACK 使用当前掩码；
保留 AUX/HPD 处理和 UFS 的电源、频率及命令路径。

```bash
flange --target radxa-dragon-q6a-default-debug build kernel
```

目标编译在 Docker 完成。正常产品更新使用生成的匹配内核与模块；下述实验只替换了 msm 模块，
不能将其结果扩大为整个新系统镜像的验收。

## 已确认的机制

原代码在没有显示流时仍由 host_init 开启 STATUS2，中断 ACK 又总附带完整使能掩码。
未连接显示器时 link/pixel 时钟关闭，STATUS2 的 video_ready 与 idle_pattern_sent 状态持续存在。
受控单变量实验中，清除 `0xae90024` 的使能位 `0x924` 后 DP 计数停止，AUX/HPD 不变；
恢复使能后每秒增加约 5.8 万次中断。状态残留究竟由固件、复位还是时钟交接产生尚未证明。

按 `/proc/interrupts` 的 `dp_display_isr` 名称定位，IRQ 数字会随启动变化。
不要把直接写寄存器当作持久修复；重启及电源管理都会改变状态。

## 验证结果

fio 3.36 使用普通测试文件：4 路、每路 512 MiB、direct I/O、libaio、iodepth 32；
随机测试为 4 KiB / 读 70%，顺序测试为 1 MiB / 读写各半，同时运行 8 核 stress-ng。
达到 100°C 传感器读数时停止；传感器校准未独立核验，不应自行放宽阈值。

| 场景 | 结论 |
| --- | --- |
| 原版 CPU + 随机 I/O | 未完成，CPU0 软锁死 |
| 干净启动禁用 msm，随机 I/O 180 秒 | 完成，读约 128 / 写约 54.7 MiB/s |
| 修复模块，随机 I/O 90 秒 | 完成，读约 135 / 写约 57.8 MiB/s，DP 中断固定为 2 |
| 修复模块，顺序 I/O 目标 60 秒 | 约 59 秒温度保护停止，未卡死；不计为完整通过 |
| 冷却后修复模块，顺序 I/O 45 秒 | 完成，读约 258 / 写约 268 MiB/s，DP 中断固定为 2 |

修复模块的 build-id `b7bc76b9f2e1bf37637ef583f312dea8363c23be` 与设备一致；
vermagic 匹配，无强制加载。UFS 错误计数未增加，Logical Unit Resets 保持启动基线 1。
Docker 构建与 checkpatch 通过；这些短时结果不能代替长稳测试。

## 使用限制与回退

显示输出、热插拔、链路重训练、PSR 和挂起恢复未验证。长时间满载还受散热限制。
回退时使用与运行内核匹配的原模块或重新部署原完整内核，执行 depmod 后重启。
不要在线卸载 msm：该基线已观察到 adreno_remove / DRM 自刷新工作项中的卸载 Oops。
无显示用途时可临时禁用 msm 后重启隔离问题，但会失去 GPU/显示功能。

原始日志与两版模块属于本地构建诊断产物，不随仓库分发；读者无需这些临时文件即可使用上述补丁和判断边界。
