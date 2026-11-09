## 1. SoC 通路

- [x] 1.1 新增 rv1106 SoC 配置，核实 rkbin INI、trust 模式与 U-Boot defconfig，bootloader 构建通过（≤2小时）
- [x] 1.2 内核 `rv1106_defconfig` + NAND/UBI/以太网/USB gadget Kconfig，zImage 与 FIT 构建通过（≤2小时）

## 2. 板级

- [x] 2.1 移植 `rv1106g-luckfox-pico-pro-max.dts`（基础外设 + UBI bootargs）（≤2小时）
- [ ] 2.2 板级配置：分区、UBI 几何、flash_identity、最小 Ubuntu 默认 product，`flange build` 全量产物生成（≤2小时）

## 3. 验证与文档

- [ ] 3.1 实机刷写：串口登录、以太网 DHCP、USB gadget 枚举，结论写入 verification.md（用户目测）（≤2小时）
- [ ] 3.2 wiki 板卡页与板卡索引、README 板卡列表（≤2小时）
