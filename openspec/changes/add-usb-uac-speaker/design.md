## Context

当前 firmware 通过 `esp_tinyusb` 1.7.x 暴露 IF0 Vendor/GUD 与 IF1 HID 键盘。项目早期设计已确定
Cardputer 音频使用 UAC1、mono 16 kHz / 16 bit，板载 NS4168 的 I2S 引脚为 BCLK=GPIO41、
DOUT=GPIO42、WS=GPIO43。GPIO43 同时是当前 UART0 TX，因此音频启用后不能继续使用 UART0 日志。

`esp_tinyusb` 1.7.x 的依赖下界 TinyUSB 0.14.2 会解析到缺少 UAC1 device 路径的旧实现；官方
TinyUSB 0.21 已提供 Full-Speed UAC1 speaker 支持。`esp_tinyusb` 默认 `tusb_config.h` 未开放 Audio
Kconfig，因此 firmware 必须提供局部配置覆盖，同时继续复用 `tinyusb_driver_install()` 的 PHY、task
与描述符注入能力。

## Goals / Non-Goals

**Goals:**

- 保留 GUD 与 HID 行为，新增 Linux `snd-usb-audio` 可直接识别的 UAC1 playback PCM。
- 固定 mono 16 kHz / 16 bit，每 USB frame 32 bytes，降低 FS 总线与 SRAM 压力。
- 把 USB OUT FIFO 按 I2S 消费节奏送到 NS4168，并对欠载输出静音。
- 消除 GPIO43 的 UART0/I2S 冲突，提供可复现的构建与实机验证步骤。

**Non-Goals:**

- 不实现麦克风、全双工、音量 DSP、重采样或 feedback endpoint。
- 不修改 host 内核、不新增私有 USB 驱动、不改变 VID/PID。
- 不在 flange Docker 中构建 ESP-IDF firmware。

## Decisions

### 1. 升级到 esp_tinyusb 2.2.x 与 TinyUSB 0.21.x

将 manifest 明确锁定兼容 UAC1 的版本，避免 `>=0.14.2` 在不同机器解析出行为不同的 TinyUSB。
备选是在旧 TinyUSB 上自行回移 UAC1 class driver，但维护面和验证成本明显更高。

### 2. 使用 UAC1 adaptive OUT，不增加 feedback endpoint

16000 Hz 能整除 USB Full-Speed 的 1000 frames/s，每帧恒定 16 samples / 32 bytes。首版用 adaptive
isochronous OUT 与 I2S 主时钟，避免再占一个 IN endpoint。若实机长时间播放出现累计漂移，再独立增加
feedback endpoint，不在首版预先复杂化。

### 3. 复合接口顺序为 GUD、UAC AC、UAC AS、HID

IF0 保持 Vendor/GUD，降低主线 GUD 绑定回归风险；IF1/IF2 由 IAD 组合成 UAC；HID 后移至 IF3。
端点保持 GUD OUT=0x01/IN=0x81、HID IN=0x82，并新增 Audio OUT=0x03，避免改变既有 endpoint。

### 4. firmware 提供局部 TinyUSB 配置覆盖

新增 `main/tusb_config.h`，先包含 esp_tinyusb 默认配置，再开启单个 Audio function 并声明 descriptor
长度、AS interface 数、control buffer、32-byte endpoint 与多帧软件 FIFO。CMake 将该目录以 `BEFORE`
方式加入 esp_tinyusb 与 TinyUSB target，确保两个组件和应用看到完全一致的 class 配置。

### 5. I2S task 以固定 1 ms 节奏消费

`uac_audio` 初始化 ESP-IDF I2S standard TX，创建高优先级 task。每轮读取 32 bytes；不足部分清零后写入
I2S。数据仅有 16 个 int16 sample，无需额外动态环形缓冲，TinyUSB software FIFO 即跨 USB/I2S 时钟域
的缓冲。

### 6. 关闭 UART 控制台释放 GPIO43

将 sdkconfig 默认控制台改为 `none`，避免 UART0 TX 抢占 GPIO43。调试优先使用 JTAG 或临时改用不冲突
GPIO 的外接日志配置；不在首版引入新的运行时日志 transport。

## Risks / Trade-offs

- [UAC1 helper macro 位于 TinyUSB example 而非公共头] → 在 firmware 内维护最小 UAC1 descriptor macro，
  按 TinyUSB 0.21 结构与 USB Audio 1.0 descriptor 字段静态校验总长度。
- [无 feedback endpoint 时主机与 ESP I2S 时钟可能长期漂移] → 使用 16 kHz 恒定帧长与多帧 FIFO，实机先做
  10 分钟播放；若仍有周期性 underrun/overrun，后续增加显式 feedback。
- [关闭 UART 后可观测性下降] → 文档提供 host 枚举与 ALSA 验证，并保留 ESP-IDF JTAG 调试路径。
- [依赖升级可能影响 GUD/HID] → 构建后用 descriptor parser、`lsusb -v`、`modetest`、`evtest` 做复合回归。

## Migration Plan

1. 更新 managed component 版本并删除旧 lock 后重新解析依赖。
2. 编译并烧录 firmware；若无法枚举，回滚 manifest、TinyUSB 配置与 UAC descriptor 即恢复原功能。
3. 依次验证 USB descriptor、ALSA playback、GUD 出图、HID 按键与连续播放稳定性。

## Open Questions

- 首版无 feedback 的时钟漂移是否在目标 Linux host 与 Cardputer 实机上可接受，需要 10 分钟播放验证。
- 关闭 UART0 后，项目是否要在后续变更中固定一组不冲突 GPIO 作为量产日志口。
