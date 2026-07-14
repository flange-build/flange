## 1. USB Audio 描述符与配置

- [x] 1.1 扩展接口、endpoint 和格式常量，加入 UAC1 麦克风 AudioStreaming IN
- [x] 1.2 把 AudioControl topology 改为同一 UAC1 function 下的扬声器与麦克风双流
- [x] 1.3 开启 TinyUSB Audio EP IN FIFO，并保持现有 EP OUT 配置一致

## 2. PDM 采集与半双工仲裁

- [x] 2.1 增加 GPIO46 麦克风数据引脚，并把扬声器 TX 固定到 I2S1、麦克风 RX 固定到 I2S0
- [x] 2.2 初始化 mono 16 kHz / 16 bit PDM RX，并实现 1 ms PCM 帧上传
- [x] 2.3 实现受保护的最后启动优先状态机、GPIO reconfig 和方向切换 FIFO 清理
- [x] 2.4 扩展 TinyUSB interface callback，处理扬声器与麦克风 alt setting 生命周期

## 3. 集成与文档

- [x] 3.1 更新启动日志和中文注释，反映 UAC1 playback/capture 半双工能力
- [x] 3.2 更新 README 的接口布局、硬件引脚、半双工约束及 ALSA 录音验证命令

## 4. 验证

- [x] 4.1 运行 OpenSpec 校验与源码静态检查，确认描述符长度、接口数和 endpoint 一致
- [x] 4.2 使用 ESP-IDF 完成 firmware clean build
- [x] 4.3 在 Cardputer 实机验证 ALSA 录音、方向切换和 GUD/HID/扬声器回归；无硬件连接时保留为待验证项
