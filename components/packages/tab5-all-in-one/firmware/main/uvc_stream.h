#pragma once
/*
 * UVC 视频流：把一份 JPEG 字节流按 10 fps 交给 TinyUSB 的 video class。
 *
 * 帧源是**可换的**，本文件只管「什么时候提交下一帧」与「提交给谁」：
 *   P4 Task5：flash 里的静态 JPEG（uvc_test_jpeg.h）—— 先用假数据把 USB 证通
 *   P4 Task6：片上硬件编码的合成图案（cam_jpeg.c + uvc_pattern.c）
 *   P4 Task9：真实摄像头（camera_csi.c → cam_jpeg.c）
 * 每一步只换帧源，USB 侧一行不动 —— 出问题时变量只有一个。
 *
 * ⚠️ **Task9 起才第一次真正压这根管子。** Task5/Task6 的帧源都压不满它
 *    （静态图与平色块的合成图案编出来都只有几 KB ≈ 15 个包 ≈ 15 ms，100 ms 的
 *    拍子里八成在空转），所以那两步的「零拒收」**不是**带宽结论。真实照片类内容
 *    640×360 4:2:2 在 q=70 上典型 25–35 KB，对着每帧 44.6 KB 的预算才有话说。
 *    判断余量看 uvc_stream_report() 第二行的「峰值占 N/100 ms」与「拒收」。
 */
#include "esp_err.h"
#include <stdbool.h>

/* 起帧泵任务。须在 tinyusb_driver_install() 之后调用（任务一起来就会调 tud_video_*）。
 * 与键盘/触摸/音频同一处置原则：失败只降级、不拦启动。 */
esp_err_t uvc_stream_start(void);

/* host 是否已选中 VideoStreaming 的 alt 1（= 摄像头真的被打开了）。
 * 实现就是一句 tud_video_n_streaming(0, 0)，单独暴露是为了让
 * uvc_stream_report() 与将来的自检有一个不必知道 ctl/stm 索引的入口。
 * ⓘ CSI 的按需启停（spec §2.1「带宽零和」在 PSRAM 侧的落点）在帧泵任务**内部**
 *   完成，直接用 tud_video_n_streaming()，不绕这个函数。 */
bool uvc_stream_is_streaming(void);

/* 自检快照打一遍（提交/完成/拒收帧数，以及 host 在 COMMIT 里协商下来的参数）。
 * 与 codec_audio_report() 同构，但**两档都要周期性复读**：这里的数字随 host
 * 开关摄像头而变，它随时间的增量就是「流到底通没通」的唯一设备侧证据。 */
void uvc_stream_report(void);
