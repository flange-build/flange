/*
 * UVC 视频流的设备侧实现：帧泵任务 + 两个 video class 回调。
 *
 * P4 Task9 起帧源是**真实摄像头**，整条链路在本文件的 uvc_frame_source_get() 里
 * 串起来（这是 Task6 建立的、也是唯一的一处接缝）：
 *
 *   camera_csi_get_frame()  SC202CS → CSI → ISP → 1280×720 RGB565 (PSRAM)
 *        ↓ cam_jpeg_downscale()      PPA SRM ×8/16 → 640×360 RGB565
 *        ↓ cam_jpeg_encode()         硬件 JPEG 4:2:2 → 约 20~35 KB
 *        ↓ tud_video_n_frame_xfer()  ISO IN 0x84，448 B/ms
 *
 * 帧源换过三次，USB 侧一行没动过：Task5 是 flash 里一张静态图（uvc_test_jpeg.h
 * 保留着），Task6 是片上实时编码的合成图案（uvc_pattern.c 保留着，但已从
 * CMakeLists 的 SRCS 里去掉 —— 它仍是静态测试图的生成源与宿主机测试对象），
 * Task9 是摄像头。要回退帧源只需改本文件的那一个函数。
 *
 * ⚠️ **摄像头的启停也归本文件**：host 停在 alt 0（没人开摄像头）时 CSI 不取流、
 *   PPA 不提交、编码器空闲，PSRAM 与 USB 带宽双双归零 —— 这是 spec §2.1
 *   「带宽零和」在两条总线上的共同落点，见 uvc_pump_task() 里那段启停。
 */
#include "uvc_stream.h"
#include "usb_descriptors.h"   /* UVC_FPS / UVC_EP_SIZE / UVC_PAYLOAD_HDR / UVC_MAX_FRAME_BYTES */
#include "tab5_pins.h"         /* CAM_SENSOR_W / CAM_SENSOR_H */
#include "cam_jpeg.h"          /* 帧源后两段：PPA 缩放 + 硬件 JPEG 编码器 */
#include "camera_csi.h"        /* 帧源第一段：CSI/ISP 取流与启停 */
#include "cam_frame_stats.h"   /* 帧内容统计（Task8 的观测设施，随帧源一起搬过来） */
#include "esp_cache.h"         /* esp_cache_get_alignment：PPA 输出缓冲的对齐要求 */
#include "esp_heap_caps.h"
#include "esp_log.h"
#include "esp_timer.h"
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
 * 取一帧等多久。传感器是 30 fps 固定（33 ms 一帧），取 3 倍 = 100 ms：
 * 真丢帧时宁可跳一拍，也不要把帧泵任务钉在这里 —— 那会让 UVC 侧连「没有新帧」
 * 都表达不出来（既不提交也不回到循环顶，节拍整个乱掉）。
 * 超时次数记在 camera_csi 的「取帧超时」里，不在本文件重复计一遍。
 */
#define UVC_CAM_WAIT_MS  (3 * 1000 / 30)

/* 帧内容统计的采样步长：每 8 行取一行、行内每 8 个取一个 ⇒ 只碰 1/64 的像素。
 * 全采样 92 万像素每帧要好几毫秒，观测本身就会变成干扰源。 */
#define UVC_STATS_STEP   8

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
 * 缩放后的帧缓冲：640×360 RGB565 = 460,800 字节，**必须放 PSRAM**（内部 RAM
 * 拢共只剩四百多 KB，见 README 的资源占用一节）。它同时是 PPA 的输出与 JPEG
 * 编码器的输入，两个 DMA 都从这里过。
 *
 * ⚠️ **必须按 cache line 对齐分配**，普通 heap_caps_malloc() 不行：
 *    ppa_srm.c:186-189 对 out.buffer 的**地址**与 out.buffer_size 两者都硬性
 *    检查对齐，不过就返回 ESP_ERR_INVALID_ARG —— 症状是「一帧都出不来」，
 *    从 host 侧完全看不出是内存对齐的事。（JPEG 编码器那侧反而没有这个要求，
 *    jpeg_encode.c:250 的 C2M 带 UNALIGNED 标志，所以 Task6 用普通 malloc
 *    一直没事 —— 这条限制是 Task9 引入 PPA 才出现的，计划里没写。）
 *    长度 460800 = 128 × 3600，64/128 两种 line size 都整除，天然满足；
 *    首地址交给 MALLOC_CAP_CACHE_ALIGNED —— 它会去问 esp_cache_get_alignment()
 *    （heap_align_hw.c:51），与 PPA 驱动自己算那个数时用的是同一个函数
 *    （ppa_core.c:68-69），所以「我们分配的」与「驱动检查的」必然同源，
 *    不靠记忆写 64。
 */
static uint16_t *s_rgb;

/* 摄像头当前该不该取流。**唯一的真相是 tud_video_n_streaming()**，本标志只用来
 * 检出「变了」这个边沿，好让 start/stop 每次切换只调一次。 */
static bool     s_cam_running;
static int32_t  s_cam_last_err = ESP_OK;   /* 最近一次 start/stop 的返回值 */

/*
 * ══ Task8 的观测设施，随帧源一起搬到这里 ═══════════════════════════
 *
 * Task8 那个临时自检任务（开机强制取流 120 秒）已经删掉 —— 它的行为与
 * 「alt 0 时摄像头零影响」直接冲突。但它带的那几个**判据**连着两轮直接点名了
 * 根因，一个都不能丢，所以搬到真实链路上来：
 *   亮度均值/最暗/最亮  画面是不是真的跟着物理世界变（挡镜头掉、手电冲高）
 *   校验和              帧与帧之间变不变（不变 ⇒ 取到的是同一块没被重写的缓冲）
 *   下 1/8 的均值/最亮   **DMA 截断的指纹**：CSI 只填上半张时，全帧的四个数照样
 *                       随镜头变化，只有下 1/8 恒为 0（详见 camera_csi.c 的
 *                       csi_transfer_size 那段）
 * 统计对象是**缩放前的 1280×720 原帧**，因为要判的是 CSI/ISP 那一段。
 *
 * ⓘ 全帧统计从「每秒一次」改成了**每帧一次**：它现在同时是自动曝光与自动白平衡
 *   的输入（camera_csi_tune_tick 把硬件统计喂给官方 esp_ipa），而节奏是按「拍」算的，
 *   隔一秒喂一次数据会让官方算法的帧延迟/迟滞（按帧标定）全部失去意义。
 *   代价：1/64 采样约 2 ms/帧 × 10 fps = **每秒 20 ms**，占取流期 PSRAM 时间的
 *   2%，比 CSI 自己那 55 MB/s 小两个数量级；换来的是曝光与白平衡都能闭上环
 *   （AWB 的三个通道均值就在同一次扫描里顺带算出来，不多扫一遍）。
 *   下 1/8 那份仍然每秒一次 —— 它判的是 DMA 截断，与曝光无关，没必要跟着加密。
 */
static uint32_t          s_stat_phase;
static cam_frame_stats_t s_stat_full;
static cam_frame_stats_t s_stat_bottom;
static uint32_t          s_full_max_ever;
static uint32_t          s_bottom_max_ever;

/* PSRAM 读带宽三点实测（MB/s），0 = 还没量过。取流中那一次是本阶段新增的一档：
 * 它比 Task8 那次多了 PPA 的读写与 JPEG 编码器的读写。 */
static uint32_t s_bw_idle;
static uint32_t s_bw_stream;
static uint32_t s_bw_after;
static uint32_t s_bw_stream_countdown;   /* 取流开始后再等这么多帧才量 */

/* 实测 fps 用：上一次自检快照时的完成帧数与时刻。 */
static uint32_t s_fps_last_sent;
static int64_t  s_fps_last_us;

/*
 * 全帧统计：每帧都做。
 *
 * ⓘ **纯观测**，不再是任何控制律的反馈量 —— 画质由官方 esp_ipa 用**硬件**统计
 *   闭环（见 cam_ipa.h）。它回答的是「帧里有没有东西、变不变」这类自检判据，
 *   逆 gamma 那一套已随自研控制律一并删除（见 cam_frame_stats.h）。
 */
static void frame_stats_sample(const uint16_t *raw)
{
    cam_frame_stats_rgb565(raw, CAM_SENSOR_W, CAM_SENSOR_H,
                           UVC_STATS_STEP, &s_stat_full);
    if (s_stat_full.lum_max > s_full_max_ever)
        s_full_max_ever = s_stat_full.lum_max;
}

/* 下 1/8 的统计：只为判 DMA 截断，每秒一次就够。
 * 缓冲是行连续的，把指针推到 7/8 处、高度传 1/8 即可，复用同一个已测函数。 */
static void frame_stats_sample_bottom(const uint16_t *raw)
{
    const int bottom_rows = CAM_SENSOR_H / 8;

    cam_frame_stats_rgb565(raw + (size_t)(CAM_SENSOR_H - bottom_rows) * CAM_SENSOR_W,
                           CAM_SENSOR_W, bottom_rows, UVC_STATS_STEP, &s_stat_bottom);
    if (s_stat_bottom.lum_max > s_bottom_max_ever)
        s_bottom_max_ever = s_stat_bottom.lum_max;
}

/*
 * 取下一帧：CSI 取流 → PPA 缩小 → 硬件编码。返回的指针指向 cam_jpeg 的双缓冲之一。
 *
 * 三步各自的失败**都已经有计数器**，所以这里只返回 false、不再重复计一遍：
 *   取帧失败 → camera_csi_report() 的「取帧超时」
 *   缩放失败 → cam_jpeg_scale_stats() 的 failed
 *   编码失败 → cam_jpeg_stats() 的 failed
 * 自检快照三行并排，一眼就能看出是哪一段断的。
 *
 * ⚠️ tud_video_n_frame_xfer() 的缓冲**在整帧发完之前不能被改写**（驱动只记指针，
 *    分包时逐次 memcpy）。这就是 cam_jpeg 双缓冲存在的理由，以及下面提交成功后
 *    必须调 cam_jpeg_frame_committed() 的理由。
 *    ⓘ s_rgb **不需要**双缓冲：它在本函数返回前就被编码器读完了（编码是同步阻塞
 *      调用），UVC 驱动拿到的是 JPEG 输出缓冲，从不碰 s_rgb。
 */
static bool uvc_frame_source_get(const uint8_t **buf, size_t *len)
{
    const uint16_t *raw = NULL;
    if (camera_csi_get_frame(&raw, UVC_CAM_WAIT_MS) != ESP_OK)
        return false;

    /*
     * 内容统计。统计的是**缩放前**的原帧 —— 要判的是 CSI/ISP 段，而且 AE 要控的
     * 也是传感器的曝光，两者都必须在缩放/编码之前取。
     * 顺序上紧贴取帧、排在缩放之前：PPA 与 JPEG 各要几毫秒，插在中间只会让
     * 「反馈量对应哪一帧」变得更含糊。
     */
    frame_stats_sample(raw);
    camera_csi_tune_tick(&s_stat_full);

    /* 下 1/8 那份每秒一次就够，它判的是 DMA 截断，与曝光无关。 */
    if (++s_stat_phase >= UVC_FPS) {
        s_stat_phase = 0;
        frame_stats_sample_bottom(raw);
    }

    if (cam_jpeg_downscale(raw, s_rgb) != ESP_OK)
        return false;

    size_t n = 0;
    if (cam_jpeg_encode(s_rgb, UVC_W, UVC_H, buf, &n) != ESP_OK)
        return false;
    *len = n;
    return true;
}

static void uvc_pump_task(void *arg)
{
    (void)arg;
    TickType_t next = xTaskGetTickCount();
    const TickType_t period = pdMS_TO_TICKS(1000 / UVC_FPS);   /* 10 fps ⇒ 100 ms */

    /* 一切开始之前量一次空载 PSRAM 读带宽，作为另外两个数的基线。
     * 此刻 CSI 已经 init（app_main 的顺序）但没取流，屏幕上是待机画面 ——
     * 也就是「只有 DPI 面板在读 PSRAM」这个基准态。 */
    s_bw_idle = camera_csi_psram_read_mbps();

    while (1) {
        vTaskDelayUntil(&next, period);       /* 固定节拍，不受上一帧耗时影响 */

        /*
         * host 选中 alt 1 才开 CSI，回到 alt 0 立刻停。
         *
         * USB 侧：alt 0 时主机没有预留任何 ISO 带宽，12 Mbps 全归 GUD 的 bulk。
         * PSRAM 侧：不取流则 CSI 不写那 55 MB/s、PPA 不提交、编码器空闲，
         *   而 DPI 面板刷新常驻要读 89～107 MB/s —— 那是它们的直接竞争者。
         * 两条合起来才是「摄像头不开时对显示零影响」的完整实现。
         *
         * ⓘ 设备侧的 **FIFO** 不在此列：它在 SET_CONFIGURATION 时就分掉了，
         *   与 alt 无关，见 app_main.c 的 log_usb_fifo_usage()。
         */
        const bool want = tud_mounted() &&
                          tud_video_n_streaming(UVC_CTL_IDX, UVC_STM_IDX);
        if (want != s_cam_running) {
            const esp_err_t rc = want ? camera_csi_start() : camera_csi_stop();
            s_cam_last_err = rc;
            /*
             * **无论成败都认下这次切换**，不重试。失败时重试意味着每 100 ms 重跑
             * 一遍启动链（含几十毫秒 I2C），既拖垮帧泵又刷屏，而根因（摄像头没探到
             * /CSI 没建起来）不会因为多试几次就好。失败记在 s_cam_last_err 里，
             * 由自检快照说出来；host 侧的表现是「有 /dev/videoN 但取不到流」。
             */
            s_cam_running = want;
            if (want) {
                s_bw_stream = 0;
                s_bw_stream_countdown = UVC_FPS;   /* 稳定约 1 秒后再量带宽 */
            } else {
                s_bw_after = camera_csi_psram_read_mbps();
            }
            if (rc == ESP_OK)
                ESP_LOGI(TAG, "摄像头取流%s（host 切到 alt %d）",
                         want ? "开始" : "停止", want ? 1 : 0);
            else
                ESP_LOGE(TAG, "摄像头%s失败(%s)，UVC 将发不出帧",
                         want ? "启动" : "停止", esp_err_to_name(rc));
        }
        if (!want)
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

        /* 取流稳定约一秒后量一次「CSI + PPA + JPEG 全开」那一档的 PSRAM 读带宽。
         * 每次 alt 0→1 只量一次：它自己要读 1 MB，量多了就成了干扰源。 */
        if (s_bw_stream_countdown && --s_bw_stream_countdown == 0)
            s_bw_stream = camera_csi_psram_read_mbps();
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

    /*
     * 第三行是 Task9 新加的：缩放段 + 实测 fps。
     *   缩放失败 非零 ⇒ PPA 提交被拒。**几乎只有一个原因**：s_rgb 没按 cache line
     *                   对齐（ppa_srm.c:186-189），而它是启动时一次性分配的，
     *                   所以要么全失败要么全成功，中间态不存在。
     *   缩放耗时      ⇒ 就是每 100 ms 里 display_blit() 可能被顶住的时长上界
     *                   （PPA 引擎是共享硬件，两个 client 在引擎信号量上排队）。
     *                   显示掉帧时先看这个数，别一上来就怪带宽。
     *   实测 fps      ⇒ 判据是 ≥9.0。**用「完成」而不是「提交」算** —— 提交了没发完
     *                   的帧 host 一帧都看不见，那不叫帧率。
     */
    uint32_t scaled = 0, sfail = 0, sus = 0;
    cam_jpeg_scale_stats(&scaled, &sfail, &sus);

    const int64_t now = esp_timer_get_time();
    uint32_t fps_x10 = 0;
    if (s_fps_last_us && now > s_fps_last_us)
        fps_x10 = (uint32_t)((int64_t)(s_frames_sent - s_fps_last_sent) * 10000000
                             / (now - s_fps_last_us));
    s_fps_last_sent = s_frames_sent;
    s_fps_last_us = now;

    ESP_LOGI(TAG, "[自检] 缩放=%" PRIu32 " 失败=%" PRIu32 " 耗时=%" PRIu32 " us"
                  " | 实测 %" PRIu32 ".%" PRIu32 " fps(距上一行自检)"
                  " | 摄像头启停=%s",
             scaled, sfail, sus, fps_x10 / 10, fps_x10 % 10,
             esp_err_to_name((esp_err_t)s_cam_last_err));

    /*
     * 第四行：画面内容与 PSRAM 带宽 —— Task8 那套观测设施，搬到真实链路上。
     *
     *   采样=0                 ⇒ 一次都没统计过，即从来没取到过帧（看上面 camera
     *                            的自检行，那里区分「没数据」与「帧长不符」）
     *   均值随遮挡/手电变       ⇒ 像素真的跟着物理世界走
     *   最暗==最亮             ⇒ **纯色**，不是真实画面
     *   校验和帧帧不变          ⇒ 取到的是同一块没被重写的缓冲
     *   下1/8 历史最亮恒为 0 而全帧见过光 ⇒ **DMA 只填了上半张**（见下面那条 ERROR）
     *   PSRAM 三个数：取流中比空载掉一两成算正常；掉一半以上说明 DPI 面板也在挨饿，
     *                 要重点看 GUD 有没有撕裂；停流后没回到空载 ⇒ 停流没停干净。
     */
    ESP_LOGI(TAG, "[自检] 画面 采样=%" PRIu32 " 均值%u 最暗%u 最亮%u"
                  " (下1/8 均值%u 最亮%u，历史最亮 全帧%" PRIu32 "/下1/8 %" PRIu32 ")"
                  " 校验和 %08" PRIx32
                  " | PSRAM 读 空载%" PRIu32 " → 取流中%" PRIu32 " → 停流后%" PRIu32 " MB/s",
             s_stat_full.samples, s_stat_full.lum_mean, s_stat_full.lum_min,
             s_stat_full.lum_max, s_stat_bottom.lum_mean, s_stat_bottom.lum_max,
             s_full_max_ever, s_bottom_max_ever, s_stat_full.checksum,
             s_bw_idle, s_bw_stream, s_bw_after);

    /* DMA 截断的自动判读，别让它只停留在「用户得自己注意那个括号里的数」。
     * 整段时间里全帧见过光、而最下面 1/8 一次都没亮过 ⇒ 那 1/8 从来没被写过。 */
    if (s_full_max_ever > 16 && s_bottom_max_ever == 0)
        ESP_LOGE(TAG, "[自检] ⚠️ 下 1/8 全程为零而全帧有画面 ⇒ **DMA 只填了上半张**，"
                      "camera_csi.c 的 csi_cfg.input_data_color_type 定的搬运字节数偏小");
}

esp_err_t uvc_stream_start(void)
{
    /*
     * 缓冲与编码器**在启动时一次建好**，不做按需分配：分配失败要在开机日志里
     * 立刻可见，而不是等 host 打开摄像头时才在帧泵里静默失败（那时 host 侧的
     * 表现是「有 /dev/videoN 但取不到流」，从现象反推不到内存不够）。
     * 代价是即便没人开摄像头也占着 PSRAM（460,800 + 2×65,536 ≈ 578 KB；CSI 那
     * 3×1.84 MB 由 camera_csi.c 另算）—— Tab5 有 32 MB PSRAM，付得起；
     * 而**带宽**上的代价是零：帧泵在 alt 0 时不取流、不缩放、不编码，
     * 三个引擎全空闲，一点 PSRAM 带宽都不碰。
     *
     * 对齐用 **MALLOC_CAP_CACHE_ALIGNED** 而不是自己写一个 64：让堆自己按它知道的
     * cache line 对齐，与 PPA 驱动检查时用的那个数（ppa_core.c:68-69 问
     * esp_cache_get_alignment()）必然同源。分配完再用公开的
     * esp_cache_get_line_size_by_addr() 复核长度也整除 —— 长度不对齐同样过不了
     * ppa_srm.c 那条检查，而 460800 只是**恰好**对 64/128 都整除，
     * 有人改 UVC_W/H 时得当场炸掉，别等上板查「一帧都没有」。
     */
    const size_t rgb_bytes = (size_t)UVC_W * UVC_H * 2;
    s_rgb = heap_caps_malloc(rgb_bytes, MALLOC_CAP_SPIRAM | MALLOC_CAP_CACHE_ALIGNED);
    if (!s_rgb) {
        ESP_LOGE(TAG, "帧缓冲分配失败（%u 字节 PSRAM，需按 cache line 对齐）",
                 (unsigned)rgb_bytes);
        return ESP_ERR_NO_MEM;
    }
    const size_t line = esp_cache_get_line_size_by_addr(s_rgb);
    if (line == 0 || (rgb_bytes % line) != 0) {
        ESP_LOGE(TAG, "缩放输出 %u 字节不是 cache line(%u) 的整数倍，PPA 会拒收",
                 (unsigned)rgb_bytes, (unsigned)line);
        heap_caps_free(s_rgb);
        s_rgb = NULL;
        return ESP_ERR_INVALID_SIZE;
    }

    esp_err_t err = cam_jpeg_init();   /* 编码器 + PPA 缩放 client */
    if (err != ESP_OK) {
        heap_caps_free(s_rgb);
        s_rgb = NULL;
        return err;
    }

    if (xTaskCreate(uvc_pump_task, "uvc", UVC_TASK_STACK_SIZE, NULL,
                    UVC_TASK_PRIORITY, NULL) != pdPASS)
        return ESP_ERR_NO_MEM;

    ESP_LOGI(TAG, "UVC 帧泵已启动：MJPEG %dx%d @ %d fps，"
                  "帧源=摄像头 %dx%d → PPA 缩放 → 硬件 JPEG"
                  "（每帧预算 %u 字节 = %u 包；CSI 由 alt 0/1 启停）",
             UVC_W, UVC_H, UVC_FPS, CAM_SENSOR_W, CAM_SENSOR_H,
             (unsigned)((UVC_EP_SIZE - UVC_PAYLOAD_HDR) * UVC_FRAME_MS),
             (unsigned)UVC_FRAME_MS);
    return ESP_OK;
}
