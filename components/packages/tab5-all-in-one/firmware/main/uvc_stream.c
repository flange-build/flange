/*
 * UVC 视频流的设备侧实现：帧泵任务 + 两个 video class 回调。
 *
 * P4 Task6 的帧源是**片上实时编码的合成图案**：uvc_pattern.c 渲染 RGB565 →
 * cam_jpeg.c 走 P4 的硬件 JPEG 编码器压成 MJPEG。**仍然没有摄像头、没有 CSI、
 * 没有 ISP、没有 PPA。** 相对 Task5（flash 里那张静态图，见 uvc_test_jpeg.h，
 * 文件保留着，回退帧源只需改本文件的 uvc_frame_source_get()）变量只有编码器一个，
 * 判据也只有一条、不需要任何日志：**ffplay 里那个白方块动起来了**。
 */
#include "uvc_stream.h"
#include "usb_descriptors.h"   /* UVC_FPS / UVC_EP_SIZE / UVC_PAYLOAD_HDR / UVC_MAX_FRAME_BYTES */
#include "cam_jpeg.h"          /* 帧源后半段：硬件 JPEG 编码器 */
#include "uvc_pattern.h"       /* 帧源前半段：合成图案（与 Task4 逐字节同一份） */
#include "esp_heap_caps.h"
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

/* 一帧要占几个 ISO 包。每包被 UVC 载荷头吃掉 UVC_PAYLOAD_HDR 字节
 * （video_device.c 的 _prepare_in_payload()），全速 ISO 一个 USB 帧(1 ms)发一包
 * ⇒ 这个数同时就是「一帧要在总线上占多少毫秒」，拿它跟 UVC_FRAME_MS 比，
 * 就是**唯一**能看出带宽还剩多少的算式，自检行里直接打出来。 */
#define UVC_FRAME_PACKETS(bytes) \
    (((bytes) + (UVC_EP_SIZE - UVC_PAYLOAD_HDR) - 1) / (UVC_EP_SIZE - UVC_PAYLOAD_HDR))

/* 一拍多少毫秒。10 fps ⇒ 100 ms，也就是一帧最多允许占 100 个 ISO 包。 */
#define UVC_FRAME_MS  (1000 / UVC_FPS)

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
 * 帧缓冲：640×360 RGB565 = 460,800 字节，**必须放 PSRAM**（内部 RAM 拢共只剩
 * 四百多 KB，见 README 的资源占用一节）。硬件 JPEG 编码器从 PSRAM 直读没问题：
 * 它走 2D-DMA，输入侧的 cache 回写由驱动自己做，且对输入缓冲没有对齐要求
 * （jpeg_encode.c:250 带 UNALIGNED 标志）。
 */
static uint16_t *s_rgb;
/* 帧号只在真正编码时才 ++，所以方块的位移严格等于「设备侧编出来的帧数」。
 * host 侧看到位移 ≠ STEP 就是丢帧 —— 见 uvc_pattern.c 里 span 取整那段注释。 */
static uint32_t  s_frame_no;

/*
 * 取下一帧：渲染 → 硬件编码。返回的指针指向 cam_jpeg 的双缓冲之一。
 *
 * ⚠️ tud_video_n_frame_xfer() 的缓冲**在整帧发完之前不能被改写**（驱动只记指针，
 *    分包时逐次 memcpy）。这就是 cam_jpeg 双缓冲存在的理由，以及下面提交成功后
 *    必须调 cam_jpeg_frame_committed() 的理由。
 */
static bool uvc_frame_source_get(const uint8_t **buf, size_t *len)
{
    if (!uvc_pattern_render(s_rgb, UVC_W, UVC_H, s_frame_no++))
        return false;
    size_t n = 0;
    if (cam_jpeg_encode(s_rgb, UVC_W, UVC_H, buf, &n) != ESP_OK)
        return false;   /* 失败次数记在 cam_jpeg 的统计里，自检行会打出来 */
    *len = n;
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
        if (!uvc_frame_source_get(&buf, &len))   /* 编码失败：跳过本拍，画面卡一帧 */
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
         * 这个计数持续非零就说明帧太大/太密，去调 cam_jpeg.c 的 CAM_JPEG_QUALITY。
         */
        if (tud_video_n_frame_xfer(UVC_CTL_IDX, UVC_STM_IDX, (void *)buf, len)) {
            s_frames_submitted++;
            /* 这一块缓冲从现在起归 UVC 驱动读，下一帧编到另一块去。
             * **必须在提交成功之后**，被拒收时不能转 —— 推导见 cam_jpeg.h。 */
            cam_jpeg_frame_committed();
        } else {
            s_frames_refused++;
        }
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
                  " frame_max=%" PRIu32 " interval=%" PRIu32,
             uvc_stream_is_streaming(),
             s_frames_submitted, s_frames_sent, s_frames_refused,
             s_commits, s_commit_payload, (unsigned)UVC_EP_SIZE,
             s_commit_frame_max, s_commit_interval);

    /*
     * 第二行是 Task6 新加的，判据（对应计划 Task6 Step1/Step5）：
     *   峰值 > 44 KB（占满 100/100 ms）⇒ 帧发不完，拒收会跟着涨，CAM_JPEG_QUALITY −10
     *   峰值 30–44 KB                  ⇒ 保持，但已经贴着预算，别再往上调质量
     *   峰值 < 20 KB 且 拒收=0          ⇒ 才允许 +10 换画质
     *   编码失败 非零                   ⇒ 编码器本身出错/超时，不是带宽问题
     *
     * 「峰值占 N/100 ms」就是带宽吃紧与否的直读数字：N 是这一帧要占多少个 ISO 包，
     * 全速 ISO 每毫秒一包，所以 N 同时就是毫秒数，分母是一拍的长度。
     */
    uint32_t enc = 0, fail = 0, us = 0;
    size_t last = 0, avg = 0, peak = 0;
    cam_jpeg_stats(&enc, &fail, &last, &avg, &peak, &us);
    ESP_LOGI(TAG, "[自检] 编码=%" PRIu32 " 失败=%" PRIu32
                  " | 帧字节 最近=%u 平均=%u 峰值=%u"
                  " → 峰值占 %u/%u ms | 编码耗时=%" PRIu32 " us",
             enc, fail, (unsigned)last, (unsigned)avg, (unsigned)peak,
             (unsigned)UVC_FRAME_PACKETS(peak), (unsigned)UVC_FRAME_MS, us);
}

esp_err_t uvc_stream_start(void)
{
    /*
     * 缓冲与编码器**在启动时一次建好**，不做按需分配：分配失败要在开机日志里
     * 立刻可见，而不是等 host 打开摄像头时才在帧泵里静默失败（那时 host 侧的
     * 表现是「有 /dev/videoN 但取不到流」，从现象反推不到内存不够）。
     * 代价是即便没人开摄像头也占着 PSRAM（460,800 + 2×65,536 ≈ 578 KB）——
     * Tab5 有 32 MB PSRAM，付得起；而**带宽**上的代价是零：帧泵在 alt 0 时
     * 一次都不渲染、不编码，编码器引擎完全空闲，不碰 PSRAM 也不碰 2D-DMA。
     */
    s_rgb = heap_caps_malloc((size_t)UVC_W * UVC_H * 2, MALLOC_CAP_SPIRAM);
    if (!s_rgb) {
        ESP_LOGE(TAG, "帧缓冲分配失败（%u 字节 PSRAM）", (unsigned)(UVC_W * UVC_H * 2));
        return ESP_ERR_NO_MEM;
    }

    esp_err_t err = cam_jpeg_init();
    if (err != ESP_OK) {
        heap_caps_free(s_rgb);
        s_rgb = NULL;
        return err;
    }

    if (xTaskCreate(uvc_pump_task, "uvc", UVC_TASK_STACK_SIZE, NULL,
                    UVC_TASK_PRIORITY, NULL) != pdPASS)
        return ESP_ERR_NO_MEM;

    ESP_LOGI(TAG, "UVC 帧泵已启动：MJPEG %dx%d @ %d fps，帧源=片上硬件编码的合成图案"
                  "（每帧预算 %u 字节 = %u 包）",
             UVC_W, UVC_H, UVC_FPS,
             (unsigned)((UVC_EP_SIZE - UVC_PAYLOAD_HDR) * UVC_FRAME_MS),
             (unsigned)UVC_FRAME_MS);
    return ESP_OK;
}
