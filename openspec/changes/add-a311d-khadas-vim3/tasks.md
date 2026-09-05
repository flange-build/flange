## 1. 配置实现

- [x] 1.1 提取 VIM3/VIM3L 共享 Jsonnet 数据，并确认 VIM3L canonical 语义不变
- [x] 1.2 新增 A311D SoC 配置与 VIM3 板级 fastboot fragment
- [x] 1.3 新增 Khadas VIM3 board 配置、SPI dtso 与 rootfs overlay
- [x] 1.4 修正 Amlogic bootloader builder，直接收集 build-fip 已生成的四件产物

## 2. 测试与文档

- [x] 2.1 更新 target 基数并增加 VIM3 canonical 构建输入断言
- [x] 2.2 更新 README、板卡索引和 Amlogic/VIM3 wiki 文档
- [x] 2.3 校正 amlogic-platform 产物映射与 amlogic-flash 板级刷写契约

## 3. 验证

- [x] 3.1 运行配置、Amlogic builder/flash 与平台测试
- [x] 3.2 运行 OpenSpec strict 校验并记录 V14 实板验收边界
