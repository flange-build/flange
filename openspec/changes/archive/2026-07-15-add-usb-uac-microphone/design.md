## Context

当前 firmware 的单个 UAC1 Audio Function 仅包含 AudioControl 与一个扬声器 AudioStreaming OUT
接口。板载 SPM1423 使用 PDM（脉冲密度调制）输出，DAT 接 GPIO46、CLK 接 GPIO43；GPIO43 又是
NS4168 扬声器的 I2S WS，因此硬件不能同时录音和播放。

ESP32-S3 的 PDM RX 只能使用 I2S0，现有扬声器可迁移到 I2S1。TinyUSB 0.21 的单个 Audio Function
同时支持 isochronous OUT 与 IN FIFO，适合把两个方向放入同一个 UAC1 功能而不增加第二个 Audio
driver instance。

## Goals / Non-Goals

**Goals:**

- 让 Linux `snd-usb-audio` 枚举 mono 16 kHz / 16 bit capture PCM。
- 把 SPM1423 PDM 数据通过 ESP32-S3 硬件 PDM-to-PCM filter 转成 PCM 并上传。
- 保持现有扬声器格式及 GUD/HID 功能不变。
- 对 GPIO43 实施可预测、无电气争用的半双工切换。

**Non-Goals:**

- 不支持 simultaneous playback/capture（同时播放与录音）。
- 不实现音量、静音、自动增益、降噪或回声消除 control。
- 不增加新的采样率或声道格式。

## Decisions

### 1. 一个 UAC1 Audio Function 包含两个 AudioStreaming 接口

AudioControl 接口声明两个 streaming interface：扬声器 AS OUT 和麦克风 AS IN。两条 topology
分别为 USB Streaming → Speaker，以及 Microphone → USB Streaming，entity ID 不重复。IAD 覆盖三个
接口，TinyUSB 仍配置为一个 Audio Function。

备选方案是创建第二个独立 UAC function，但这会需要第二个 TinyUSB Audio driver instance，并让 control
callback、FIFO 与配置宏成倍增加，不符合当前简单固定格式需求。

### 2. 麦克风使用 I2S0 PDM RX，扬声器固定使用 I2S1 standard TX

麦克风以 16 kHz、16 bit、mono PCM 模式初始化 I2S0 PDM RX，GPIO43 输出 PDM clock，GPIO46 输入
PDM data。扬声器改用 I2S1，格式和 GPIO41/42/43 保持不变。两个 channel 启动时初始化，但默认均不
enable。

### 3. 使用“最后启动的 stream 优先”的半双工状态机

TinyUSB interface callback 记录扬声器和麦克风 alt setting 请求。新的 alt=1 请求成为目标方向；当前方向
先 disable，再重新配置目标 channel 的 GPIO matrix，最后 enable 目标方向。若当前方向关闭而另一方向
仍保持 alt=1，则恢复另一方向；两者都关闭时进入 idle。

切换实际动作由音频 task 执行，USB callback 只更新受 critical section 保护的目标状态，避免在 USB control
上下文中执行 I2S driver 操作。切换时清空目标 TinyUSB FIFO，防止播放旧数据或上传切换前样本。

备选方案是在第二个方向打开时 stall USB control request，但 ALSA 对被拒绝 alt setting 的恢复行为不一致，
也无法自然恢复已打开的另一方向。

### 4. 单一音频 task 按 1 ms 帧搬运两个方向

播放方向维持现有 USB FIFO → I2S write，并在欠载时补零。录音方向每次从 PDM RX 读取 32 byte PCM，
再调用 `tud_audio_write()` 写入 IN FIFO；FIFO 空间不足时丢弃未写入的当前帧，不阻塞 USB task。

## Risks / Trade-offs

- [host 同时打开 playback 与 capture 时只能有一个方向工作] → 文档明确半双工，并采用最后启动优先、
  关闭后自动恢复另一方向的确定规则。
- [GPIO matrix 在两个已初始化 channel 间残留路由] → 每次 enable 前调用对应 reconfig GPIO API，且严格先
  disable 当前 channel。
- [PDM FIFO overflow 或 USB IN FIFO overflow 造成丢样] → 使用固定 1 ms DMA 帧和多帧软件 FIFO，溢出时
  丢弃单帧而不累积时延。
- [不同 host 对 UAC1 组合 topology 的解析差异] → 使用标准 AC header、独立 terminal pair 与固定格式，
  并保留 Linux `lsusb -v`/ALSA 实机验证任务。

## Migration Plan

1. 扩展描述符和 TinyUSB Audio IN 配置。
2. 增加 PDM RX channel 与半双工状态机，clean build 验证。
3. 刷写实机，用 ALSA 分别验证播放、录音和方向切换，再回归 GUD/HID。

回滚时恢复本变更前的描述符、TinyUSB 配置和 `uac_audio` 模块即可，不涉及持久化数据迁移。

## Open Questions

- 实机测试后确认 SPM1423 的 PDM slot edge 与录音幅度；如硬件批次存在差异，仅调整 slot mask 或数字放大
  参数，不改变 USB 协议契约。
