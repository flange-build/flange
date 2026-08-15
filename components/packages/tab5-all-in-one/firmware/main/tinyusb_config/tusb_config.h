#pragma once

/*
 * esp_tinyusb 2.2.1 的默认 tusb_config.h 把 Vendor/HID/CDC 等映射到了 Kconfig，
 * 但**没有开放 Audio 类**（它的 Kconfig 与 include/tusb_config.h 里 AUDIO 零命中）。
 * include_next 保留它的平台、FreeRTOS 与既有 class 配置，再追加本工程的 UAC1 参数。
 *
 * CMake 侧的接线见 main/CMakeLists.txt：必须**同时**把本目录塞进 tinyusb 与
 * esp_tinyusb 两个库的 include 路径最前面 —— 只改一个会让两边看到不同的
 * CFG_TUD_*，接口数与描述符长度对不上。
 *
 * ⓘ sdkconfig.h 必须在 include_next **之前**取到（下面的 CFG_TUD_* 之外，
 *    esp_tinyusb 的默认配置本身也读它）：IDF 给每个编译单元都加了
 *    -I build/config，所以这里能直接 include 到。
 */
#include "sdkconfig.h"

#include_next "tusb_config.h"

#undef CFG_TUD_AUDIO
#define CFG_TUD_AUDIO 1

/*
 * 播放（host → 设备）。SZ_MAX 必须 ≥ 描述符里声明的 wMaxPacketSize，
 * SW_BUF_SZ 必须 ≥ SZ_MAX（不满足时 audio_device.h 直接 #error）。
 * 256 字节软件缓冲 ≈ 8 个 USB 帧，足够吸收数据泵任务的调度抖动。
 */
#define CFG_TUD_AUDIO_ENABLE_EP_OUT             1
#define CFG_TUD_AUDIO_FUNC_1_EP_OUT_SZ_MAX      36
#define CFG_TUD_AUDIO_FUNC_1_EP_OUT_SW_BUF_SZ   256

/* 录音（设备 → host） */
#define CFG_TUD_AUDIO_ENABLE_EP_IN              1
#define CFG_TUD_AUDIO_FUNC_1_EP_IN_SZ_MAX       36
#define CFG_TUD_AUDIO_FUNC_1_EP_IN_SW_BUF_SZ    256

/*
 * 让 TinyUSB 按软件 FIFO 水位决定每帧发几个样本（标称 16 个，±1）。
 * 这正是「异步 IN 不需要反馈端点」的实现基础：设备时钟与 host 帧钟的漂移
 * 由包大小自己吸收，而不是靠一条额外的端点去告诉 host。
 */
#define CFG_TUD_AUDIO_EP_IN_FLOW_CONTROL        1

/*
 * ⚠️ 这两条显式写 0，不靠默认值 —— 它们各自会多要一条 IN 端点。
 * P4 全速控制器只有 4 条可用 IN，已经分给
 * vendor(0x81) / HID(0x82) / UAC 录音(0x83) / UVC 视频流(0x84)。
 * 多出来的第 5 条会让 dcd_dwc2.c 的 TU_ASSERT 失败，且**无日志**。
 */
#define CFG_TUD_AUDIO_ENABLE_FEEDBACK_EP        0
#define CFG_TUD_AUDIO_ENABLE_INTERRUPT_EP       0

/*
 * ── UVC（Video class）───────────────────────────────────────────────
 * esp_tinyusb 2.2.1 的 Kconfig 与默认 tusb_config.h 里 VIDEO 零命中，
 * 所以与 Audio 一样只能在这里手工开。
 *
 * ⚠️ **两个宏都必须定义。** usbd.c 只用 `#if CFG_TUD_VIDEO` 就把 videod 驱动
 *    挂进驱动表，而 video_device.c:30 的编译门是
 *    `#if (CFG_TUD_ENABLED && CFG_TUD_VIDEO && CFG_TUD_VIDEO_STREAMING)`。
 *    只定义前者 ⇒ 整个 video_device.c 编译成空文件 ⇒ 链接期缺 videod_init /
 *    videod_deinit / videod_reset / videod_open / videod_control_xfer_cb /
 *    videod_xfer_cb 六个符号。tusb_option.h:656 只给了 CFG_TUD_VIDEO 的默认值 0，
 *    CFG_TUD_VIDEO_STREAMING 与 CFG_TUD_VIDEO_STREAMING_EP_BUFSIZE 连默认值都没有
 *    （全库 grep 只有使用点，没有 #ifndef 兜底）。
 */
#undef CFG_TUD_VIDEO
#define CFG_TUD_VIDEO                     1   /* 一个 VideoControl 功能 */
#define CFG_TUD_VIDEO_STREAMING           1   /* 它下属一个 VideoStreaming 接口 */

/*
 * ISO IN 端点缓冲 = 端点最大包。这个值有**两个**作用，必须与描述符里的
 * wMaxPacketSize 完全相等：
 *  ① TUD_EPBUF_DEF(buf, ...) 的静态 DMA 缓冲大小（video_device.c:129）；
 *  ② dwMaxPayloadTransferSize 的**封顶值**（:562-567）——
 *     它就是 host 每毫秒真正能拿到多少字节。
 * 取值 448 的完整推导见 usb_descriptors.h 的 UVC_EP_SIZE 注释。
 * ⚠️ 这里写不了 `UVC_EP_SIZE`：tusb_config.h 被 tinyusb 库自身包含，
 *    不能反向 include 应用头。所以是**字面量 + 对账断言**（在 usb_descriptors.c）。
 */
#define CFG_TUD_VIDEO_STREAMING_EP_BUFSIZE  448
