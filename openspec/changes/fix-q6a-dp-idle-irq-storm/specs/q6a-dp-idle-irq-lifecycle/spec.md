## ADDED Requirements

### Requirement: 空闲控制器屏蔽显示流中断

Q6A 的 DP 驱动 MUST 在 link 或 pixel 时钟关闭时屏蔽 STATUS2 显示流中断，同时保留正常 HPD 和 AUX 中断处理。

#### Scenario: 无显示器启动
- **WHEN** 未接显示器启动系统且显示流未开启
- **THEN** STATUS2 的显示流中断使能位为零，DP 中断不持续增长

### Requirement: 中断确认遵循当前掩码

ISR MUST 使用当前流中断掩码确认状态，且掩码切换与 ISR 的寄存器写操作必须串行化。

#### Scenario: 中断与流关闭并发
- **WHEN** 显示流中断处理与关闭时钟并发发生
- **THEN** 时钟关闭前流中断被屏蔽，后续 ISR 不得重新使能它

### Requirement: 活跃显示流保留完成通知

驱动 MUST 在 link 和 pixel 时钟均可用后启用显示流中断，保留 video_ready 与 idle_pattern 的完成通知。

#### Scenario: 启动或重训练显示流
- **WHEN** 流时钟已开启且准备发送视频
- **THEN** 驱动能收到有效的视频就绪事件，关闭时能收到有效的空闲完成事件

### Requirement: 压测结论可追溯

诊断报告 MUST 分开记录原始故障、隔离实验、候选补丁测试和未验证场景。

#### Scenario: 无显示器完成组合负载
- **WHEN** 8 核 CPU 与 4 路 UFS 文件读写测试完成
- **THEN** 记录持续时间、退出码、中断计数和 UFS 错误，且不据此宣称显示输出回归已通过
