#pragma once
/*
 * 把一帧 RGB565 用 ESP32-P4 的**硬件** JPEG 编码器压成 MJPEG 负载。
 *
 * 为什么是硬件：640×360 的软件 JPEG 在 P4 上要几十毫秒且吃满一个核，
 * 而 10 fps 的拍子只有 100 ms —— 那点余量还要留给 GUD 收帧与显示刷新。
 * esp_driver_jpeg 是 IDF 内置组件，不引入任何托管依赖（esp_video 会顺带
 * 拖进 usb_host_uvc + esp_h264 + esp_ipa，计划里已经否决）。
 *
 * 本文件是「像素后处理」这一层唯一的对外入口：uvc_stream.c 只依赖这一个头文件，
 * 换帧源时 USB 侧一行不用动。
 */
#include "esp_err.h"
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

/*
 * 建编码器引擎与两块输出缓冲。**不幂等**：重复调用返回 ESP_ERR_INVALID_STATE，
 * 而不是悄悄再建一个引擎（那会多占一份 PSRAM 且两个引擎抢同一个 2D-DMA 通道）。
 */
esp_err_t cam_jpeg_init(void);

/*
 * 编码一帧。src 是紧凑排列的 w×h 个 RGB565（stride = w，小端，无 padding）。
 * 成功时 *out / *len 指向**内部双缓冲中当前空闲的那一块**。
 *
 * ⚠️ **双缓冲不是优化，是正确性要求**：tud_video_n_frame_xfer() 只记指针，
 *    整帧发完之前驱动会持续从这块内存 memcpy 取数（video_device.c 的
 *    _prepare_in_payload()）。单缓冲会让编码器一边写、UVC 一边读同一块内存，
 *    表现是画面横向撕裂（上半是新帧、下半是旧帧），而且只在帧偏大、
 *    一帧发不完一个拍子时才出现 —— 典型的「偶发、随内容变化」的疑难杂症。
 */
esp_err_t cam_jpeg_encode(const uint16_t *src, int w, int h,
                          const uint8_t **out, size_t *len);

/*
 * PPA SRM 缩放：CAM_SENSOR_W×CAM_SENSOR_H 的 RGB565 → UVC_W×UVC_H 的 RGB565。
 * 摄像头帧与 JPEG 编码器之间唯一的一步（Task9）。
 *
 * src：紧凑排列的 1280×720 RGB565，即 camera_csi_get_frame() 交回来的那一块。
 *      **输入侧没有对齐要求**（驱动的 C2M 回写带 UNALIGNED 标志）。
 * dst：紧凑排列的 640×360 RGB565。
 *      ⚠️ **dst 的首地址必须按 cache line 对齐**（ppa_srm.c:186-189 硬性检查
 *      out.buffer 与 out.buffer_size 两者都对齐，不对齐直接 ESP_ERR_INVALID_ARG，
 *      表现为「一帧都出不来」而不是画面异常）。460800 字节这个长度天然对齐
 *      （= 128 × 3600，64/128 两种 line size 都整除），首地址靠调用方用
 *      heap_caps_aligned_alloc() 保证 —— 见 uvc_stream.c 的分配点。
 *
 * 同步阻塞（PPA_TRANS_MODE_BLOCKING），必须在任务上下文调用。
 * 两侧的 cache 同步由 PPA 驱动自己做（ppa_srm.c:250-260），调用方不用管。
 */
esp_err_t cam_jpeg_downscale(const uint16_t *src, uint16_t *dst);

/*
 * 缩放侧的统计快照。参数都可传 NULL。
 *
 * last_us 不只是好奇：PPA 引擎是**与 GUD 显示共享**的硬件（两个 client 在引擎的
 * 那个二值信号量上排队，见 cam_jpeg.c 里 s_ppa 的注释），所以这个数就是
 * 「摄像头每 100 ms 会把 display_blit() 顶住多久」的上界，是 Task10 归因
 * 「显示掉帧到底怪谁」时唯一的直接证据。
 */
void cam_jpeg_scale_stats(uint32_t *scaled, uint32_t *failed, uint32_t *last_us);

/*
 * 告诉本模块「刚才那一块缓冲已经交给 UVC 了」，下一次编码换另一块。
 * **必须只在 tud_video_n_frame_xfer() 返回 true 之后调用。**
 *
 * 为什么不在 cam_jpeg_encode() 里自转（计划 Task6 Step3 的原始写法是自转的）：
 * 提交是会被驱动**拒收**的（上一帧还在飞）。设 A/B 两块，自转的序列是
 *   拍1 编 B，提交成功（B 在飞）
 *   拍2 编 A，提交被拒（B 还在飞，A 白编）
 *   拍3 编 B ← **B 仍在飞**，编码器正往 UVC 正在读的那块内存里写 ⇒ 撕裂
 * 也就是说自转在「零拒收」时才成立，恰恰在帧变大、拒收开始出现时失效 ——
 * 而那正是双缓冲存在的理由。改成「提交成功才转」后，编码永远落在
 * 「上一次成功提交的那一块」之外的那一块，与拒收次数无关。
 *
 * ⓘ 它不是「完成回调的影子标志」，所以没有 uvc_stream.c 里警告过的那种死锁：
 *   host 在 alt1→alt0→alt1 之间把在飞的帧丢掉时完成回调不会来，但本模块
 *   从不等待完成，最坏只是继续用另一块缓冲，一直是安全的。
 */
void cam_jpeg_frame_committed(void);

/*
 * 统计快照。**帧字节数是本阶段唯一能判断带宽余量的数字**：
 * 每包有效载荷 446 B、全速 ISO 每毫秒一包 ⇒ 帧字节 ÷ 446 就是这一帧要占的毫秒数，
 * 拿它和 100 ms 的拍子比即可。参数都可传 NULL。
 */
void cam_jpeg_stats(uint32_t *encoded, uint32_t *failed, size_t *last_bytes,
                    size_t *avg_bytes, size_t *peak_bytes, uint32_t *last_us);
