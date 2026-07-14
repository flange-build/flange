## 1. TinyUSB 配置与描述符

- [x] 1.1 将 esp_tinyusb 与 TinyUSB 锁定到支持 Full-Speed UAC1 的兼容版本
- [x] 1.2 新增项目级 `tusb_config.h` 并让 esp_tinyusb、TinyUSB 与 main target 使用一致的 Audio 配置
- [x] 1.3 扩展复合 USB device/config/string descriptor，加入 UAC1 AC/AS 接口与 Audio OUT endpoint

## 2. 扬声器数据链路

- [x] 2.1 新增 `uac_audio` 模块，初始化 GPIO41/42/43 上的 I2S standard TX
- [x] 2.2 实现 UAC control/interface callback 与固定 1 ms FIFO 消费、欠载补静音逻辑
- [x] 2.3 在 `app_main` 中按依赖顺序初始化音频模块并启动播放 task

## 3. 配置与文档

- [x] 3.1 关闭占用 GPIO43 的 UART0 console，并更新 CMake source 清单
- [x] 3.2 更新中文 README 的能力状态、日志变化与 Linux ALSA 枚举/播放验证步骤

## 4. 验证

- [x] 4.1 运行 OpenSpec 校验与源码静态检查，确认 descriptor 总长、接口数、endpoint 和格式常量一致
- [x] 4.2 使用 ESP-IDF 完成 firmware clean build；若本机环境缺失则记录可复现阻塞与待执行命令
- [ ] 4.3 在 Cardputer 实机验证 ALSA 播放、10 分钟连续音频及 GUD/HID 回归；无硬件时保留为待验证项
