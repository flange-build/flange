# image-build-rule Specification

## Purpose
TBD - created by archiving change 2026-03-29-phase6-image-flash. Update Purpose after archive.
## Requirements
### Requirement: image_build 框架 rule 定义
`build/image_build.bzl` SHALL 定义 `image_build` rule，采用框架+策略分离架构。框架负责组件产物聚合和最终镜像收集，策略脚本负责分区表创建、镜像组装等平台特有逻辑。rule MUST NOT 硬编码任何平台特有参数。

#### Scenario: image_build rule 属性定义
- **WHEN** 查看 `image_build` rule 的 attrs 定义
- **THEN** 包含 `boot`（Label，必选）、`bootloader`（Label，必选）、`rootfs`（Label，必选）、`build_script`（Label，必选）、`partition_config`（Label，可选）

#### Scenario: image_build rule 不包含平台硬编码
- **WHEN** 审查 `build/image_build.bzl` 的实现
- **THEN** 不存在 `rockchip`、`rkdeveloptool`、`parameter.txt`、`idbloader` 等平台特有字符串

### Requirement: image_build 环境变量契约
框架 SHALL 通过环境变量向策略脚本传递输入参数。

**框架 → 脚本（输入）：**
- `IMAGE_BOOT` — boot.img 路径
- `IMAGE_BOOTLOADER_DIR` — bootloader 产物目录路径（包含 idbloader.img、u-boot.itb 等）
- `IMAGE_ROOTFS` — rootfs.tar.gz 路径
- `IMAGE_PARTITION_CONFIG` — 分区配置文件路径（如 parameter.txt，可能为空）

**脚本 → 框架（输出）：**
- `IMAGE_OUTPUT` — raw.img 绝对路径

#### Scenario: 策略脚本接收环境变量
- **WHEN** image_build 框架调用策略脚本
- **THEN** 脚本可通过 `$IMAGE_BOOT`、`$IMAGE_BOOTLOADER_DIR`、`$IMAGE_ROOTFS` 等环境变量获取产物路径

#### Scenario: 策略脚本设置输出路径
- **WHEN** 策略脚本完成镜像打包
- **THEN** `IMAGE_OUTPUT` 指向生成的 raw.img 绝对路径

### Requirement: image_build 产出 raw.img
`image_build` rule SHALL 产出 `raw.img` 文件，为完整磁盘镜像，包含分区表和所有分区数据，可通过 dd 命令直接写入存储设备。

#### Scenario: raw.img 可直接刷写
- **WHEN** 将 raw.img 通过 `dd if=raw.img of=/dev/sdX` 写入 SD 卡
- **THEN** 目标设备可正常启动

### Requirement: image_build 使用 no-sandbox 执行
镜像打包需要 losetup、mount、mkfs 等操作，SHALL 使用 `no-sandbox` 和 `no-remote` 执行要求。

#### Scenario: 执行模式
- **WHEN** 查看 `image_build` rule 的 `execution_requirements`
- **THEN** 包含 `"no-sandbox": "1"` 和 `"no-remote": "1"`

### Requirement: image_collect 收集产物
`build/image_collect.bzl` SHALL 定义 `image_collect` rule，将镜像构建产物收集到 `target/<board>/image/` 目录。

#### Scenario: 产物目录结构
- **WHEN** 执行 `bazel run //image:collect --config=radxa-zero3w`
- **THEN** `target/radxa-zero3w/image/` 目录包含 `raw.img` 和策略脚本产出的各组件镜像文件

