## ADDED Requirements

### Requirement: RV1106 SoC 构建通路
系统 SHALL 提供 `rockchip/rv1106` SoC 配置，使用 ARM32 内核与 bootloader 架构、armhf 用户态，
复用 `rockchip-arm32-spinand-ubi` 路由生成 idblock、U-Boot FIT、内核 FIT `boot.img` 与 UBI rootfs；
MUST NOT 为 RV1106 新增仓库外源码依赖。

#### Scenario: 组件全部可构建
- **WHEN** 选择 `luckfox-pico-pro-max-default-release` 并执行 `flange build`
- **THEN** 产出 idblock、uboot、`boot.img` 与 `rootfs.ubi`
- **AND** 现有 Rockchip target 的 golden 序列不变

### Requirement: Luckfox Pico Pro/Max 板级启动
`luckfox-pico-pro-max` 板 SHALL 以 SPI NAND 为唯一启动介质，DTS `chosen.bootargs` MUST 指定
`console=ttyFIQ0`、`ubi.mtd=<rootfs 分区>` 与 `root=ubi0:rootfs rootfstype=ubifs`。
Pro（RV1106G2）与 Max（RV1106G3）SHALL 共用同一板级配置。

#### Scenario: 串口与网络
- **WHEN** 全量刷写后上电
- **THEN** 串口 `ttyFIQ0` 出现登录提示
- **AND** 板载百兆以太网可通过 DHCP 获取地址

#### Scenario: 分区几何显式
- **WHEN** 板级配置缺少 UBI NAND 几何任一字段
- **THEN** 构建在生成 UBI 前失败
