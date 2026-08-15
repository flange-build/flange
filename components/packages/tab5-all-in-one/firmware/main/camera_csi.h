#pragma once
/*
 * SC202CS(RAW8) → MIPI-CSI host → **ISP(去马赛克)** → CSI 桥(直通) → DMA →
 * 1280×720 RGB565（PSRAM）。
 * **本阶段（P4 Task8）取流但不接 UVC** —— UVC 继续出 Task6 的片上合成图案。
 * PPA 缩小与接进 UVC 流是 Task9 的事，刻意分开：这样「取流」出问题时，
 * 变量只有取流本身，不会和编码/USB 混在一起。
 *
 * ⚠️ **RAW8→RGB565 只能由 ISP 做，不能交给 CSI 桥。** 本板 P4 是 rev v1.0，
 * 桥的颜色转换硬件不存在，让它转会在 esp_cam_new_csi_ctlr() 就返回
 * ESP_ERR_NOT_SUPPORTED（实机踩过一次）。所以 CSI 的 input/output 颜色格式
 * **都填 RGB565**（= 桥搬运的数据，不是传感器发的），逐行依据写在
 * camera_csi.c 的 csi_cfg 上方。IDF 例程 mipi_isp_dsi 那份 RAW8→RGB565 的
 * CSI 配置只适用于 rev ≥ 3.0，不能照抄。
 *
 * 分层与音频、面板、触摸完全同构：
 *   寄存器序列   → 托管组件 espressif/esp_cam_sensor（**芯片驱动**组件，
 *                  依赖只有 cmake_utilities + esp_sccb_intf，两者都零外部依赖）
 *   CSI / ISP    → IDF 内置的 esp_driver_cam / esp_driver_isp
 *   板级接线     → 本文件（电源在 IO 扩展 0x43 的 PIN6，SCCB 复用内部 I2C）
 * **刻意不引 espressif/esp_video**：它强制拖 usb_host_uvc + esp_h264 + esp_ipa，
 * 在一块「TinyUSB device 独占唯一一条 FSLS PHY」的板子上引入 USB Host 栈毫无道理。
 * 完整依据见 main/idf_component.yml 里 esp_cam_sensor 那一段。
 *
 * ⚠️ **只在真的要用画面时才 start。** CSI 每秒往 PSRAM 写 55 MB（1280×720×2×30），
 * 而 DPI 面板刷新每秒要从 PSRAM 读 89～107 MB —— 算式（timing 见 display_dsi.c）：
 *   ILI9881C  60 MHz ÷ (940 × 1324) = 48.2 Hz × 720×1280×2 B ≈  89 MB/s
 *   ST7123    70 MHz ÷ (802 × 1510) = 57.8 Hz × 720×1280×2 B ≈ 107 MB/s
 * （DPI 只在有效像素期取数，所以不是「像素时钟 × 2 字节」那个含消隐的上界）。
 * 常开会挤 DPI 的带宽，表现为屏幕撕裂/花屏。所以 camera_csi_init() 只建对象、
 * 不开数据流，启停单独一对函数 —— Task9 会把它们挂到 UVC 的 alt 0/1 上。
 */
#include "esp_err.h"
#include <stdint.h>

/*
 * 给摄像头上电，在共用的内部 I2C 总线上建一个 SCCB io，读 PID，再交给
 * esp_cam_sensor 的 sc202cs_detect()。
 *
 * 失败时**自己把摄像头电源关掉**并返回错误，调用方只需降级：本阶段 UVC 仍用
 * 片上合成图案帧源，显示/键盘/触摸/音频四项能力一概不受影响。
 * 与 kbd_start() / touch_start() / codec_audio_init() 同一处置原则。
 *
 * 不幂等：重复调用会重复上电与重复建 SCCB io。开机只调一次。
 */
esp_err_t camera_sensor_probe(void);

/*
 * 自检快照打一遍。与 codec_audio_report() 同构，存在的理由也一样：探测跑在 CDC
 * 日志串口真正出字节之前，现场看不到它的 ESP_LOG*，所以结论要能被复读。
 *
 * 它把四种失败**明确区分开**（判读表写在 camera_csi.c 的函数注释里）：
 *   SCCB io 没建起来 / 0x36 不应答(NAK) / 应答但 PID 不是 0xeb52 / 组件内部失败。
 */
void camera_sensor_report(void);

/*
 * 建 CSI 控制器 + ISP + 帧缓冲，并把传感器的 1280×720 RAW8 寄存器表真正写进去。
 * 须在 camera_sensor_probe() 成功之后调用；**不启动任何数据流**。
 * 幂等：重复调用直接返回 ESP_OK。
 *
 * 失败时同样只降级不拦启动，具体卡在哪一步由 camera_csi_report() 区分
 * （六个步骤各自记一个返回值，不共用哨兵）。
 */
esp_err_t camera_csi_init(void);

/*
 * 开/关取流。幂等。必须在 camera_csi_init() 成功之后。
 *
 * start 的顺序是**先控制器后传感器**：传感器一 stream on，MIPI 差分对就开始送
 * 数据，控制器没 start 的话那些数据无处可去（表现为 CSI 的 error 中断刷屏）。
 * stop 严格反序，否则 CSI 上会留下半帧，下次 start 的第一帧是错位的。
 *
 * ⓘ stop **不断摄像头的电**：断电会丢掉 esp_cam_sensor 写进去的整张寄存器表，
 *   下次 start 就得重新 detect + set_format（几十毫秒的 I2C，且多一条会失败的
 *   路径）。而 UVC 的 alt 0/1 切换可能相当频繁 —— Task9 每次开关摄像头都重跑一遍
 *   探测，正是那种「实验室好好的、现场偶发失败」的设计。不取流时传感器停在
 *   sleep mode（reg 0x0100 = 0），**不产生任何 MIPI 数据、不占一点 PSRAM 带宽**，
 *   这已经满足「不取流时零影响」；剩下的只是传感器自身的静态电流。
 */
esp_err_t camera_csi_start(void);
esp_err_t camera_csi_stop(void);

/*
 * 阻塞取一帧。成功时 *fb 指向 CAM_SENSOR_W×CAM_SENSOR_H 个 RGB565（紧凑排列）。
 *
 * 该缓冲**在下一次 camera_csi_get_frame() 调用之前有效** —— 下一次调用会把它还给
 * DMA。这条约定就是缓冲的归还机制，调用方不需要（也没有）单独的 release 函数。
 *
 * 返回 ESP_ERR_TIMEOUT 表示 timeout_ms 内没有帧写完。这与「取到了一帧全黑」是
 * 完全不同的两件事，日志里必须分得开 —— 见 camera_csi_report()。
 */
esp_err_t camera_csi_get_frame(const uint16_t **fb, uint32_t timeout_ms);

/*
 * CSI/ISP 自检快照。与 camera_sensor_report() 同构、理由也一样（CDC 档下开机那几行
 * 会被环形缓冲冲掉，结论必须能被复读）。
 *
 * 它把六个初始化步骤**各自**记一个返回值（帧缓冲 / CSI 控制器 / 回调注册 / ISP /
 * 传感器 set_format / start），不共用哨兵；再加上运行期的四个计数器
 * （取到的帧 / 丢帧 / 取帧超时 / 缓冲被抢回）。
 */
void camera_csi_report(void);

/*
 * ⚠️ **临时自检任务，Task9 接上 UVC 时整块删掉。**
 *
 * 它存在的唯一理由：本任务不接 UVC，没有任何 host 侧出口，而「取到的到底是不是
 * 真画面」必须有一个物理上无可辩驳的判据 —— 拿手挡住镜头，平均亮度必须跟着掉。
 *
 * 行为：开机后取流 CAM_SELFTEST_SEC 秒，每秒打一行帧率/亮度/校验和，
 * **到点自动停流并结束任务**。到点即停是刻意的：Task8 的默认构建不能变成
 * 「摄像头永远开着」，那会一直挤 DPI 的 PSRAM 带宽，等于用一个临时自检去破坏
 * 已经验证过的显示能力。停流之后这块板就回到「摄像头已就绪、但没在取流」的
 * 常态，也正好把 stop 路径跑了一遍。
 */
void camera_csi_selftest_start(void);
