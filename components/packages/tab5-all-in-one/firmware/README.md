# Tab5 AIO 固件

ESP-IDF 固件把 Tab5 接成 `16d0:10a9` USB 复合设备。Linux 发送 640×360 RGB565 图像，
ESP32-P4 用 PPA（像素处理加速器）放大 2 倍并旋转至 720×1280 DSI 面板；
同一连接承载键盘、触摸、音频和摄像头。[Linux 端集成与验证范围](../README.md) · [相机与 ISP 参考](CAMERA.md)

## 1. 硬件与工具链

| 项目 | 当前基线 |
| --- | --- |
| 主控 | ESP32-P4 rev v1.0，编译目标为 rev < 3.0 |
| 存储 | 32 MB HEX PSRAM / 200 MHz，16 MB Flash，factory 分区 4 MB |
| 工具链 | ESP-IDF v6.0.2，依赖由 `main/idf_component.yml` / `dependencies.lock` 固定 |
| 显示 | 720×1280、2 lane DSI / 1000 Mbps；ILI9881C 已实机，ST7123 只编译 |
| USB | USB-C：PHY0，G24/G25，Full Speed 12 Mbps；USB-A 是另一条高速 Host 接口 |
| 日志 | UART0 TX G37 / RX G38，M5-Bus，115200 8N1；或有功能代价的 CDC 调试档 |

`sdkconfig.defaults` 选择 `CONFIG_ESP32P4_SELECTS_REV_LESS_V3=y` 和
`CONFIG_ESP32P4_REV_MIN_100=y`。rev < 3 与 rev ≥ 3 硬件互斥，不能用运行时探测让这一固件兼容两者。
面板批次则可以运行时 I2C 探测：`0x55` 对应 ST7123，`0x14` 对应 GT911/ILI9881C。

## 2. 构建与烧录

先按 ESP-IDF 的安装方式准备 v6.0.2 并激活其环境。以下命令从 flange 根目录进入工程：

```bash
cd components/packages/tab5-all-in-one/firmware
# 此前需 source 实际 ESP-IDF 安装目录的 export.sh
idf.py set-target esp32p4
idf.py build
```

产物在本工程 `build/`。默认配置包含 GUD、键盘、触摸、音频和摄像头；
修改 Kconfig 或切换 SDKCONFIG_DEFAULTS 后用 `idf.py fullclean` 清除旧 CMake 配置再构建。
当前 flange Docker 没有 ESP 工具链，此工程由独立 ESP-IDF 环境构建。

TinyUSB 接管 USB-C 后，USB-Serial/JTAG 自动复位下载不可用。烧录步骤：

1. 按住 BOOT（G35），插入 USB-C 或复位，然后松开进入 ROM 下载模式。
2. 用实际串口运行 `idf.py -p <串口> flash`。
3. 拔插 USB-C 正常启动，Linux 应枚举为 `16d0:10a9`。

USB-A 母座不作为设备上行口，不使用 A-to-A 线替代 USB-C 连接。

## 3. USB 接口与资源预算

| 功能 | 默认接口 | 端点 / 协议 |
| --- | --- | --- |
| GUD | IF0 Vendor | OUT `0x01` / IN `0x81`；实际像素走 bulk OUT，控制走 EP0 |
| 键盘 + 触摸 | IF1 HID | IN `0x82`；Report ID 1 键盘、2 触摸，10 ms 间隔 |
| 音频 | IF2 控制、IF3 播放、IF4 录音 | ISO OUT `0x02` / ISO IN `0x83` |
| 摄像头 | IF5 控制、IF6 流 | alt 0 无流端点；alt 1 ISO IN `0x84`，448 B/ms |

控制器仅有 4 条非 EP0 IN 端点，默认配置全部占用。默认描述符为 384 字节、7 接口。
可分配 FIFO 为 **242 words**，不是寄存器总量 256；默认共用 231、剩余 11。
16 kHz 单声道音频使最大 OUT 包仍小于 GUD 已有的 64 B，控制 RX FIFO 开销；
48 kHz 立体声没有足够 FIFO 再容纳 UVC。音频没有显式反馈端点，长期时钟漂移未实测。

### USB-C 枚举的必要条件

- 显式使用 `TINYUSB_CONFIG_FULL_SPEED`，默认 HIGH_SPEED 会驱动 USB-A 对应控制器。
- 将内部 PHY0 路由给 OTG1.1，并关闭抢占该 PHY 的 USB-Serial/JTAG 次级控制台。
- 音频 I2S 初始化先于 TinyUSB，安装后执行 `otg_fsls_pads_repair()`。

第三项修复一个已确认的 GPIO HAL 假设：`gpio_ll_func_sel()` 将 G26/G27 视作默认 OTG PHY，
配置 I2S 引脚时清除 USB_WRAP 的 pad enable；但本工程已把 OTG 换到 PHY0，因此误关的是 USB-C 的 G24/G25。
这不是两个输出驱动同时占用音频引脚。修复同时处理 pad pull override，防止 D+ 上拉被误清。
升级 ESP-IDF 时需对照 `app_main.c` 和当前 GPIO/USB HAL 的实际行为。

### CDC 调试档

`idf.py menuconfig` 中启用 `CONFIG_AIO_DEBUG_CDC` 可把日志送往 USB-C；该档**不编译音频**。
GUD 不使用的 IN `0x81` 让给 CDC 数据，音频 IN `0x83` 让给 CDC 通知，CDC OUT 为 `0x03`；
HID 与 UVC 保持 `0x82` / `0x84`。描述符为 259 字节、6 接口，FIFO 用 224 words。

不要直接启用 `CONFIG_TINYUSB_CDC_ENABLED`，其默认端点会冲突，编译检查会拒绝。
CDC 打开前的早期日志可能丢失；完整启动日志使用 UART0 与 USB-TTL。恢复音频需要关闭 CDC 并重新构建烧录。

## 4. GUD 显示

Linux 使用内核 `gud` 驱动，创建 `/dev/dri/cardN`。只提供一个 connector、一个 640×360 模式和 RGB565。
`SET_BUFFER` 声明脏矩形，bulk OUT 传像素；固件支持 LZ4 解压，经 PPA SRM 放大与旋转后写面板。
`DISPLAY_ROT_CCW90=1` 对应已标定方向；显示和触摸变换必须配套。

DSI 及 DPI 参数、初始化序列来自 esp-bsp 的 m5stack_tab5；供电由共享 IO 扩展器管理。
未连接主机时显示本地待机画面。Linux console 出图已验证，ST7123 批次及持续全屏帧率未实测。

```bash
lsusb -d 16d0:10a9
ls /sys/class/drm/
modetest -M gud -c
```

确认实际 DRM card 与 connector 后使用桌面或 kmssink；X11 配置见 [GUD 显示](../../../../docs/hardware/gud-display.md)。
不要把 `card0` 或 `event0` 固定为 Tab5，设备编号随系统变化。

## 5. HID 键盘与触摸

### Tab5 Keyboard

独立 I2C 使用 SDA G0 / SCL G1，地址 `0x6d`，INT G50 低有效。
Normal 模式（寄存器 `0x10=0`）读取行列事件，自建 6KRO 状态机；官方 HID 模式不能完整表达修饰键与多键按下。
版本/地址寄存器为 `0xfe/0xff`，不要把图中块基址 `0xf0` 当成版本；`0xfd` 是固件升级入口，驱动不访问它。

- 基础字母层不盲用官方表的 firstModifierMask，避免底行字母错误附加 Shift。
- Sym/Aa 是本地层键，不直接上报 Shift；Aa 被当前 Ctrl/Alt 按下集合门控，保证 Ctrl+C 等终端语义。
- HID usage `0xe0..0xe7` 转修饰位；超过 6 个普通键时丢弃超出项。
- 按下/释放逐条上报，不能把同批事件合成最终状态而丢失短按。端点忙时最多等 20 ms 并报告失败。

接口使用 report 协议，无 boot keyboard 承诺；BIOS/UEFI/GRUB 的 boot 协议环境不受支持。
未同步主机 CapsLock 等 LED 状态。

### GT911 触摸

触摸复用内部 I2C G31/G32，地址 `0x14`；IO 扩展器 `0x43` 的 PIN5 供电。
INT G23 需驱动为低，同时传 `int_gpio_num=GPIO_NUM_NC`，由 20 ms 轮询读点；上拉该脚会使本板不出坐标。
缺少可选键盘/触摸只记录警告，不阻塞显示启动。

触摸与键盘共用 IF1，RID 2 的负载为 31 B：5×6 B contact + 1 B Contact Count。
坐标范围 0..32767，报告声明最多 5 点。实现有以下接口约束：

- 活跃 contact 压实到报告前部，保留控制器 track_id；未用 slot 清零，不按 ID 留空洞。
- 最大点数同时约束结构体、描述符和 GET_REPORT Feature 应答；Feature 数据不重复写 Report ID。
- Contact Identifier 的最大值 255 使用两字节有符号编码；X/Y 属 Generic Desktop 页，之后切回 Digitizer 页。
- 状态未变不重发；只有发送成功才更新 last_rpt，避免丢失“全部抬起”后永久卡触摸。

实机在 Khadas VIM3L 观察到独立键盘设备、ABS_MT_SLOT Max 4、三指独立轨迹，以及横持四角 X/Y 全量程。
驱动绑定由这些 MT 能力推断，当次未直接读取 sysfs driver 链接；四/五指未实测。

```bash
cat /proc/bus/input/devices
sudo evtest
```

按名字分别选择 `flange Tab5 USB Terminal Keyboard` 与触摸设备，检查组合键、释放、三指和四角。

## 6. UAC1 音频

ES8388（7-bit 地址 `0x10`）播放、ES7210（`0x40`）录音，共用同一 I2S 端口和 MCLK/BCLK/WS，
收发数据线分离，硬件可全双工。两方向均为 16 kHz、单声道、S16_LE；USB 与 I2S 的单双声道转换在 `audio_frame.c`。

| 信号 | GPIO |
| --- | --- |
| MCLK / BCLK / WS | 30 / 27 / 29 |
| 播放 DOUT / 录音 DSIN | 26 / 28 |
| 喇叭功放 | IO 扩展器 `0x43` 的 PIN1；完成 codec 初始化后启用 |

I2S TX/RX 的采样率、位宽和 slot 数必须一致。codec 库使用的地址形式与 I2C probe 不同，
按 `tab5_pins.h` 区分 7-bit / 8-bit 常量，不混用。摄像头和功放复用已有 IO 扩展器句柄，
重新初始化扩展器会意外改变屏幕与触摸供电。

播放 Feature Unit 提供音量/静音，映射到 ES8388 硬件音量，范围约 -50..0 dB；录音增益未提供。
播放、录音、硬件音量分别实测通过；两方向长期同时运行及无反馈端点的漂移未验收。

```bash
aplay -l
arecord -l
# 将 N 替换为 Tab5 的声卡号
speaker-test -D plughw:N,0 -r 16000 -c 1 -F S16_LE -t sine
arecord -D hw:N,0 -r 16000 -c 1 -f S16_LE -d 10 /tmp/tab5-mic.wav
amixer -c N scontrols
```

## 7. 摄像头与整体性能

SC202CS 经 CSI/ISP 输出 RGB565，PPA 缩小到 640×360，再用硬件 JPEG 以 4:2:2 / quality 70 编码。
USB 只声明 MJPEG 640×360 / 10 fps；Linux 由 uvcvideo 创建 `/dev/videoN`。
当前实现、rev v1.0 限制、ISP 参数和验证方法见 [CAMERA.md](CAMERA.md)。

摄像头在主机进入 alt 1 后才启动 CSI；alt 0 不预留视频 ISO 带宽，也不做持续取帧。
这不等于整个相机功能零内存或零资源占用：FIFO 等资源可在 SET_CONFIGURATION 时分配。
开摄像头后 GUD 的理论可用带宽从约 1364 降至 916 B/ms（约 33%），真实帧率影响尚未测得。

性能检查可先测仅 GUD 的全屏动态内容，再同时打开键盘、触摸、双向音频和 UVC，
对比相同内容的帧率、USB 错误、UART 的解压/PPA 失败与音视频累计帧数。
音频漂移以实际 wall clock 与收发样本数比较，不用软件设定的时长代替观测时长。
目前没有五项同时运行的长稳结果。

## 8. 验证与源码定位

纯逻辑测试在 `test/`，直接编译 `main/` 的实现，不依赖 ESP 硬件。
现有 9 组覆盖键盘、触摸、待机画面、音频帧、音量、UVC 图案、帧统计、控制律和 ISP 映射。
2026-08-21 记录为共 3258 用例通过；这是既有结果，本页不代表重新运行了全部固件验证。

```bash
# 在 firmware/ 中，构建后校验 ELF 内实际描述符
python3 test/check_usb_desc.py build/tab5_aio.elf
# 拉取依赖后校验官方标定值的生成结果
python3 test/isp_cal_extract.py --check
```

描述符检查覆盖默认与 CDC 两种构建，验证端点数量、UAC/UVC 描述符长度、alt 0/1 以及帧预算。
默认与 CDC 均有 clean build 通过记录；当前 ISP 对齐版本未烧板，不能用构建结果代替画质或硬件验收。

| 文件 | 职责 |
| --- | --- |
| `main/app_main.c`、`board_power.c`、`tab5_pins.h` | 初始化顺序、PHY 修复、供电与硬件常量 |
| `main/usb_descriptors.c` / `.h`、`tinyusb_config/tusb_config.h` | 复合描述符与类配置 |
| `main/gud_device.c`、`display_dsi.c`、`standby_screen.c` | 收帧、解压、PPA/面板与待机画面 |
| `main/kbd_i2c.c`、`kbd_translate.c`、`tab5_kbd_map.h` | 键盘总线、状态与层映射 |
| `main/touch_hid.c`、`touch_map.c` | GT911 采集、坐标和 HID 报告 |
| `main/codec_audio.c`、`audio_frame.c`、`uac_volume.c` | 音频数据泵与硬件音量 |
| `main/camera_csi.c`、`cam_jpeg.c`、`uvc_stream.c` | 相机采集、缩放编码与视频流 |
| `main/cam_tune.c` / `.h`、`cam_isp_map.c`、`cam_frame_stats.c` | 可测试的控制律、ISP 映射及统计 |
| `main/cam_isp_cal.h`、`test/isp_cal_extract.py` | 官方标定数据的生成物与提取工具 |

GUD 协议头来自 Linux（Dual MIT/GPL），面板与驱动资料来自 esp-bsp（Apache-2.0），
键盘映射来自官方固件（MIT），Spleen 点阵字体为 BSD-2-Clause；保留文件中的原始许可。
