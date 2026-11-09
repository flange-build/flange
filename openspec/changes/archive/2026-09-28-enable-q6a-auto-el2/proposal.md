## Why

Radxa Dragon Q6A 只有在 EL2 下才同时具备 ADSP/CDSP（UEFI 预加载、内核接管）与 venus 硬件编码；EL1 下编码
喂帧即整机复位。目前进 EL2 依赖用户手动在 UEFI 把 `Hypervisor Override` 设为 `Enabled`，wiki 一直把
「flange 默认 EL2」列为待解项。

Radxa UEFI 的该选项出厂为 `Auto`：根据 Linux 设备树 `/chosen/radxa,enable-kvm` 决定是否进 EL2，并在
EL2 时预加载 DSP。Radxa 官方开启 KVM 的方式正是叠加内核自带的 `qcs6490-radxa-dragon-q6a-kvm.dtso`
（含该属性与 EL2 所需的设备树修正），不需要进 UEFI。flange 采用同一份 DTB 即可让 Q6A 开箱进 EL2。

## What Changes

- `radxa-dragon-q6a` 的 `kernel.device_tree.name` 由 `qcs6490-radxa-dragon-q6a` 改为内核 Makefile 已构建的
  组合 DTB `qcs6490-radxa-dragon-q6a-kvm`（base DTB + Radxa KVM overlay：`/chosen/radxa,enable-kvm = <1>`、
  GPU zap 禁用、ADSP/CDSP `qcom,broken-reset`、SCM SHM bridge、venus `video-firmware`、PCIe 窗口）。
- `meizu-e3-bringup` 的面板 overlay 改为合并到该组合 DTB 上。
- 更新测试、wiki 与规格中 Q6A 的 DTB 名称。

## 非目标

- 不支持 UEFI `Hypervisor Override = Disabled`（强制 EL1）：组合 DTB 的 EL2 修正在 EL1 下会使 GPU 与视频
  不可用。`Auto`（出厂默认）与 `Enabled` 均支持。
- 不改 SPI 固件、UEFI 变量或刷写流程；不涉及 RUBIK Pi 3。
- 不验证 DSP 崩溃恢复（EL2 下由内核经 PAS 重载，已知未验证）。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `qcs6490-mainline-kernel`：新增「Q6A 默认以 EL2 启动」要求。
- `meizu-e3-panel`：`meizu-e3-bringup` product 的面板 overlay 合并目标改为 KVM 组合 DTB。

## Impact

- `components/board/radxa-dragon-q6a/config.jsonnet`（DTB 名与注释）。
- `tests/config/test_qcs6490_jsonnet.py`、`tests/config/test_canonical_matrix.py`。
- `wiki/boards/radxa-dragon-q6a.md`、`wiki/log.md`；顺带更正板页中「RUBIK Pi 3 能编码只因 QLI 默认 EL2」
  的错误表述。
- 已部署的 Q6A 需重新刷写 rootfs 才生效；UEFI 保持 `Auto` 即自动进 EL2。
