#pragma once
#include "tusb.h"

/* mainline drm/gud 驱动绑定的固定 VID/PID，不可更改 */
#define GUD_VID 0x16d0
#define GUD_PID 0x10a9

/*
 * ── AIO_HAS_AUDIO：UVC 调试档为什么必须关掉音频 ─────────────────────
 *
 * 这块板现场没有开箱即用的串口（USJ 被 TinyUSB 收走、UART0 只在 M5-Bus 排针上），
 * 唯一不接外设的日志通道是 USB CDC —— 而 CDC 要 **2 条 IN 端点**（通知 + 数据）。
 *
 * P3 那一档的做法是「让出 vendor IN 0x81 + 借走 UVC 预留的 0x84」。**UVC 落地后
 * 这条路走不通了**：0x84 已经是视频流本身，借走它等于关掉被调试的对象。
 *
 * 新的账：让出 vendor IN(0x81) 腾 1 条 + **整个音频功能不编译**腾出 0x83，
 * CDC 拿 0x81(数据) 与 0x83(通知)，0x84 **原封不动留给 UVC**：
 *
 * | 0x81 | 0x82 | 0x83 | 0x84 |
 * |------|------|------|------|
 * | CDC 数据 IN | HID | CDC 通知 | **UVC 视频流（不变）** |
 *
 * FIFO 也宽裕（dfifo 顶 242 words）：
 *   RX 62 + EP0 16 + CDC 数据 IN 16 + HID 16 + CDC 通知(8B ⇒ 2 words) 2 = 112
 *   ⇒ 余 130 words = 520 字节 ≥ UVC 要的 112 words，比默认档还多 7 words。
 *
 * ⚠️ **代价：这一档下完全没有音频** —— host 侧 /proc/asound/cards 里没有这块设备，
 *    aplay/arecord 都不列它，喇叭与双麦全不工作。这是排障档，不是产品档。
 * ⓘ **有 USB-TTL 就别用这一档**：接 UART0(G37/G38) 零端点代价、能抓上电最早的
 *    日志、而且默认档（音频在）也能用。本档是「手边只有一根 USB-C 线」时的替代品。
 *
 * ⓘ 为什么不给音频单独一个 Kconfig 开关：那会造出第四种组合（无音频 + 无 CDC），
 *   它既没有用途也要跟着维护判据。AIO_HAS_AUDIO 是 CONFIG_AIO_DEBUG_CDC 的反相，
 *   不是独立自由度。
 */
#if CONFIG_AIO_DEBUG_CDC
#define AIO_HAS_AUDIO 0
#else
#define AIO_HAS_AUDIO 1
#endif

/*
 * 接口编号。
 *
 * ⚠️ **IF0 vendor 与 IF1 HID 的编号刻意不动。** 音频三个接口追加在 HID 之后，
 * 而不是像 spec §2 原先设想的那样插在 vendor 与 HID 之间 —— 键盘与多点触摸
 * 都已实机验证通过，没有理由为了排版好看去动它们的接口号。
 * IAD 只要求它覆盖的接口**连续**，不要求它们排在最前面。
 *
 * UAC1 三接口的**相对顺序不能动**：AudioControl 必须是 IAD 覆盖区间的第一个，
 * 两个 AudioStreaming 必须紧随其后且连号。
 */
enum {
    ITF_NUM_VENDOR = 0,
    ITF_NUM_HID,                   /* 键盘 + 多点触摸，靠 Report ID 区分 */
#if AIO_HAS_AUDIO
    ITF_NUM_AUDIO_CONTROL,
    ITF_NUM_AUDIO_STREAMING_OUT,   /* 播放：host → ES8388 → 喇叭 */
    ITF_NUM_AUDIO_STREAMING_IN,    /* 录音：ES7210 双麦 → host */
#endif
    /* UVC 两接口，同样**追加在最后**。相对顺序不能动：VideoControl 必须是 IAD
     * 覆盖区间的第一个，VideoStreaming 必须紧随其后。整段排在最后完全合法 ——
     * uvcvideo 按 IAD + 接口类绑定，不按接口号。 */
    ITF_NUM_VIDEO_CONTROL,
    ITF_NUM_VIDEO_STREAMING,
#if CONFIG_AIO_DEBUG_CDC
    /* 调试档的 CDC 也**追加在最后**，理由与音频那三个相同：不动已验证的接口号。
     * CDC 的两个接口必须连号且控制接口在前。 */
    ITF_NUM_CDC,
    ITF_NUM_CDC_DATA,
#endif
    ITF_NUM_TOTAL
};

/*
 * 端点编号。P4 全速控制器 ep_count=7 / ep_in_count=5(**含 EP0**)，
 * 即非 EP0 的可用 IN 端点只有 **4 条**（tinyusb portable/synopsys/dwc2/dwc2_esp32.h）。
 *
 * | 0x81 | 0x82 | 0x83 | 0x84 |
 * |------|------|------|------|
 * | vendor(GUD) | HID | **UAC 录音** | **UVC 视频流** |
 *
 * （CONFIG_AIO_DEBUG_CDC 下这张表会重排，见下方那段。）
 *
 * 超编时 dcd_dwc2.c 的 TU_ASSERT(allocated_epin_count < ep_in_count) 直接失败，
 * 且默认日志等级下**一个字都不打** —— 症状是 SET_INTERFACE 被 STALL、某个接口
 * 静默不工作，看起来与音频毫无关联。所以 4 条已经用满，不得再加。
 */
#define EPNUM_VENDOR_OUT 0x01
#if AIO_HAS_AUDIO
#define EPNUM_VENDOR_IN  0x81      /* 声明但从不使用，见下方 CONFIG_AIO_DEBUG_CDC */
#define EPNUM_AUDIO_OUT  0x02      /* ISO OUT，播放 */
#define EPNUM_AUDIO_IN   0x83      /* ISO IN，录音 */
#endif
#define EPNUM_HID        0x82
#define EPNUM_UVC_IN     0x84      /* ISO IN，视频流。**两档都是这一条，不再出借** */

/*
 * ── CONFIG_AIO_DEBUG_CDC：让出 GUD 的 IN 端点 + 关掉音频，换一条 USB 日志串口 ──
 *
 * 端点重排见文件顶部 AIO_HAS_AUDIO 那段的完整推导。这里只落号：
 *
 * | 0x81 | 0x82 | 0x83 | 0x84 |
 * |------|------|------|------|
 * | CDC 数据 IN | HID | CDC 通知 | **UVC 视频流（不变）** |
 *
 * **GUD 不需要 IN 端点。** mainline 的 drivers/gpu/drm/gud/gud_drv.c 在 probe 里
 * 只调一次 `usb_find_bulk_out_endpoint()`，全驱动没有 usb_find_bulk_in_endpoint /
 * usb_rcvbulkpipe —— 协议本身是「EP0 控制请求 + bulk OUT 送像素」的单向结构。
 * 本固件也从不调 tud_vendor_write()（gud_device.c 只有 rx 侧）。所以 0x81 是
 * TUD_VENDOR_DESCRIPTOR 顺带声明出来的一条**从未通过流量的端点**。
 * TinyUSB 侧也没问题：vendord_open() 按描述符里实际出现的端点逐条 open，
 * 只有 OUT 时就只开 rx_stream（vendor_device.c:296-332）。
 */
#if CONFIG_AIO_DEBUG_CDC
#define EPNUM_CDC_IN     0x81      /* 原 vendor IN 空出来的那一条 */
#define EPNUM_CDC_NOTIF  0x83      /* 原 UAC 录音空出来的那一条（音频整体不编译） */
#define EPNUM_CDC_OUT    0x03
#endif

/*
 * 直接开 CONFIG_TINYUSB_CDC_ENABLED 仍然是编译期错误：esp_tinyusb 默认给它的
 * 端点是 0x83/0x84，与 UVC 直接撞号。
 *
 * 把它变成编译期错误，而不是留给后人在一块**没有串口**的板子上调试一个
 * 「像是描述符写错」的枚举失败 —— 那正是最需要日志的时候最想打开 CDC 的时刻。
 * 正确的入口是 CONFIG_AIO_DEBUG_CDC（它自己会 select 出
 * CONFIG_TINYUSB_CDC_ENABLED，并重排端点号），而不是手动开 CDC。
 */
#if CONFIG_TINYUSB_CDC_ENABLED && !CONFIG_AIO_DEBUG_CDC
#error "要 USB 日志串口请开 CONFIG_AIO_DEBUG_CDC（Tab5 All-in-One 菜单里），它会让出 GUD 的 IN 端点并关掉音频来腾端点；不要直接开 CONFIG_TINYUSB_CDC_ENABLED（它默认占 0x83/0x84，与 UVC 撞号）"
#endif

#if CONFIG_AIO_DEBUG_CDC && !CONFIG_TINYUSB_CDC_ENABLED
#error "CONFIG_AIO_DEBUG_CDC 需要 CONFIG_TINYUSB_CDC_ENABLED（正常由 Kconfig 的 select 保证；手改 sdkconfig 时会掉）"
#endif

#if CONFIG_AIO_DEBUG_CDC && AIO_HAS_AUDIO
#error "UVC 调试档必须关掉音频才腾得出 IN 端点（0x83 要给 CDC 通知）"
#endif

/*
 * ── UAC1 音频参数：16 kHz / 单声道 / 16 bit(S16_LE)，播放与录音同参数 ──
 *
 * 为什么两个方向必须同采样率：全双工的 TX/RX 共用 BCLK 与 WS，采样率、位宽、
 * slot 数三项都必须一致。想让两个方向跑不同采样率就得占两个 I2S 端口，
 * 而 Tab5 的 SCLK/LRCK/MCLK 在物理上只有一组。
 *
 * 为什么是 16 kHz 单声道 —— 是 FIFO 账定的，不是听感定的。全速控制器整块
 * FIFO 只有 256 words(1 KB)，要同时装下共享 RX FIFO 与每条 IN 端点的 TX FIFO：
 *
 * | 方案 | OUT 包 | RX FIFO | 音频 IN 的 TX FIFO | 合计 | 空闲(留给 UVC) |
 * |---|---|---|---|---|---|
 * | **16 kHz 单声道(本方案)** | 36 B | **62**(不涨) | 9 | 135 | **121 words** ✅ |
 * | 32 kHz 单声道 / 16 kHz 立体声 | 68 B | 64 | 17 | 145 | 111 words |
 * | 48 kHz 立体声 | 196 B | 128 | 49 | 241 | 15 words ❌ UVC 没位置 |
 *
 * 16 kHz 单声道有一个别的档位没有的性质：**OUT 包 36 B 小于 vendor 已有的
 * 64 B，共享 RX FIFO 一个 word 都不涨**，整个音频功能的 FIFO 代价只有录音
 * 那 9 words。而 FIFO 不够时 dfifo_alloc() 只是 TU_ASSERT 返回 false，**无日志**。
 *
 * 另一半理由见下面那条 _Static_assert：16000 % 1000 == 0 ⇒ 每个 USB 帧恰好
 * 16 个样本、没有小数包，adaptive/asynchronous 就够用，不必上显式反馈端点
 * （反馈端点会占掉 0x84，把 UVC 顶掉）。若选 44100，就得按 9/10 的比例交替发
 * 44 和 45 个样本并跟踪相位漂移 —— 那正是逼人上反馈端点的场景。
 *
 * 升级阶梯：32 kHz 单声道与 16 kHz 立体声只多吃 10 words FIFO，属于「几乎免费」
 * 的档位；48 kHz 立体声不可行。等 UVC 的可行性结论出来之后再抬。
 */
#define UAC_SAMPLE_RATE      16000
#define UAC_CHANNEL_COUNT    1
#define UAC_BYTES_PER_SAMPLE 2
#define UAC_FRAME_SAMPLES    (UAC_SAMPLE_RATE / 1000)
#define UAC_FRAME_BYTES      (UAC_FRAME_SAMPLES * UAC_CHANNEL_COUNT * UAC_BYTES_PER_SAMPLE)

/*
 * 端点最大包 = 标称帧 + 一个样本的余量（按 word 对齐取 4 字节）。
 * 异步 IN 在设备时钟略快于 host 帧钟时需要偶尔多发一个样本；adaptive OUT 同理，
 * host 也可能多送一个。端点大小恰等于标称值会把这条路堵死，只能丢样本 ——
 * 听感是周期性的轻微咔哒，而且极难归因。代价是各多 1 个 word 的 FIFO。
 */
#define UAC_EP_OUT_SIZE      (UAC_FRAME_BYTES + 4)
#define UAC_EP_IN_SIZE       (UAC_FRAME_BYTES + 4)

_Static_assert(UAC_SAMPLE_RATE % 1000 == 0,
               "采样率必须产生整数 samples/ms，否则要上显式反馈端点（会顶掉 UVC）");

/*
 * 播放链上 Feature Unit（音量 / 静音）的 bUnitID。
 *
 * 描述符（usb_descriptors.c）与控制请求回调（codec_audio.c 的
 * tud_audio_*_req_entity_cb）必须用**同一个** ID：host 的每一条音量请求都把它放在
 * wIndex 的高字节里，对不上号的表现是「alsamixer 里有滑块但拖了不出声」，
 * 而 TinyUSB 只会静默 STALL。所以在这里定名，两边都引用它。
 *
 * 取 5 而不是插进 1..4 中间：终端 ID 1..4（USB流/喇叭/麦克风/USB流）已实机验证，
 * 且录音侧那条 AS 接口的 bTerminalLink 指着 ID4 —— 重新编号会连带动到与本次
 * 改动毫无关系的录音链。UAC1 只要求实体 ID 在本功能内唯一，不要求连续或有序。
 */
#define UAC_FU_ID_SPEAKER 5

/*
 * ── UVC（USB Video Class）：MJPEG 640×360 @ 10 fps ──────────────────
 *
 * 分辨率是**像素管线**定的，不是带宽定的（spec §7 原写 640×480，本阶段订正）：
 *   ① SC202CS 唯一能用的 MIPI 模式是 1280×720（1600×1200 超出 P4 ISP 的
 *      1920×1080 上限，1600×900 裁不出 4:3）；
 *   ② P4 的 ISP **没有缩放器**（esp_driver_isp 只有 isp_crop.h，能裁不能缩）；
 *   ③ 唯一的缩放器 PPA 的缩放比粒度是 1/16 ⇒ 1280×720 ×0.5 = 640×360 精确，
 *      而 640×480 需要 2/3，1/16 表达不出来（最近的 11/16 给出 660×495）。
 * 附带：640/16=40、360/8=45 都整除 4:2:2 的 MCU(16×8)，编码器不必补边；
 * 而且与 GUD 显示模式同为 640×360，整个包只有一个分辨率要记。
 */
#define UVC_W                640
#define UVC_H                360
#define UVC_FPS              10
/* dwFrameInterval 的单位是 100 ns ⇒ 10 fps = 1,000,000。
 * video_device.c:560-561 有 TU_ASSERT(interval/10000 != 0)，即帧间隔不得小于 1 ms。 */
#define UVC_FRAME_INTERVAL   (10000000 / UVC_FPS)

/*
 * ISO IN 端点大小 = 448 字节（112 words FIFO）。
 *
 * 上限是 **492 字节**，由 DWC2 的 dfifo 账算出来，**不是 1023(全速 ISO 的规范上限)**：
 *   dfifo 顶 = 256 − 2×ep_count(7) = **242 words**（dcd_dwc2.c:257-263，
 *     is_dma 成立：CONFIG_TINYUSB_MODE_DMA=y 且 P4 的 OTG11_ARCHITECTURE=2=INTERNAL_DMA）
 *   已用 = RX 62 + EP0 16 + vendor IN 16 + HID 16 + UAC 录音 IN 9 = 119
 *   余量 = 242 − 119 = 123 words = 492 字节
 * 取 448 而不取满 492：① dfifo_alloc() 装不下时只是 TU_ASSERT 返回 false、
 * **无日志**，症状是 SET_INTERFACE 被 STALL；② 448 在 is_dma 为真(余 123)与为假
 * (余 137) 两种假设下都成立；③ 代价只有 9% 带宽，而 640×360@10fps 有 1.5–2.6 倍余量。
 */
#define UVC_EP_SIZE          448
/* 每包被 UVC 载荷头吃掉 2 字节（video_device.c:1174-1176）。 */
#define UVC_PAYLOAD_HDR      2

/*
 * 一帧 JPEG 的上限。同时是 cam_jpeg.c 输出缓冲的大小。
 *
 * ⚠️ 这个数**不能随便填小**：TinyUSB 用
 *     dwMaxPayloadTransferSize = min(ceil(dwMaxVideoFrameSize/interval_ms) + 2,
 *                                    CFG_TUD_VIDEO_STREAMING_EP_BUFSIZE)
 * （video_device.c:562-567），而 uvcvideo 把我们声明的 dwMaxVideoFrameBufferSize
 * 原样填进 COMMIT。填 30000 的话每包只发 302 字节，带宽白掉三分之一，
 * **而且哪里都不报错**。下面那条 _Static_assert 守着这件事。
 */
#define UVC_MAX_FRAME_BYTES  65536

_Static_assert((UVC_MAX_FRAME_BYTES / (UVC_FRAME_INTERVAL / 10000)) + 2 > UVC_EP_SIZE,
               "dwMaxVideoFrameBufferSize 太小，TinyUSB 会把每包缩到不足 UVC_EP_SIZE，"
               "带宽静默损失（见 video_device.c 的 dwMaxPayloadTransferSize 计算）");
_Static_assert(UVC_W % 16 == 0 && UVC_H % 8 == 0,
               "4:2:2 的 MCU 是 16×8，两个方向都要整除，否则编码器要补边");

/* HID Report ID。键盘与触摸共用 IF1 这一个接口与 EPNUM_HID 这一条 IN 端点
 * （P4 全速控制器最多 4 条 IN 端点，UAC/UVC 会用满，见 firmware/README.md），
 * 靠 Report ID 区分 —— 这也是本接口必须放弃 boot 协议的原因，见 usb_descriptors.c。 */
#define HID_RID_KEYBOARD 1
#define HID_RID_TOUCH    2

/*
 * 描述符数据由 esp_tinyusb 经 tinyusb_config_t 注入；不要在本工程实现
 * tud_descriptor_*_cb，否则与 esp_tinyusb 的实现重复符号。
 */
extern const tusb_desc_device_t aio_desc_device;
extern const uint8_t aio_desc_configuration[];
extern const char *aio_string_desc_arr[];
extern const int aio_string_desc_count;
