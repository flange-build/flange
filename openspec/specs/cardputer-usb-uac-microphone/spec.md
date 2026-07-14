# cardputer-usb-uac-microphone Specification

## Purpose

规定 Cardputer firmware 的 USB Audio Class 1（USB 音频类版本 1，UAC1）麦克风能力：使用板载 SPM1423 PDM 麦克风提供固定格式的 USB 录音流，并在共享 GPIO43 的约束下与既有 UAC1 扬声器进行半双工仲裁，同时保持复合设备其他功能兼容。

## Requirements

### Requirement: UAC1 麦克风枚举

firmware MUST 在现有 UAC1 Audio Function 中提供独立的 microphone AudioStreaming IN 接口，格式固定为
mono 16 kHz、16 bit PCM，并由标准 USB Audio Class host driver 枚举为 capture PCM。

#### Scenario: Linux 枚举录音设备

- **WHEN** Cardputer 通过 native USB 连接支持 UAC1 的 Linux host
- **THEN** `snd-usb-audio` 提供一个支持 `S16_LE`、mono、16000 Hz 的 ALSA capture PCM

### Requirement: 板载 PDM 麦克风采集

firmware MUST 使用 GPIO43 作为 SPM1423 PDM clock、GPIO46 作为 PDM data，通过 ESP32-S3 I2S PDM RX
硬件转换为 mono 16 bit PCM，并连续写入 UAC Audio IN FIFO。

#### Scenario: host 录制麦克风

- **WHEN** host 把麦克风 AudioStreaming interface 切换到 alt setting 1 并读取 capture PCM
- **THEN** firmware 以每 1 ms 32 byte 的帧从板载麦克风采集并向 host 上传音频数据

### Requirement: 扬声器与麦克风半双工仲裁

firmware MUST 保证共享 GPIO43 的扬声器 I2S WS 与麦克风 PDM clock 不会同时启用，并 MUST 采用最后启动的
AudioStreaming 方向优先的切换规则。

#### Scenario: 播放期间开始录音

- **WHEN** 扬声器正在 streaming 且 host 启动麦克风 streaming
- **THEN** firmware 先停止扬声器 I2S TX，再把 GPIO43 切换为 PDM clock 并启动麦克风采集

#### Scenario: 录音结束后恢复播放

- **WHEN** host 在两个方向均保持打开后关闭当前麦克风 streaming，而扬声器仍为 alt setting 1
- **THEN** firmware 停止 PDM RX 并自动恢复扬声器 I2S TX

### Requirement: 复合设备兼容性

增加麦克风后 firmware MUST 保持 GUD vendor interface、UAC1 扬声器和 HID keyboard 的既有 endpoint 地址与
功能行为，并为麦克风分配不冲突的 isochronous IN endpoint。

#### Scenario: 麦克风启用后的复合设备枚举

- **WHEN** host 完成 USB configuration
- **THEN** GUD、UAC1 playback、UAC1 capture 与 HID 全部成功枚举且 endpoint 地址不冲突

### Requirement: 停流与 FIFO 清理

firmware MUST 在录音 stream 关闭或方向切换时停止对应 I2S channel，并清理目标方向的 TinyUSB FIFO，避免
上传切换前的旧样本或播放旧数据。

#### Scenario: 关闭录音流

- **WHEN** host 把麦克风 AudioStreaming interface 切换回 alt setting 0
- **THEN** firmware 停止 PDM RX，清理 Audio IN FIFO，并进入 idle 或恢复仍被请求的扬声器方向
