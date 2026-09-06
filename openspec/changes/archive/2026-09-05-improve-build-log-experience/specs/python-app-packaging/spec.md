## MODIFIED Requirements

### Requirement: App 字段 MUST 具有严格类型与实际运行消费者

AppSpec MUST 拒绝未知字段、重复 YAML 键和隐式类型转换，支持架构仅为 aarch64/armhf。
exec/test MAY 声明 runtime.executable 为目标绝对路径，默认 /usr/bin/<name>；构建 MUST 在安装清单中确认入口存在且可执行。
service MUST 声明 systemd.unit，data_dirs 仅允许用于 service；lib.dev_suffix 控制开发包后缀。
无消费者 capabilities 与 lib.headers_dir MUST 被移除，头文件经 install staging、include 约定或显式 install 映射交付。

#### Scenario: 字符串布尔值拒绝
- **WHEN** systemd.auto_start 写成字符串 false
- **THEN** AppSpec 指出字段要求布尔值，不转换为 true

#### Scenario: 自定义运行入口缺失
- **WHEN** runtime.executable 指向安装清单之外的文件
- **THEN** 构建拒绝发布可运行成功结果

#### Scenario: 重复 YAML 键
- **WHEN** app.yaml 重复声明 runtime 或其他键
- **THEN** 加载失败，不让后写的值覆盖前值

#### Scenario: recoveryctl 使用系统管理命令目录

- **WHEN** recoveryctl 的安装清单把可执行脚本交付到 /usr/sbin/recoveryctl
- **THEN** AppSpec 显式声明 runtime.executable 为 /usr/sbin/recoveryctl，构建报告与安装清单使用相同路径
- **AND** aarch64/armhf 的最小打包验证保留该运行入口与执行权限，不通过关闭校验绕过默认路径差异
