## ADDED Requirements

### Requirement: 经校验的 QDL 发布包
系统 MUST 在宿主通过 QDL 向 UNO Q eMMC 刷写。发布包 MUST 含确定的固件、分区镜像、XML、GPT 和摘要清单。
刷写前 MUST 拒绝缺失文件、路径穿越、符号链接逃逸、摘要不符、镜像越界和不匹配容量。

#### Scenario: 必需镜像缺失
- **WHEN** XML 的非空 filename 指向不存在的文件
- **THEN** 在启动 QDL 前失败，不以 allow-missing 绕过检查

#### Scenario: 使用仓库自带宿主工具
- **WHEN** 用户在 macOS 或 Linux 的 ARM64、x86_64 宿主执行刷写
- **THEN** 系统可直接选择仓库内对应架构的固定版本 QDL，无需另行下载或重建镜像
- **AND** 工具随附来源、版本、SHA256 和上游许可证，保留既有本地覆盖及 PATH 回退

#### Scenario: 目标容量不匹配
- **WHEN** 已识别设备容量与发布布局不兼容
- **THEN** 拒绝写入并说明兼容容量，禁止隐式套用固定偏移

#### Scenario: macOS 浏览发布包
- **WHEN** Finder 在发布包中生成未列入 manifest 的普通 `.DS_Store` 文件
- **THEN** 文件集合校验忽略此元数据，不改变任何镜像摘要或刷写计划
- **AND** 其他额外文件、缺失文件及 `.DS_Store` 符号链接仍被拒绝，并报告差异路径

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

### Requirement: 刷写进度可见
系统 MUST 在交互终端实时转发 QDL 分区进度，并持续保存日志；校验与 GPT 读取 MUST 有阶段提示。

#### Scenario: 正在写入大镜像
- **WHEN** QDL 尚未退出但已输出分区进度
- **THEN** 终端与日志均立即得到输出，不等待整个刷写结束

#### Scenario: 写入失败或超时
- **WHEN** QDL 非零退出或超过时限
- **THEN** 保留已产生的日志并报告日志路径，回收子进程且不自动重试
