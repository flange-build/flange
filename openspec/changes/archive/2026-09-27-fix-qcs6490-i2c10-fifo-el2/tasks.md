## 1. 内核 patch

- [x] 1.1 基于内核源 `7473a9f` 的 `arch/arm64/boot/dts/qcom/qcs6490-radxa-dragon-q6a.dts`，编写 `components/platform/qualcommqcs6490/patches/kernel/0007-dts-radxa-dragon-q6a-i2c10-drop-gsi-dma.patch`：删除 `&i2c10` 的 `qcom,enable-gsi-dma`；patch 头写中文说明（EL2 下 GPII MSI 寄存器同步中止的根因、依赖 `0006`）
- [x] 1.2 更新 `0006` 的 patch 说明与代码注释：由"仅命中 i2c13/SE5"改为"命中所有 DT 未声明 GSI 的 i2c SE"，diff 代码行不变
- [x] 1.3 在干净源码树上按序 `git apply --check` 0001–0007，确认零冲突

## 2. 构建与产物核对

- [x] 2.1 `flange build`（radxa-dragon-q6a-default-debug），构建成功
- [x] 2.2 反编译产物 DTB，确认 `i2c@a88000` 与 `i2c@a94000` 均不含 `qcom,enable-gsi-dma`，其余节点与修改前一致（仅差这一个属性）

## 3. 实板验证（EL2）

- [x] 3.1 `flange flash` 刷入镜像（SPI 保持 `260120`），UEFI `Hypervisor Override` 开启，不加启动参数启动：`started at EL2`、`/dev/kvm` 存在、`i2c_qcom_geni` 加载无 Oops/SError、到达 rootfs
  - 实板（2026-09-27）：刷写 3337 MiB/15.9 s；cmdline 无 `module_blacklist`；`CPU: All CPU(s) started at EL2`、`/dev/kvm` 在、`/chosen` 含 `radxa,enable-kvm`；活动 DT 中 `i2c@a88000`/`i2c@a94000` 均无 `qcom,enable-gsi-dma`；`systemctl --failed` 为空
- [x] 3.2 RTC 验证：`/dev/rtc*` 存在，`hwclock -r` / `hwclock -w` 成功；`dmesg` 无 `gpi` 通道相关报错
  - 实板：`rtc-ds1307 10-0068: registered as rtc0`；镜像无 `hwclock`，改用 `RTC_SET_TIME`/`RTC_RD_TIME` ioctl 与 sysfs：写入前 `date` 为 `EINVAL`（RTC 从未设时，非 i2c 错误），写入后读回 `2026-09-27 04:50:41`，8 s 后 sysfs 读 `04:50:49` 与宿主一致；`dmesg` 无 `gpi`/`GPI transfer`/Oops/SError，`/proc/interrupts` 无 `gpi-dma`（GPI 未被使用）
- [ ] 3.3 （可选）关闭 `Hypervisor Override` 以 EL1 启动同一镜像，确认启动与 RTC 正常
  - 未执行（可选项，归档时跳过）：EL1 下 FIFO 路径与 i2c13 相同，但本构建未单独实板复验；wiki 已注明

## 4. 文档

- [x] 4.1 更新 `wiki/boards/radxa-dragon-q6a.md`：EL2 下 GPI 中止根因、UEFI 自行套用 KVM fixup 的机制、i2c10 改走 FIFO；frontmatter sources 补 `0007`；`wiki/log.md` 追加条目
- [x] 4.2 `openspec validate fix-qcs6490-i2c10-fifo-el2` 通过
