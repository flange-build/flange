/*
 * UVC 视频流的设备侧实现：帧泵任务 + 两个 video class 回调。
 *
 * P4 Task5 的帧源是 flash 里那张静态测试图（uvc_test_jpeg.h），**没有摄像头、
 * 没有 ISP、没有 JPEG 编码器、没有 PPA**。这一步只回答一个问题：
 * TinyUSB 的 video class 能不能把一段现成的 JPEG 分包推给 uvcvideo 并被解出来。
 * 摄像头 bring-up 与 UVC 传输同时上，出问题时无法归因 —— 见计划 Task5 开头。
 */
#include "uvc_stream.h"
#include "usb_descriptors.h"   /* UVC_FPS / UVC_EP_SIZE / UVC_PAYLOAD_HDR / UVC_MAX_FRAME_BYTES */
#include "uvc_test_jpeg.h"     /* 帧源：k_uvc_test_jpeg（常驻 flash 的 .rodata） */
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "tusb.h"
#include <inttypes.h>

static const char *TAG = "uvc";

#define UVC_CTL_IDX   0    /* 只有一个 VideoControl 功能（CFG_TUD_VIDEO == 1） */
#define UVC_STM_IDX   0    /* 它下属唯一一个 VideoStreaming 接口 */

#define UVC_TASK_STACK_SIZE 4096
/*
 * 与 TinyUSB 的任务同优先级（esp_tinyusb 的 TINYUSB_DEFAULT_TASK_PRIO = 5），
 * 与 P3 的音频数据泵取同一个值、同一个理由：本任务绝大部分时间阻塞在
 * xTaskDelayUntil() 上，没有理由压过 USB 栈；同优先级下时间片轮转，都不会饿死。
 * 若 Task 10 的复合回归发现显示掉帧，降到 4 再测。
 */
#define UVC_TASK_PRIORITY   5

/* 这一帧要占几个 ISO 包。每包被 UVC 载荷头吃掉 UVC_PAYLOAD_HDR 字节
 * （video_device.c 的 _prepare_in_payload()），全速 ISO 一个 USB 帧(1 ms)发一包
 * ⇒ 这个数同时就是「一帧要在总线上占多少毫秒」。静态图 2869 B ⇒ 7 包 ⇒ 7 ms，
 * 相对 100 ms 的拍子有十几倍余量，**所以本阶段测不出吞吐**，见 uvc_stream.h。 */
#define UVC_FRAME_PACKETS \
    ((sizeof(k_uvc_test_jpeg) + (UVC_EP_SIZE - UVC_PAYLOAD_HDR) - 1) / (UVC_EP_SIZE - UVC_PAYLOAD_HDR))

_Static_assert(sizeof(k_uvc_test_jpeg) <= UVC_MAX_FRAME_BYTES,
               "静态测试图超过了描述符声明的 dwMaxVideoFrameBufferSize，host 会按声明值截断");

/*
 * 统计量。**全部只在自检快照里读**，不参与任何控制流 —— 它们的唯一用途是让
 * 「host 根本没打开摄像头」「打开了但一帧都没提交」「提交了但没发完」
 * 这三种完全不同的失败在串口上长得不一样（对应计划 Task5 Step6 的第 3/4/5 条）。
 *
 * volatile：s_frames_sent 与 s_commit_* 由 USB 侧的回调写（中断延续 / 控制传输
 * 处理路径），帧泵任务与 report 读。32 位对齐读写在 P4 上是原子的，计数器又只做
 * 单向累加，不需要更强的同步。
 */
static volatile uint32_t s_frames_submitted;  /* tud_video_n_frame_xfer() 成功次数 */
static volatile uint32_t s_frames_sent;       /* 完成回调次数 = host 真正收全的帧 */
static volatile uint32_t s_frames_refused;    /* 驱动拒收：上一帧还在飞，或端点没开 */
static volatile uint32_t s_commits;           /* host 下发 COMMIT(SET_CUR) 的次数 */
static volatile uint32_t s_commit_payload;    /* dwMaxPayloadTransferSize，见下 */
static volatile uint32_t s_commit_frame_max;  /* dwMaxVideoFrameSize */
static volatile uint32_t s_commit_interval;   /* dwFrameInterval，单位 100 ns */

/*
 * host 提交 COMMIT 时到。四个可选回调（video_device.c:205-227 全是 TU_ATTR_WEAK）
 * 里我们只实现两个：这一个用来把协商结果记下来，另一个用来数发完的帧。
 *
 * ⚠️ 这里**只记录、不做任何耗时的事**：它跑在 USB 控制传输的处理路径上，
 * 阻塞会让 SET_CUR 超时，host 侧表现为 "Failed to set VS commit" 然后放弃。
 * 真正的启停（Task9 起的 CSI start/stop）交给帧泵任务按 tud_video_n_streaming() 判断。
 */
int tud_video_commit_cb(uint_fast8_t ctl_idx, uint_fast8_t stm_idx,
                        video_probe_and_commit_control_t const *param)
{
    (void)ctl_idx;
    (void)stm_idx;
    /*
     * dwMaxPayloadTransferSize 是 TinyUSB **算出来**的（不是我们填的）：
     *     min(ceil(dwMaxVideoFrameSize/interval_ms) + 2, CFG_TUD_VIDEO_STREAMING_EP_BUFSIZE)
     * 它就是每毫秒真正能发多少字节。**这条记录是那个静默带宽陷阱唯一的现场证据**：
     * 它若小于 UVC_EP_SIZE(448)，说明 dwMaxVideoFrameBufferSize 声明小了，
     * 带宽白掉一截而哪里都不会报错（usb_descriptors.h 有 _Static_assert 守着我们
     * 声明的值，但 host 有权在 COMMIT 里填更小的 dwMaxVideoFrameSize，
     * 所以运行时也记一笔）。对应计划 Task5 Step6 的第 3 条。
     */
    s_commit_payload = param->dwMaxPayloadTransferSize;
    s_commit_frame_max = param->dwMaxVideoFrameSize;
    s_commit_interval = param->dwFrameInterval;
    s_commits++;
    return VIDEO_ERROR_NONE;
}

/* 一帧发完（最后一包带 EOF 位，由 _prepare_in_payload() 自己置）。
 * 只累加计数，不在这里提交下一帧 —— 这个回调跑在 USB 中断上下文的延续里，
 * 在这里提交意味着把 memcpy/编码搬进中断，会把 USB 栈钉住。 */
void tud_video_frame_xfer_complete_cb(uint_fast8_t ctl_idx, uint_fast8_t stm_idx)
{
    (void)ctl_idx;
    (void)stm_idx;
    s_frames_sent++;
}

/*
 * 取下一帧。Task5 = flash 里的静态图，**不拷贝**：video_device.c 的
 * _prepare_in_payload() 是从这里 memcpy 进 EP 缓冲的，源在 flash 完全没问题。
 *
 * ⚠️ tud_video_n_frame_xfer() 的缓冲**在整帧发完之前不能被改写**（驱动只记指针，
 *    分包时逐次 memcpy）。静态图在 .rodata 里天然满足；Task6 起换成 PSRAM 缓冲时
 *    **必须双缓冲**，否则编码器会一边写、UVC 一边读同一块内存，
 *    表现为画面横向撕裂 —— 这条要写进 cam_jpeg.c。
 */
static bool uvc_frame_source_get(const uint8_t **buf, size_t *len)
{
    *buf = k_uvc_test_jpeg;
    *len = sizeof(k_uvc_test_jpeg);
    return true;
}

static void uvc_pump_task(void *arg)
{
    (void)arg;
    TickType_t next = xTaskGetTickCount();
    const TickType_t period = pdMS_TO_TICKS(1000 / UVC_FPS);   /* 10 fps ⇒ 100 ms */

    while (1) {
        vTaskDelayUntil(&next, period);       /* 固定节拍，不受上一帧耗时影响 */

        /*
         * host 停在 alt 0（没开摄像头）：什么都不做，一个 tud_video_* 都不调。
         * ISO **带宽**此刻没有被主机预留，12 Mbps 全归 GUD 的 bulk ——
         * 这是 spec §2.1「带宽零和」的落点，也是硬约束「摄像头不开时对显示零影响」。
         * ⓘ 设备侧的 **FIFO** 不是这样：它在 SET_CONFIGURATION 时就分掉了，
         *   与 alt 无关，见 app_main.c 的 log_usb_fifo_usage()。
         */
        if (!tud_mounted() || !tud_video_n_streaming(UVC_CTL_IDX, UVC_STM_IDX))
            continue;

        const uint8_t *buf;
        size_t len;
        if (!uvc_frame_source_get(&buf, &len))   /* Task5 恒为真；Task6/9 换实现后会失败 */
            continue;

        /*
         * **不自己维护「一帧在飞」的标志，直接问驱动。**
         *
         * video_device.c:1293 本来就会在 stm->bufsize 非 0（上一帧没发完）时返回
         * false，驱动才是这件事唯一的真相来源。用一个模块内的 in_flight 标志去
         * 影子跟踪它，会在 host 快速 alt1→alt0→alt1 时死锁：切到 alt 0 时驱动在
         * _open_vs_itf() 里把 bufsize 清了、完成回调**不会**再来，而标志留在 true，
         * 从此每一拍都以为上一帧还在飞，流再也起不来（只能重新插拔）。
         *
         * 拒收就**跳过本拍、不排队**：视频丢一帧远比积压一串陈旧帧好 —— 积压会让
         * 画面越来越滞后，用户看到的是「延迟越来越大」，比掉帧难受得多也难归因。
         * 这个计数持续非零就说明帧太大/太密，Task6 起去调 cam_jpeg.c 的 image_quality。
         */
        if (tud_video_n_frame_xfer(UVC_CTL_IDX, UVC_STM_IDX, (void *)buf, len))
            s_frames_submitted++;
        else
            s_frames_refused++;
    }
}

bool uvc_stream_is_streaming(void)
{
    return tud_video_n_streaming(UVC_CTL_IDX, UVC_STM_IDX);
}

void uvc_stream_report(void)
{
    /*
     * 判据（对应计划 Task5 Step6）：
     *   streaming=0 一直不变      ⇒ host 没选中 alt 1，问题在协商/描述符（第 1–3 条）
     *   streaming=1 但 提交=0     ⇒ 帧泵没跑起来（任务没建/优先级饿死）
     *   提交 一直涨、完成 不涨     ⇒ 包发不出去，多半是 EP4 IN 的 FIFO 没分到（第 4 条）
     *   完成 涨但 host 画面不对    ⇒ JPEG 数据本身或分包（第 5 条）
     *   payload≠448               ⇒ dwMaxVideoFrameBufferSize 那个静默带宽陷阱（第 3 条）
     */
    ESP_LOGI(TAG, "[自检] streaming=%d 提交=%" PRIu32 " 完成=%" PRIu32 " 拒收=%" PRIu32
                  " | commit×%" PRIu32 " payload=%" PRIu32 "(应为 %u)"
                  " frame_max=%" PRIu32 " interval=%" PRIu32
                  " | 帧源=%u 字节/%u 包（静态图，测不出吞吐）",
             uvc_stream_is_streaming(),
             s_frames_submitted, s_frames_sent, s_frames_refused,
             s_commits, s_commit_payload, (unsigned)UVC_EP_SIZE,
             s_commit_frame_max, s_commit_interval,
             (unsigned)sizeof(k_uvc_test_jpeg), (unsigned)UVC_FRAME_PACKETS);
}

esp_err_t uvc_stream_start(void)
{
    if (xTaskCreate(uvc_pump_task, "uvc", UVC_TASK_STACK_SIZE, NULL,
                    UVC_TASK_PRIORITY, NULL) != pdPASS)
        return ESP_ERR_NO_MEM;

    ESP_LOGI(TAG, "UVC 帧泵已启动：MJPEG %dx%d @ %d fps，帧源=flash 静态测试图 %u 字节/%u 包",
             UVC_W, UVC_H, UVC_FPS, (unsigned)sizeof(k_uvc_test_jpeg),
             (unsigned)UVC_FRAME_PACKETS);
    return ESP_OK;
}
