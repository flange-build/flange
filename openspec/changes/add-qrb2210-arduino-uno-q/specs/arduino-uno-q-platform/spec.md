## ADDED Requirements

### Requirement: UNO Q 配置与内核构建
系统 MUST 发现 arduino-uno-q 的 default debug/release 目标，固定 QRB2210 的 ARM64 kernel 输入，在 Docker 中构建 Image、最终板级 DTB 和匹配 modules。

#### Scenario: 目标规划
- **WHEN** 选择 arduino-uno-q-default-debug
- **THEN** 规划器生成隔离于其他板卡和变体的组件计划并包含源码版本及配置身份

#### Scenario: 最终设备树
- **WHEN** 使用官方 7.0 基线构建 kernel
- **THEN** 输出合成后的 qrb2210-arduino-imola.dtb，包含标准 USB-C 视频音频路由

### Requirement: 启动组件准确映射
系统 MUST 分离 U-Boot Android 容器和 Linux EFI 系统分区，完整声明固件、Image、DTB、modules 与 initrd 的依赖和必需产物。

#### Scenario: 独立 boot 构建
- **WHEN** 用户只构建 boot 且必要上游尚未构建
- **THEN** 系统先构建所需上游，不读取未声明的 rootfs/initrd 或旧目标产物

#### Scenario: 固件不完整
- **WHEN** 启动固件摘要错误或必需 loader 不存在
- **THEN** 构建失败并保留上一成功发布

### Requirement: Ubuntu 与用户数据镜像
系统 MUST 使用项目 Ubuntu-base 构建 rootfs，并按选定布局生成独立 userdata，保证 fstab、EFI 启动项和文件系统身份一致。

#### Scenario: 用户目录持久化
- **WHEN** 用户使用保留用户数据的系统更新路径
- **THEN** 计划不覆盖 userdata，系统启动后继续挂载原 Arduino 用户目录
