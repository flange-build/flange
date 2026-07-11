## 1. SDK 同步与兼容

- [x] 1.1 同步 Rockchip RT-Thread 4.1.1 vendor 树
- [x] 1.2 恢复 RK3568 UART7、GIC IRQ 与 rpmsg-lite platform 兼容
- [x] 1.3 适配 serial control 与 rpmsg-lite 4.1.1 API

## 2. 构建与配置

- [x] 2.1 调整 staging 以容忍断链子模块并显式复用 HAL SDK
- [x] 2.2 增加 flange RT-Thread AMP 平台基线及内容哈希
- [x] 2.3 关闭 Orange Pi CM4 app 的 GMAC1 与 UART2 冲突默认项

## 3. 验证

- [x] 3.1 增加配置合并、serial 生命周期与板级资源回归测试
- [x] 3.2 构建并检查最终配置、ELF/map 和 amp.img
- [x] 3.3 上板验证 UART7 banner、MSH、RPMsg channel 与双向 echo

## 4. 文档与收尾

- [x] 4.1 更新 AMP wiki，记录完整升级问题、根因与排障方法
- [x] 4.2 同步 delta spec 到 canonical spec 并通过严格校验
