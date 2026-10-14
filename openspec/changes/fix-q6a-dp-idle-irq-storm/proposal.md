## Why

Q6A 在未连接显示器时，CPU 与 UFS（通用闪存存储）组合负载触发 CPU0 soft lockup（软锁死）。现场 DP（DisplayPort）中断风暴、停用 msm 后同参数压测成功及晚加载 msm 不触发风暴的证据，要求优先检查显示初始化与中断生命周期；当前不能把问题定性为 UFS 控制器故障。

## What Changes

- 保存可复现条件、内核调用路径、寄存器观测和对照压测结果。
- 验证并修正空闲 DP 控制器的显示流中断使能时机，保持 HPD（热插拔检测）与 AUX（辅助通道）可用。
- 使用 Docker 中的 flange 内核构建与实板压力测试验证候选补丁，明确未覆盖的显示场景。

## Capabilities

### New Capabilities

- `q6a-dp-idle-irq-lifecycle`：无显示流时屏蔽显示流中断，避免干扰 CPU 与 UFS 服务。

### Modified Capabilities

无。

## Impact

候选修改位于 Qualcomm 平台的 kernel patch，涉及 `drivers/gpu/drm/msm/dp/dp_ctrl.c`。不修改 UFS 时钟、电源管理或读写语义；诊断报告记录本地原始证据位置和临时规避方案。

## 非目标

- 不把禁用整个 msm、GPU 或 HDMI 作为通用产品默认配置。
- 不在没有显示器的条件下宣称已验证 HDMI 热插拔或显示输出。
- 不顺带修复 msm 卸载路径中另行捕获的 Oops（内核异常）。
