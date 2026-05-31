# boot-partition-rule Specification

## Purpose
TBD - created by archiving change 2026-03-29-phase6-image-flash. Update Purpose after archive.
## Requirements
### Requirement: boot_partition 框架 rule 定义
`build/boot_partition.bzl` SHALL 定义 `boot_partition` rule，采用框架+策略分离架构。框架负责输入管理和产物收集，策略脚本负责 extlinux.conf 生成、目录组装和 ext4 镜像打包。rule MUST NOT 硬编码任何平台特有参数。

#### Scenario: boot_partition rule 属性定义
- **WHEN** 查看 `boot_partition` rule 的 attrs 定义
- **THEN** 包含 `kernel`（Label，必选）、`dtbos`（Label，可选）、`build_script`（Label，必选）、`dts`（string，必选）、`dts_dir`（string，必选）、`default_overlays`（string_list）、`kernel_args`（string）、`boot_size_mb`（int，默认 256）

#### Scenario: boot_partition rule 不包含平台硬编码
- **WHEN** 审查 `build/boot_partition.bzl` 的实现
- **THEN** 不存在 `rockchip`、`allwinner`、`rk35`、`extlinux` 等平台特有字符串

### Requirement: boot_partition 环境变量契约
框架 SHALL 通过环境变量向策略脚本传递输入参数。

**框架 → 脚本（输入）：**
- `BOOT_KERNEL_IMAGE` — 内核镜像（Image）路径
- `BOOT_DTB` — 主 DTB 文件路径
- `BOOT_DTBOS_DIR` — DTBO 文件目录路径（可能为空）
- `BOOT_DTS` — DTS 名称（不含扩展名）
- `BOOT_DTS_DIR` — DTS 子目录名（如 rockchip）
- `BOOT_DEFAULT_OVERLAYS` — 空格分隔的默认启用 overlay 列表
- `BOOT_KERNEL_ARGS` — 内核启动参数字符串
- `BOOT_SIZE_MB` — boot 分区大小（MB）

**脚本 → 框架（输出）：**
- `BOOT_IMG_OUTPUT` — boot.img 绝对路径

#### Scenario: 策略脚本接收环境变量
- **WHEN** boot_partition 框架调用策略脚本
- **THEN** 脚本可通过 `$BOOT_KERNEL_IMAGE`、`$BOOT_DTB`、`$BOOT_DEFAULT_OVERLAYS` 等环境变量获取构建参数

#### Scenario: 策略脚本设置输出路径
- **WHEN** 策略脚本完成 boot.img 构建
- **THEN** `BOOT_IMG_OUTPUT` 指向生成的 boot.img 绝对路径

### Requirement: boot_partition 产出 boot.img
`boot_partition` rule SHALL 产出 `boot.img` 文件（ext4 格式），内部包含内核镜像、DTB、DTB overlay 和 extlinux.conf。

#### Scenario: boot.img 内容完整
- **WHEN** 挂载 boot.img 检查内容
- **THEN** 包含 `/Image`、`/dtb/<dts_dir>/<dts>.dtb`、`/extlinux/extlinux.conf`

#### Scenario: boot.img 包含 DTBO 文件
- **WHEN** board 配置指定了 `dtb_overlays` 且 dtbos.tar.gz 非空
- **THEN** boot.img 的 `/dtb/<dts_dir>/overlay/` 目录包含对应的 `.dtbo` 文件

### Requirement: extlinux.conf 使用 fdtoverlays 指令
策略脚本生成的 extlinux.conf SHALL 使用 `fdtoverlays` 指令声明默认启用的 DTB overlay。

#### Scenario: extlinux.conf 包含 overlay 配置
- **WHEN** `BOOT_DEFAULT_OVERLAYS` 为 `rockchip-i2c3 rockchip-spi1`
- **THEN** extlinux.conf 包含 `fdtoverlays /dtb/<dts_dir>/overlay/rockchip-i2c3.dtbo /dtb/<dts_dir>/overlay/rockchip-spi1.dtbo`

#### Scenario: 无 overlay 时不生成 fdtoverlays 行
- **WHEN** `BOOT_DEFAULT_OVERLAYS` 为空
- **THEN** extlinux.conf 不包含 `fdtoverlays` 行

### Requirement: boot_partition 使用 no-sandbox 执行
boot 分区构建需要 mkfs.ext4 和 mount 操作，SHALL 使用 `no-sandbox` 和 `no-remote` 执行要求。

#### Scenario: 执行模式
- **WHEN** 查看 `boot_partition` rule 的 `execution_requirements`
- **THEN** 包含 `"no-sandbox": "1"` 和 `"no-remote": "1"`

