#pragma once
/*
 * SC202CS(RAW8) → MIPI-CSI host → **ISP(去马赛克)** → CSI 桥(直通) → DMA →
 * 1280×720 RGB565（PSRAM）。
 * 取到的帧由 uvc_stream.c 接走：PPA 缩到 640×360 → 硬件 JPEG → UVC（Task9）。
 * **取流的启停归 UVC 的 alt 0/1 管**，见下面 camera_csi_start()/stop() 的说明。
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
 * 不开数据流，启停单独一对函数 —— 由 uvc_stream.c 的帧泵按 host 选中的
 * alt 0/1 调用（alt 0 = 没人开摄像头 ⇒ 一点 PSRAM 带宽都不占）。
 */
#include "cam_frame_stats.h"
#include "esp_err.h"
#include <stdint.h>

/*
 * 给摄像头上电，在共用的内部 I2C 总线上建一个 SCCB io，读 PID，再交给
 * esp_cam_sensor 的 sc202cs_detect()。
 *
 * 失败时**自己把摄像头电源关掉**并返回错误，调用方只需降级：UVC 接口照样枚举，
 * 只是一帧都发不出来（host 侧 = 有 /dev/videoN 但取不到流），
 * 显示/键盘/触摸/音频四项能力一概不受影响。
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
 *   路径）。而 UVC 的 alt 0/1 切换可能相当频繁（host 每开关一次摄像头就是一对）
 *   —— 每次都重跑一遍探测，正是那种「实验室好好的、现场偶发失败」的设计。
 *   不取流时传感器停在
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
 * 自动曝光(AE) + 自动白平衡(AWB) 各走一拍。**每取到一帧就调一次**，由取帧的
 * 那一方（uvc_stream.c 的帧泵）把该帧的统计送进来 —— 统计本来就是它为了自检
 * 在算的，两个控制环不必再各扫一遍 PSRAM。
 *
 * 两者吃的是同一份统计量（AE 看 lum_mean，AWB 看 r/g/b_mean），**互相耦合**，
 * 处理方式有三条，理由都写在 cam_tune.h：
 *   ① AWB 的反馈量是**归一化**的通道比值 ⇒ 对 AE 改亮度天然免疫；
 *   ② AWB 的更新周期（1 秒）远大于 AE 的（300 ms）⇒ 时间尺度分离；
 *   ③ AWB 只在 AE 已收敛时才动 ⇒ 不在曝光暂态上采信颜色统计。
 * 因此调用顺序是**先 AE 后 AWB**（AWB 要读到本帧刚更新的收敛状态）。
 *
 * 更新频率限制、死区、阻尼、限幅这几道防振荡闸全在 cam_tune.c 的控制律里，
 * 所以本函数**可以放心地每帧调**：绝大多数拍它只是记下统计就返回，AE 真正下发
 * SCCB 最快 CAM_AE_INTERVAL_TICKS 拍一次，AWB 重配 CCM 最快
 * CAM_AWB_INTERVAL_TICKS 拍一次。
 *
 * 不取流（host 停在 alt 0）时它什么都不做 —— 与「摄像头不取流时零影响」一致。
 * 传感器可调范围没查到时 AE 不动（画面停在模式表的默认曝光上），而 AWB 照常
 * 工作：曝光恒定本身就意味着亮度稳定，正是最该采信颜色统计的情形。
 *
 * ⓘ CAM_AWB_ENABLE = 0 时 AWB 整段不编译，CCM 停在开机配好的静态矩阵上。
 */
void camera_csi_tune_tick(const cam_frame_stats_t *stats);

/*
 * 逆 gamma 查表（256 项），给帧统计层还原线性域用。
 *
 * 返回 **NULL = 「别做逆变换」**，且这是一个有含义的返回值而不是错误：gamma 关着
 * （CAM_GAMMA_ENABLE = 0）或没配上时，ISP 直出的就是线性光，再逆一次会把 AE/AWB
 * 的反馈量系统性压暗。表的档位与硬件里那条曲线**同源**（同一个函数一起设定），
 * 调用方不需要、也无从知道当前是哪一档。
 *
 * 表的内容在 camera_csi_init() 里定好，之后只读 ⇒ 帧泵线程可以直接用，不需要锁。
 */
const uint8_t *camera_csi_gamma_inv_lut(void);

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
 * 量一次「此刻 CPU 还能从 PSRAM 读多快」，单位 MB/s；帧缓冲还没分配时返回 0。
 *
 * 这条链路上抢 PSRAM 带宽的有四家：DPI 面板刷新（常驻读 89～107 MB/s）、
 * CSI 写入（取流时 55 MB/s）、PPA 缩放（读 18 + 写 4.6 MB/s）、JPEG 编码器。
 * **肉眼看屏幕不是判据** —— 轻微的带宽紧张看不出来，等看得出来时已经说不清
 * 是不是别的原因。由 uvc_stream.c 在「没取流 / 取流+缩放+编码 / 停流后」三个
 * 时点各调一次，三个数并排打出来，差值就是这条链路实际吃掉的那一份。
 *
 * ⚠️ **它自己要读 1 MB PSRAM（约 10 ms），是个有代价的观测**：只能在明确的
 *    时点调，每帧都调的话它自己就成了干扰源。
 */
uint32_t camera_csi_psram_read_mbps(void);
