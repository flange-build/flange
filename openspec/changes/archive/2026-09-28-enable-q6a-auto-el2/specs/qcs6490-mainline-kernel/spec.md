## ADDED Requirements

### Requirement: Q6A 默认以 EL2 启动

`radxa-dragon-q6a` 的全部目标 MUST 使用内核构建的组合 DTB `qcs6490-radxa-dragon-q6a-kvm`（base DTB 叠加 Radxa
`qcs6490-radxa-dragon-q6a-kvm.dtso`），其 `/chosen` MUST 含 `radxa,enable-kvm = <1>`。在 UEFI
`Hypervisor Override` 为出厂 `Auto` 时，系统 MUST 以 EL2 启动，ADSP/CDSP MUST 由 UEFI 预加载后被内核接管，
venus 硬件编码 MUST 可用。系统 MUST NOT 要求用户进入 UEFI 修改该选项。

#### Scenario: 配置使用 KVM 组合 DTB

- **WHEN** 求值任一 `radxa-dragon-q6a` 目标
- **THEN** `kernel.device_tree.name` 为 `qcs6490-radxa-dragon-q6a-kvm`，构建产物 DTB 的 `/chosen/radxa,enable-kvm` 为 1

#### Scenario: UEFI Auto 下自动进 EL2

- **WHEN** UEFI `Hypervisor Override` 为 `Auto`，刷写后启动
- **THEN** `/dev/kvm` 存在，ADSP 与 CDSP remoteproc 为 `attached`，720p NV12 H.264 硬件编码不复位
