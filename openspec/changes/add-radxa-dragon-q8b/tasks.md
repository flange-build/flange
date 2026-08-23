## 1. 平台与板级配置

- [x] 1.1 新增 `qualcommsc8280xp` 平台与 `sc8280xp` SoC 配置，锁定 kernel、UEFI、UFS 与 rootfs 输入
- [x] 1.2 新增 `radxa-dragon-q8b` 板级配置，声明 firmware 与 Radxa ALSA UCM deb

## 2. 构建与刷写复用

- [x] 2.1 新增薄 builder 入口并把 `qualcommsc8280xp` 注册到既有 Qualcomm EDL 策略
- [x] 2.2 泛化共享 Qualcomm kernel inline config 解析与 GRUB board 标题

## 3. 自动化验证

- [x] 3.1 新增 Q8B 平台、SoC、board、lunch、firmware、镜像与刷写路由测试
- [x] 3.2 更新现有平台集合断言并验证 Q6A 行为不回归
- [x] 3.3 运行 OpenSpec 校验、目标解析、相关 pytest 与 Python 编译检查
- [x] 3.4 验证远端 kernel/DTB/firmware/UEFI 输入可访问，并执行可用环境下的构建级检查
