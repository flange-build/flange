# Q6A CPU 与 UFS 压测中的 DP 中断风暴

诊断日期：2026-10-14。设备的 RTC（实时时钟）会回退，日志关联以启动时长和测试名称为准。

## 当前结论

已复现 CPU0 soft lockup（软锁死），并通过寄存器单变量实验确认 DP（DisplayPort）的
STATUS2 显示流中断是持续中断的来源。停止该中断源后，UFS（通用闪存存储）吞吐显著恢复。
尚无证据证明此次软锁死由 UFS 控制器本身引起，也不能据此排除其他独立 UFS 问题。

候选修复为
[`0008-drm-msm-dp-gate-stream-irqs-with-clocks.patch`](../components/platform/qualcommqcs6490/patches/kernel/0008-drm-msm-dp-gate-stream-irqs-with-clocks.patch)。
显示输出与热插拔未验证；无显示器压测不能替代这些回归。

## 环境与复现参数

- Radxa Dragon Q6A，未接 HDMI/DP 显示器，8 核 CPU，约 7.5 GiB RAM，无 swap。
- 内核 `7.0.2+ #1 SMP PREEMPT_DYNAMIC`，配置与 flange 本地构建配置逐字节一致。
- 对应源码基线：radxa/kernel `7473a9fca2b08623319e497f4f811746baddb7bc`。
- 运行 Image SHA256：`b21add1218b51cb77570b292c504e4c9a3afcef632f39d352a68f1d9d9610a7e`。
  本地构建 Image 与设备 Image 不同，不以相同版本号冒充完全相同构建。
- UFS：Samsung KLUDG4UHGC-B0E1，固件 3203，rootfs 位于 sda2/ext4。
- fio 3.36：4 路任务，每路 512 MiB，direct I/O（直接 I/O），libaio，iodepth=32；
  随机测试为 4 KiB、读 70%/写 30%，顺序测试为 1 MiB、读写各 50%。
- CPU：`stress-ng --cpu 8 --cpu-method all --verify`。
- 仅在 `/var/tmp/q6a-ufs-*` 独立测试目录读写普通文件，无裸块设备写入。
- 宿主机持续保存 dmesg（内核日志）、温度、CPU 与块设备统计。
  脚本在任一 thermal zone（温度区域）达到 100°C 时停止负载。

## 压测对照

| 场景 | 结果 | 证据文件 |
|---|---|---|
| 8 核 CPU，60 秒 | 完成，未见 UFS 错误 | `01-cpu.log` |
| 原版随机 I/O，120 秒 | fio 无错误，读 5011 KiB/s、写 2163 KiB/s；ADB 明显迟滞 | `02-io-random.log` |
| 原版 CPU＋随机 I/O，目标 180 秒 | 未完成，CPU0 软锁死，ADB 卡住 | `03-combined-random.log`、`live-dmesg.log` |
| 干净启动禁用 msm，CPU＋随机 I/O，180 秒 | 完成，RESULT=0；读约 128 MiB/s、写约 54.7 MiB/s | `05-combined-no-msm.log` |
| 保留 msm，仅屏蔽 STATUS2，目标 180 秒 | 约 120 秒时温度保护停止，RESULT=125；fio 无错误，不能记为完整通过 | `06-combined-dp-masked.log` |
| 候选补丁，CPU＋随机 I/O，90 秒 | 完成，RESULT=0；读约 135 MiB/s、写约 57.8 MiB/s，DP 计数固定为 2 | `07-patched-random.log` |
| 候选补丁，CPU＋顺序 I/O，目标 60 秒 | 约 59 秒时触发温度保护，RESULT=125；未卡死，不能记为完整通过 | `08-patched-sequential.log` |
| 候选补丁，冷却后 CPU＋顺序 I/O，45 秒 | 完成，RESULT=0；读约 258 MiB/s、写约 268 MiB/s，DP 计数固定为 2 | `09-patched-sequential-45s.log` |

禁用 msm 的对照无新增 UFS PHY、链路、DME、fatal、abort 或 host reset 错误。
Logical Unit Resets 从启动起为 1，测试后仍为 1。
仅屏蔽 STATUS2 的测试期间，中断计数固定，未出现新的软锁死或 UFS 错误。
该轮 `ufs-thermal` 达到 100016 毫摄氏度后主动停止，随后 CPU 温度下降快于该传感器；
传感器读值的校准与物理温度对应关系未独立核验，不应擅自放宽保护阈值。

原始证据位于工作区 `BUILD_ROOT/diagnostics/q6a-ufs-20261014/`，属本地诊断产物，
不随 Git 自动分发。`04-combined-no-msm.log` 为空，是先前异常内核中的未启动测试，
不计入有效结果。`live2-dmesg.log` 的卸载 Oops 属单独问题，不与原始软锁死混淆。

## 从现场到内核代码

原始软锁死发生于启动后 804 秒。CPU0 连续 22 秒未正常调度，hardirq（硬中断）占用约 90%，
看门狗列出的最频繁中断为 IRQ178，共 1395386 次；该次启动的 `/proc/interrupts`
将其映射为 `msm_mdss 12 dp_display_isr`。IRQ 编号会随重启变化，必须按处理程序名称识别。

代码路径为：

1. `drivers/gpu/drm/msm/msm_mdss.c:msm_mdss_irq()` 分发 DP 子中断。
2. `dp/dp_display.c:msm_dp_display_irq_handler()` 调用控制器中断处理。
3. `dp/dp_ctrl.c:msm_dp_ctrl_isr()` 调用 `msm_dp_ctrl_get_interrupt()`。
4. 原版 `msm_dp_ctrl_get_interrupt()` 写回 ACK（确认位）时总是附带完整
   `DP_INTERRUPT_STATUS2_MASK`，无论当前是否存在显示流。
5. `msm_dp_display_host_init()` 只开启 core clocks（核心时钟），即调用
   `msm_dp_ctrl_enable_irq()` 开启 STATUS2；未连接显示器时 link/pixel 时钟均关闭。

在风暴状态只读寄存器得到：

| 寄存器 | 地址 | 读值 |
|---|---|---|
| AUX 中断状态与使能 | `0xae90020` | `0x24924920` |
| STATUS2 | `0xae90024` | `0x1000092d` |
| HPD 状态 | `0xae90204` | `0` |
| HPD 掩码 | `0xae9020c` | `0xf` |

STATUS2 的 bit0（video_ready）和 bit3（idle_pattern_sent）持续存在。
只向 STATUS2 写零后读值为 `0x10000009`，状态位仍在，使能位 `0x924` 已清零。
DP 计数在 5 秒内保持 3412755 不变，AUX 与 HPD 寄存器不变。
重新写回 `0x924`，1 秒增加 57552 次中断；再次屏蔽后计数固定为 3470318。
见 `clean5-mask-status2.txt`、`clean5-toggle-status2.txt`。

这确认了可屏蔽的中断源。残留位究竟来自固件状态、复位还是时钟交接尚未证明。
干净启动禁用 msm，等启动完成后手动加载原版模块时，STATUS2 为 `0x924`、DP 计数为 0，
说明初始化时序影响复现。不能将这一现象直接写成已经证明的固件缺陷。

## 候选修复与验证边界

- STATUS2 的使能跟随 link 与 pixel 时钟，关闭任一组时钟前先屏蔽。
- 链路重训练重新开启 link 时钟时，根据 pixel 时钟状态恢复使能。
- 自旋锁串行化掩码切换和 ISR，ACK 使用当前掩码，仅上报使能的状态。
- 启用流中断前，在相关时钟已开启的状态下确认残留事件。
- AUX/HPD 的处理和 UFS 的电源、频率、命令路径保持不变。

构建命令：`flange --target radxa-dragon-q6a-default-debug build kernel`，编译在 Docker 内执行。
`checkpatch.pl --no-tree --no-signoff` 检查本地补丁；未代替用户添加 Signed-off-by 签署。

已构建并部署单个 msm 模块，未替换运行 Image、DTB 或其他模块。补丁模块 SHA256：
`ef0e13b015882678d7f7f0a4fae1224befbe3562d8e1327bbc80047dbb966f4c`。
设备 `/sys/module/msm/notes/.note.gnu.build-id` 与候选文件均为
`b7bc76b9f2e1bf37637ef583f312dea8363c23be`，确认实际加载了候选代码。
双方 vermagic 为 `7.0.2+ SMP preempt mod_unload aarch64`，无强制加载。

正常重启后没有诊断黑名单，DP 共 2 次中断，STATUS2 为 `0x10000009`；
原有状态位仍在，流中断使能位已清零，AUX/HPD 状态与使能保持原值。
内核 taint（污染标记）仍为 4096，仅有原先的外部模块标记，没有新增 Oops 标记。
补丁下 90 秒随机 I/O 完整通过，CPU 平均空闲约 0.095%，最高温度读数为
`ufs-thermal` 的 99.202°C；DP 计数始终为 2，UFS 错误计数未增加。
60 秒顺序测试在 fio 运行约 58.8 秒时触发 100.086°C 温度保护，读约 248 MiB/s、写约
255 MiB/s，没有软锁死或新增 UFS 错误，但未完整通过。冷却后 45 秒顺序测试完整通过，
读约 258 MiB/s、写约 268 MiB/s，最高温度读数为 99.382°C，最终 DP 仍共 2 次中断。
UFS 错误计数保持为零，Logical Unit Resets 保持启动基线 1。
显示输出、热插拔、链路重训练、PSR 和挂起恢复仍需显示设备验收。
持续更长时间的满载验证受到温度限制，需要改善散热或独立核验传感器读数，不能把本次短测当成长稳测试。

## 回滚与临时规避

设备原 msm 模块 SHA256：
`f88381cb6067200659fb85fe268f5b8a3a19e9a290dcdd68b7c565537383e400`，
宿主机备份为上述证据目录中的 `msm-original.ko.zst`。
设备备份为 `/var/lib/q6a-ufs-diagnostic/msm-original.ko.zst`。
回滚时将它恢复到 `/lib/modules/7.0.2+/kernel/drivers/gpu/drm/msm/msm.ko.zst`，
运行 `depmod -a`、`sync` 后重启；不要在线卸载 msm。

无显示用途的设备可通过 modprobe 黑名单阻止 msm 开机加载，再重启实现临时隔离；
这会关闭 GPU/显示，不能作为默认产品修复。测试所用文件为
`/etc/modprobe.d/q6a-ufs-diagnostic.conf`，内容为 `blacklist msm` 和 `install msm /bin/false`。
恢复时删除此临时文件并重启。不要在线 `modprobe -r msm`：本次排查已在
`adreno_remove()` 和 DRM 自刷新工作项中捕获卸载 Oops。

直接写寄存器只用于上述受控实验，重启或电源管理会改变它，不能充当持久修复。

## 交付状态

- 设备保留修复后的 msm 模块和原模块备份，正常开机自动加载，无诊断黑名单。
- 已清理日志明确记录的 7 个测试目录，共 14 GiB 文件；rootfs 可用空间约 87 GiB。
- 已停止本次日志采集并删除 `/run` 下测试脚本；fio 与 stress-ng 保留供后续复测。
- Docker 构建成功，checkpatch 无错误或警告，OpenSpec 严格校验通过。
- 原始证据、两版模块和构建日志留在本地诊断产物目录；OpenSpec 变更未归档，显示回归任务仍待验收。
