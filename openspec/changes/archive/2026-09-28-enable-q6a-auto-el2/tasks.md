## 1. 配置与测试

- [x] 1.1 `radxa-dragon-q6a` 的 `device_tree.name` 改为 `qcs6490-radxa-dragon-q6a-kvm`，更新注释说明 UEFI `Auto` 行为与不支持 `Disabled`
- [x] 1.2 更新 `tests/config/test_qcs6490_jsonnet.py` 与 `tests/config/test_canonical_matrix.py` 的 Q6A DTB 断言，运行相关测试

## 2. 构建与实板

- [x] 2.1 构建 `radxa-dragon-q6a-meizu-e3-bringup-debug`，确认产物 DTB 的 `/chosen/radxa,enable-kvm` 为 1、面板 overlay 合并成功
- [x] 2.2 UEFI `Hypervisor Override` 设为 `Auto` 后刷写启动：确认 `/dev/kvm`、ADSP/CDSP `attached`、硬件编码不复位、面板显示正常（用户目视）

## 3. 文档

- [x] 3.1 更新 `wiki/boards/radxa-dragon-q6a.md`（默认 EL2 已解决、不支持 `Disabled`、更正「RUBIK Pi 3 能编码只因 QLI 默认 EL2」）与 `wiki/log.md`

实板记录（2026-09-28，meizu-e3-bringup-debug，UEFI `Hypervisor Override = Auto`）：用户自行验证通过。
