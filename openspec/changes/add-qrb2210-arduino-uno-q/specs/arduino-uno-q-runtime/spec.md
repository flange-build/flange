## ADDED Requirements

### Requirement: 匹配的固件与板级初始化
系统 MUST 安装与所选 kernel/DTS 匹配的 Qualcomm/Atheros 固件、无线校准、相关用户态服务和启动成功标记。
固件 MUST 有固定来源、摘要及许可证；BDF 选择 MUST 使用实际板卡身份与 revision。

#### Scenario: 新旧 PCB 校准
- **WHEN** 系统初始化无线固件
- **THEN** 使用对应 revision 的 BDF，身份或 revision 无法确认时报告明确诊断

### Requirement: MCU 与 Bridge 完整工作流
系统 MUST 支持 arduino:zephyr:unoq 的 sketch 构建、上传、重启与 Linux/MCU 双向 RPC（远程过程调用）。
系统 MUST 保留正确用户、设备权限、Router 服务与 OpenOCD 控制配置，且不得因 rootfs 重刷无条件覆盖现有 sketch。

#### Scenario: 上传并执行
- **WHEN** 用户通过已验证的本地或 ADB 上传路径部署 sketch
- **THEN** MCU 执行目标程序，重启后仍能与 Linux 完成双向 RPC

### Requirement: App Lab 和 Bricks Ubuntu 兼容
系统 MUST 提供 App CLI、App Lab 和 Bricks 运行环境，固定软件、OCI 容器镜像及模型输入。
系统 MUST 验证 Ubuntu ARM64 二进制依赖与设备访问，禁止混入 Debian 系统库来绕过 ABI 不兼容。

#### Scenario: 完整应用闭环
- **WHEN** 用户在 App Lab 创建包含 Python、MCU 和 Brick 的应用
- **THEN** 应用可构建、上传、启动、停止并在重启后按配置恢复，日志可读取

#### Scenario: 缺失或不兼容运行时
- **WHEN** 必需依赖缺失或 ELF 要求的 ABI 不可满足
- **THEN** 构建或验证明确失败，不发布完整兼容的成功声明

### Requirement: 完整硬件验收
系统 MUST 记录 Wi-Fi、Bluetooth、USB 双角色、GPU/显示、音频、MCU、App Lab 和 Bricks 的实际验证结果。
实际连接的 CSI/DSI 配件 MUST 单独记录型号及测试结果。

#### Scenario: 硬件测试未通过
- **WHEN** 功能尚未验证或测试失败
- **THEN** 对应任务保留未完成或失败证据，不以驱动存在代替功能通过
