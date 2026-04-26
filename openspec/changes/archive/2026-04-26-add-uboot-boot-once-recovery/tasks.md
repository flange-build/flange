## 1. Boot 分区 extlinux 布局

- [x] 1.1 修改 Rockchip boot builder，生成 `extlinux.conf` 与 `recovery.conf`
- [x] 1.2 修改 Allwinner A733 boot builder，生成 `extlinux.conf` 与 `recovery.conf`
- [x] 1.3 更新 extlinux 单元测试，覆盖 normal/recovery 配置隔离

## 2. Bootloader 启动选择

- [x] 2.1 为 Rockchip U-Boot 新增补丁：根据 `BOOT_MODE_RECOVERY` 选择 `recovery.conf`
- [x] 2.2 在补丁中支持并消费 `flange_boot_once=recovery`
- [x] 2.3 修改 distro boot sysboot 路径，使用 `flange_extlinux_conf`
- [x] 2.4 添加静态校验，确保 bootloader 补丁被构建系统纳入应用

## 3. recoveryctl 行为调整

- [x] 3.1 新增直接调用 Linux `reboot(2)` restart2 的 helper
- [x] 3.2 新增 `recoveryctl recovery` / `loader` / `normal` 子命令
- [x] 3.3 保留 `recoveryctl reboot [target]` 兼容入口
- [x] 3.4 保留 `flange_boot_once=recovery` 作为显式持久兜底，不再作为默认路径
- [x] 3.5 移除正常流程中的 extlinux DEFAULT fallback

## 4. 宿主机 CLI 与文档

- [x] 4.1 修改 `flange recovery enter/reboot` 调用链，使用新的设备端入口
- [x] 4.2 更新 `ProjectSpec.md` 的 USB 线刷 Recovery 章节
- [x] 4.3 更新 `docs/recovery.md`、`README.md` 和 `envsetup.sh` 说明
- [x] 4.4 记录 A733 平台 reboot reason / U-Boot 选择逻辑待实机验证状态

## 5. 验证

- [x] 5.1 更新 `tests/builder/test_recoveryctl.py`
- [x] 5.2 更新 `tests/builder/test_recovery_host.py`
- [x] 5.3 更新 bootloader 补丁静态测试
- [x] 5.4 运行 recovery 相关单元测试
- [x] 5.5 在具备设备时执行 RK3566 实机验证：normal → recovery → normal
