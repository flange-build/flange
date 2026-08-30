## 1. 平台与板级配置

- [x] 1.1 新增 `qualcommsc8280xp` 平台与 `sc8280xp` SoC 配置，锁定 kernel、UEFI、UFS 与 rootfs 输入
- [x] 1.2 新增 `radxa-dragon-q8b` 板级配置，声明 firmware 与 Radxa ALSA UCM deb
- [x] 1.3 新增 `firmware-qcom-audioreach` 本地固件包，由 flange 重打 deb 并让 Q8B 安装专用 topology
- [x] 1.4 新增 `radxa-q8b-fastrpc`，将参考 deb 内容重组为 flange runtime 与 debug test deb
- [x] 1.5 为 vendor App 增加 maintainer script 映射，并提供 Q8B FastRPC 专用安装/卸载脚本
- [x] 1.6 按 Radxa 官方包名拆分 `fastrpc`、ADSP/CDSP library、`fastrpc-test` 与 Q8B DSP runtime
- [x] 1.7 将 DSP runtime 独立为 `components/packages/radxa-firmware-sc8280xp` vendor package

## 2. 构建与刷写复用

- [x] 2.1 新增薄 builder 入口并把 `qualcommsc8280xp` 注册到既有 Qualcomm EDL 策略
- [x] 2.2 泛化共享 Qualcomm kernel inline config 解析与 GRUB board 标题

## 3. 自动化验证

- [x] 3.1 新增 Q8B 平台、SoC、board、lunch、firmware、镜像与刷写路由测试
- [x] 3.2 更新现有平台集合断言并验证 Q6A 行为不回归
- [x] 3.3 运行 OpenSpec 校验、目标解析、相关 pytest 与 Python 编译检查
- [x] 3.4 验证远端 kernel/DTB/firmware/UEFI 输入可访问，并执行可用环境下的构建级检查
- [x] 3.5 验证 package vendor deb 构建、内容哈希、Q8B 配置解析与 OpenSpec 一致性
- [x] 3.6 验证 FastRPC release/debug 选择、flange deb 内容、来源哈希与依赖闭包
- [x] 3.7 验证 maintainer script 路径边界、control.tar.gz 内容与 Q8B 服务范围
- [x] 3.8 验证拆分后的 deb 包名、依赖闭包、payload 所有权与 debug/release 选择
- [x] 3.9 验证独立 firmware package 的注册、官方同名 deb 与 FastRPC 依赖
