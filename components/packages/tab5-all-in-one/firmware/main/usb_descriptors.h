#pragma once
#include "tusb.h"

/* mainline drm/gud 驱动绑定的固定 VID/PID，不可更改 */
#define GUD_VID 0x16d0
#define GUD_PID 0x10a9

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
 *
 * ⚠️ 音频三接口由 CONFIG_AIO_AUDIO_DESC 控制，**默认不编入**（见
 * main/Kconfig.projbuild）。关闭时 ITF_NUM_TOTAL 退回 2，配置描述符与音频
 * 落地之前逐位一致 —— 这正是「GUD 回归」的兜底。
 */
enum {
    ITF_NUM_VENDOR = 0,
    ITF_NUM_HID,                   /* 键盘 + 多点触摸，靠 Report ID 区分 */
#if CONFIG_AIO_AUDIO_DESC
    ITF_NUM_AUDIO_CONTROL,
    ITF_NUM_AUDIO_STREAMING_OUT,   /* 播放：host → ES8388 → 喇叭 */
    ITF_NUM_AUDIO_STREAMING_IN,    /* 录音：ES7210 双麦 → host */
#endif
    ITF_NUM_TOTAL
};

/*
 * 端点编号。P4 全速控制器 ep_count=7 / ep_in_count=5(**含 EP0**)，
 * 即非 EP0 的可用 IN 端点只有 **4 条**（tinyusb portable/synopsys/dwc2/dwc2_esp32.h）。
 *
 * | 0x81 | 0x82 | 0x83 | 0x84 |
 * |------|------|------|------|
 * | vendor(GUD) | HID | **UAC 录音** | **留给 UVC** |
 *
 * 超编时 dcd_dwc2.c 的 TU_ASSERT(allocated_epin_count < ep_in_count) 直接失败，
 * 且默认日志等级下**一个字都不打** —— 症状是 SET_INTERFACE 被 STALL、某个接口
 * 静默不工作，看起来与音频毫无关联。所以 0x84 必须留着。
 */
#define EPNUM_VENDOR_OUT 0x01
#define EPNUM_VENDOR_IN  0x81
#define EPNUM_HID        0x82
#if CONFIG_AIO_AUDIO_DESC
#define EPNUM_AUDIO_OUT  0x02      /* ISO OUT，播放 */
#define EPNUM_AUDIO_IN   0x83      /* ISO IN，录音；0x84 留给 UVC */
#endif

/*
 * ⚠️ CDC 调试串口与 UAC 音频**互斥**：CDC 自带 2 条 IN（通知 + 数据），
 * 加上 vendor 与 HID 正好把 4 条可用 IN 端点用满，音频 IN 就是第 5 条；
 * 而且它默认拿的就是 0x83/0x84，与音频、UVC 直接撞号。
 *
 * 把它变成编译期错误，而不是留给后人在一块**没有串口**的板子上调试一个
 * 「像是描述符写错」的枚举失败 —— 那正是最需要日志的时候最想打开 CDC 的时刻。
 */
#if CONFIG_AIO_AUDIO_DESC && CONFIG_TINYUSB_CDC_ENABLED
#error "CDC 调试串口与 UAC 音频互斥（IN 端点不够，且 0x83/0x84 撞号）：二选一 —— 要么把 CONFIG_AIO_AUDIO_MODE 设回「关闭」，要么把 sdkconfig.defaults 末尾那两行注释回去，然后 rm -f sdkconfig 重编"
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
