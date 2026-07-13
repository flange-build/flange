## ADDED Requirements

### Requirement: AMP builder 按 SoC 解析架构、BSP 与 DTS

Rockchip AMP builder SHALL 从配置读取 `soc_project`、目标 CPU、kernel arch、DTS 路径和
RT-Thread BSP 映射。RK3506 SHALL 映射到 ARM32 `rk3506-32` BSP 和
`arch/arm/boot/dts`；既有 RK3566/RK3568 映射 MUST 保持不变。

#### Scenario: RK3506 RT-Thread BSP 被正确选择
- **WHEN** `amp.soc_project=rk3506` 且 `amp.mode=rt-thread`
- **THEN** builder stage `bsp/rockchip/rk3506-32`
- **AND** 使用配置声明的 CPU2 与 RK3506 内存布局

#### Scenario: DTS 一致性检查不再写死 RK3568
- **WHEN** 为 RK3506B 执行 AMP DTS 校验
- **THEN** 从目标 ARM32 DTS include 链读取 RK3506 AMP reserved-memory/RPMsg 数据
- **AND** 不访问 `arch/arm64/.../rk3568-amp.dtsi`

### Requirement: AMP FIT 渲染只修改目标 firmware image 节点

AMP FIT renderer SHALL 按目标 CPU image 节点名称修改从核 firmware 的 `load`、`size` 及
incbin，不得用全文件正则替换其他 image 或 configuration 的同名属性。渲染发生在临时目录，
不得修改 vendored SDK/RT-Thread ITS。

#### Scenario: RK3506 amp2 load 被修改且 Linux load 保留
- **WHEN** 渲染含 `images/amp2.load=0x03e00000` 和
  `configurations/conf/linux.load=0x00900000` 的 ITS
- **THEN** `amp2` 节点与 FINAL_CONFIG 一致
- **AND** Linux load 仍为 `0x00900000`

#### Scenario: 找不到目标节点时失败
- **WHEN** ITS 不含由目标 CPU 推导的 firmware image 节点
- **THEN** builder 在调用 mkimage 前失败并指出缺失节点

### Requirement: RK3506 AMP FIT 保持 ARM32 Linux 加单从核结构

RK3506 `amp.img` SHALL 是合法 FIT，包含 CPU2 ARM firmware 和 CPU0 Linux 启动描述，且
loadable 仅引用 CPU2 固件。固件 load/size、MPIDR 和 SRAM SHALL 与配置及 DTS 一致。

#### Scenario: fdtget 检查 RK3506 amp.img
- **WHEN** 对构建出的 RK3506 `amp.img` 执行 FIT 结构检查
- **THEN** `amp2.arch=arm`、`amp2.cpu=0xf02`、`amp2.load=0x03e00000`
- **AND** configuration 的 Linux CPU 为 `0xf00` 且 load 为 `0x00900000`
