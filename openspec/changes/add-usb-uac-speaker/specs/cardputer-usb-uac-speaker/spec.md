## ADDED Requirements

### Requirement: UAC1 扬声器复合枚举
Cardputer firmware MUST 在保留 GUD Vendor 接口和 HID 键盘接口的同时，暴露一个由 AudioControl 与
AudioStreaming 接口组成的 UAC1（USB Audio Class 1，USB 音频类 1）扬声器功能。设备描述符 MUST 使用
IAD（Interface Association Descriptor，接口关联描述符）兼容的 Miscellaneous device class。

#### Scenario: Linux 主机枚举复合设备
- **WHEN** Cardputer 通过 native USB 连接到启用 `snd-usb-audio`、`gud` 和 `usbhid` 的 Linux 主机
- **THEN** 主机同时创建 ALSA playback PCM、GUD DRM 设备和 HID input 设备

### Requirement: 固定的语音级 PCM 格式
UAC1 AudioStreaming 接口 MUST 只公布 mono 16 kHz / 16 bit little-endian PCM 播放格式，isochronous OUT
端点的每帧最大负载 MUST 与该格式的 32 bytes/ms 数据率一致。

#### Scenario: 查询 ALSA 硬件参数
- **WHEN** 用户通过 `aplay --dump-hw-params` 查询 Cardputer playback PCM
- **THEN** 主机报告 1 channel、16000 Hz 与 `S16_LE` 格式可用

### Requirement: USB 音频播放到板载扬声器
firmware MUST 从 UAC isochronous OUT FIFO 取出 PCM 数据，通过 I2S standard TX 输出到板载 NS4168，
并使用 GPIO41 作为 BCLK、GPIO42 作为 DOUT、GPIO43 作为 WS。

#### Scenario: 播放 16 kHz 单声道 PCM
- **WHEN** Linux 主机向 Cardputer ALSA playback PCM 连续播放有效的 mono 16 kHz / 16 bit 音频
- **THEN** Cardputer 板载扬声器持续发声，firmware 不重启且 GUD/HID 功能保持可用

### Requirement: 欠载安全处理
firmware MUST 在 USB 音频 FIFO 暂时无足够样本或停止 streaming 时向 I2S 写入静音数据，且 MUST NOT
重放旧缓冲内容或访问越界内存。

#### Scenario: 主机停止播放
- **WHEN** 主机把 AudioStreaming interface 切回 alternate setting 0 或停止发送音频包
- **THEN** 扬声器输出在有限缓冲排空后变为静音，设备保持正常枚举

### Requirement: GPIO43 冲突消除
启用 UAC 扬声器时 firmware MUST NOT 把 GPIO43 同时配置为 UART0 TX 与 I2S WS，运行日志 MUST 改走
不占用扬声器引脚的输出方式或明确关闭 UART0 控制台。

#### Scenario: 音频启动后的引脚所有权
- **WHEN** firmware 完成 I2S 扬声器初始化
- **THEN** GPIO43 仅由 I2S TX 外设驱动，不存在 UART0 与 I2S 的复用争用
