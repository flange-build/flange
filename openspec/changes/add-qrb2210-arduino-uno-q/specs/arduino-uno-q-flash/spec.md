## ADDED Requirements

### Requirement: 经校验的 QDL 发布包
系统 MUST 在宿主通过 QDL 向 UNO Q eMMC 刷写。发布包 MUST 含确定的固件、分区镜像、XML、GPT 和摘要清单。
刷写前 MUST 拒绝缺失文件、路径穿越、符号链接逃逸、摘要不符、镜像越界和不匹配容量。

#### Scenario: 必需镜像缺失
- **WHEN** XML 的非空 filename 指向不存在的文件
- **THEN** 在启动 QDL 前失败，不以 allow-missing 绕过检查

#### Scenario: 目标容量不匹配
- **WHEN** 已识别设备容量与发布布局不兼容
- **THEN** 拒绝写入并说明兼容容量，禁止隐式套用固定偏移

### Requirement: 分区级刷写与持久化保护
系统 MUST 使用同一计划支持 boot_a、boot_b、efi、rootfs 等真实分区名；默认保留官方无文件引用的持久化分区。
启动固件写入 MUST 遵守项目保护确认，多个或不能确认身份的设备 MUST 拒绝自动选择。

#### Scenario: 单刷 rootfs
- **WHEN** 用户选择 rootfs
- **THEN** 只执行该分区的写入，不重写 GPT、userdata、启动固件或校准数据

#### Scenario: 完整系统刷写
- **WHEN** 用户执行完整刷写
- **THEN** 所有写入来自验证后的计划，空 filename 区域不被清零

### Requirement: 可恢复验证
系统 MUST 保存实板容量、固件和分区身份及刷写验证记录，完成官方救援恢复验证后才声明刷写支持已验收。

#### Scenario: 未连接实板
- **WHEN** 只有离线编排测试通过
- **THEN** 实板刷写和恢复任务保持未完成，不将变更归档为已验收
