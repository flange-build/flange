## 1. 适配基线

- [x] 1.1 根据原理图与 ADB 确认 CH334R、RTL8733BUUA、USB interface class 与 VID:PID
- [x] 1.2 对比原厂 SDK 和 `linux-6.1-stan-rkr5.1`，确认 driver/firmware contract 与固定 source commit

## 2. 板级实现

- [x] 2.1 删除 AP6256 DTS patch、SDIO/UART5/BCMDHD 配置与 Broadcom firmware
- [x] 2.2 配置 RTL8733BU WiFi、Realtek USB Bluetooth OOT module 与两份同源 firmware
- [x] 2.3 更新配置、module alias、firmware 来源和“零 WiFi/BT DTS patch”自动化测试

## 3. 静态与构建验证

- [x] 3.1 运行 ATK-RK3506B 配置测试、相关 builder regression 与 OpenSpec 校验
- [x] 3.2 增量构建 kernel/rootfs/boot/image，核对最终 config、OOT module、modalias、firmware 与 UBI size

## 4. 实机验收

- [x] 4.1 刷写设备并验证冷启动、CH334R/RTL8733BUUA 枚举、`8733bu` 自动加载与 WLAN interface
- [ ] 4.2 验证 2.4/5 GHz scan、测试 AP association 与 IP connectivity
- [ ] 4.3 验证 `rtk_btusb` 自动加载、RTL8733BU firmware、HCI controller、BlueZ discovery 与 reboot 后自动恢复
- [ ] 4.4 回归 GMAC、UART4 MSH、RPMsg 与 ADB，确认 USB 无线适配未破坏既有功能

## 5. 文档与证据

- [x] 5.1 更新 ATK-RK3506B Wiki，记录 USB topology、software stack、使用方法和 troubleshooting command
- [x] 5.2 将静态构建与实机验收结果写入 change evidence，并同步任务状态
