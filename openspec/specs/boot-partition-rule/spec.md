# boot-partition-rule Specification

## Purpose

定义 Python boot builder 组装 ext4 boot 分区的跨平台输入与输出契约。

## Requirements

### Requirement: boot builder 使用 canonical 配置

boot builder MUST 从 `kernel.device_tree.{directory,name}`、
`boot.kernel_args` 与 `boot.overlays.{intree,vendor,board,package,enabled}` 读取
构建输入，不得解释平台专属设备树或 overlay alias。

#### Scenario: 组装基础 boot.img

- **WHEN** kernel 已产出 Image 与目标 DTB
- **THEN** boot.img 包含 `/extlinux/Image`、`/dtbs/<vendor>/<name>.dtb` 和 `/extlinux/extlinux.conf`

#### Scenario: 组装运行期 overlay

- **WHEN** 四个 overlay 来源数组声明了 `.dtbo`
- **THEN** boot builder 将对应文件复制到 `/dtbs/<vendor>/overlay/`

### Requirement: extlinux 使用 enabled 顺序

`boot.overlays.enabled` MUST 是四个来源数组并集的有序子集；boot builder MUST
按该顺序生成 `fdtoverlays`，引用不存在的文件 MUST 在镜像生成前报错。

#### Scenario: 多 overlay

- **WHEN** enabled 为 `["i2c.dtbo", "spi.dtbo"]`
- **THEN** extlinux 的 `fdtoverlays` 按 i2c、spi 顺序引用两者

#### Scenario: 空 enabled

- **WHEN** enabled 为空
- **THEN** extlinux 不生成 `fdtoverlays` 行

### Requirement: boot.img 构建在 Docker 内执行

ext4 镜像创建与文件注入 MUST 通过平台 boot ComponentBuilder 在 Docker 构建
环境内完成，输出收集为 `target/.../boot/boot.img`。

#### Scenario: 构建 boot 分区

- **WHEN** 执行 boot 组件构建
- **THEN** ext4 创建与文件注入在 Docker 构建环境内完成
- **AND** 产物收集为 `target/<board>/<product>/<variant>/boot/boot.img`

#### Scenario: 产物缺失

- **WHEN** boot 组件的 `.build_hash` 有效但 `boot.img` 不存在
- **THEN** 缓存判定为未命中并重建
