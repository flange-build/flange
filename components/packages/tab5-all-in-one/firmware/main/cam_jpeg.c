#include "cam_jpeg.h"
#include "usb_descriptors.h"   /* UVC_W / UVC_H / UVC_MAX_FRAME_BYTES */
#include "driver/jpeg_encode.h"
#include "esp_check.h"
#include "esp_log.h"
#include "esp_timer.h"

static const char *TAG = "cam_jpeg";

/*
 * 质量。**这不是观感参数，是带宽参数**：
 * 10 fps × 446 B/ms ⇒ 每帧预算 44.6 KB，目标是平均 ≤30 KB、峰值 ≤44 KB。
 *
 * 70 这个数的由来（宿主机实测，用同一张 uvc_pattern 渲染出来的 640×360 PPM，
 * libjpeg `cjpeg -sample 2x1`；IDF 的编码器用的是同一套 JPEG 标准 Annex K
 * 量化表与同一条质量缩放公式 —— jpeg_emit_marker.c:56-62 与 libjpeg 的
 * jpeg_quality_scaling() 逐字一致，所以宿主机的数在同一量级）：
 *
 *     q=50 → 6196 B    q=60 → 6286 B    q=70 → 6426 B
 *     q=80 → 6565 B    q=90 → 6910 B
 *
 * ⚠️ 注意这条曲线**几乎是平的**：本图案是 8 根平色条 + 一个白方块 + 一条平灰带，
 *    AC 系数基本为零，比特几乎全花在 DC 与 EOB 上，量化表怎么缩放都影响不到。
 *    也就是说 **Task6 的合成图案压根压不满这根管子**（约 6.5 KB/帧 ≈ 15 个包
 *    ≈ 15 ms，只用掉 100 ms 拍子的 15%），计划里「~20 KB / ~45 包」的估计是按
 *    照片那样的帧写的，对本图案不成立 —— 这一点必须说清楚，否则会把
 *    「Task6 一次都没拒收」误读成「带宽验过了」。真正压带宽要等真实摄像头画面。
 *
 * 所以 70 是**面向 Task9 真实画面**选的起始值（640×360 4:2:2 的照片类内容在
 * q=70 上典型 25–35 KB，落在预算内），而不是为本图案选的。调法与判据见计划
 * Task6 Step5：峰值 >44 KB 就 −10，<20 KB 且零拒收、fps ≥9.5 才允许 +10。
 */
#define CAM_JPEG_QUALITY 70

/*
 * 子采样固定 4:2:2，**不是 4:2:0**。
 * 4:2:0 的 MCU 是 16×16，而 UVC_H = 360 不是 16 的倍数（360 = 16×22.5）；
 * 4:2:2 的 MCU 是 16×8，640 与 360 都整除，编码器不必补边。
 * 代价是比 4:2:0 大 20%–25%，按上面的余量付得起。
 *
 * ⓘ RGB565 输入两种子采样都合法（jpeg_encode.c:145-147 只对 **YUV422 输入**
 *   强制 YUV422 子采样）。另注意 P4 rev <3.0 的编码器**不支持 YUV420/YUV444
 *   输入**（jpeg_encode.c:186-198 那个 `#if !(CONFIG_ESP_REV_MIN_FULL < 300
 *   && SOC_IS(ESP32P4))`），本固件正是 CONFIG_ESP32P4_REV_MIN_100，
 *   所以输入只能是 RGB888 / RGB565 / GRAY / YUV422 —— 我们用 RGB565
 *   （也正是 Task9 里 PPA 的输出色彩模式，那一步不用再换格式）。
 */
#define CAM_JPEG_SUBSAMPLE JPEG_DOWN_SAMPLING_YUV422

#define CAM_JPEG_BUFS 2

static jpeg_encoder_handle_t s_enc;
static uint8_t *s_out[CAM_JPEG_BUFS];
static size_t   s_out_cap[CAM_JPEG_BUFS];
/* 上一次**成功提交**给 UVC 的那一块（可能仍在飞）。编码永远写另一块，
 * 见 cam_jpeg.h 里 cam_jpeg_frame_committed() 的推导。 */
static int      s_busy_idx;

static uint32_t s_encoded;
static uint32_t s_failed;
static size_t   s_last_bytes;
static size_t   s_peak_bytes;
static uint64_t s_total_bytes;
static uint32_t s_last_us;

static inline int cam_jpeg_spare_idx(void)
{
    return (s_busy_idx + 1) % CAM_JPEG_BUFS;
}

esp_err_t cam_jpeg_init(void)
{
    ESP_RETURN_ON_FALSE(!s_enc, ESP_ERR_INVALID_STATE, TAG, "已初始化");

    /* timeout_ms 必须大于一次编码的有效耗时。10 fps 的拍子是 100 ms，给 200 ms：
     * 超时了宁可返回错误也不要把帧泵任务永远钉住（-1 = 永远等，那会让一次硬件
     * 异常变成「摄像头静默死掉」，连自检计数都不再动）。 */
    const jpeg_encode_engine_cfg_t eng = { .intr_priority = 0, .timeout_ms = 200 };
    ESP_RETURN_ON_ERROR(jpeg_new_encoder_engine(&eng, &s_enc), TAG, "JPEG 引擎");

    /* ⚠️ 输出缓冲**必须**用 jpeg_alloc_encoder_mem() 分配：jpeg_encode.c:144 会
     * 检查 bit_stream 的地址按 cache line 对齐，普通 heap_caps_malloc() 出来的
     * 指针过不了那条检查 —— 返回 ESP_ERR_INVALID_ARG，症状是「一帧都编不出来」
     * 而不是崩溃。这个 helper 分的是 PSRAM，并把 size 也向上对齐。 */
    const jpeg_encode_memory_alloc_cfg_t mem = {
        .buffer_direction = JPEG_ENC_ALLOC_OUTPUT_BUFFER,
    };
    for (int i = 0; i < CAM_JPEG_BUFS; i++) {
        s_out[i] = jpeg_alloc_encoder_mem(UVC_MAX_FRAME_BYTES, &mem, &s_out_cap[i]);
        ESP_RETURN_ON_FALSE(s_out[i], ESP_ERR_NO_MEM, TAG, "JPEG 输出缓冲 %d", i);
    }

    ESP_LOGI(TAG, "JPEG 编码器就绪：%dx%d 4:2:2 q=%d，双缓冲各 %u 字节(PSRAM)",
             UVC_W, UVC_H, CAM_JPEG_QUALITY, (unsigned)s_out_cap[0]);
    return ESP_OK;
}

esp_err_t cam_jpeg_encode(const uint16_t *src, int w, int h,
                          const uint8_t **out, size_t *len)
{
    ESP_RETURN_ON_FALSE(s_enc && src && out && len && w > 0 && h > 0,
                        ESP_ERR_INVALID_ARG, TAG, "参数");

    const int idx = cam_jpeg_spare_idx();

    const jpeg_encode_cfg_t cfg = {
        .width = (uint32_t)w,
        .height = (uint32_t)h,
        .src_type = JPEG_ENCODE_IN_FORMAT_RGB565,
        .sub_sample = CAM_JPEG_SUBSAMPLE,
        .image_quality = CAM_JPEG_QUALITY,
    };
    uint32_t produced = 0;
    const int64_t t0 = esp_timer_get_time();
    /*
     * 同步阻塞调用（内部 xSemaphoreTake + 等 2D-DMA 中断），所以必须在自己的任务
     * 里跑，**绝不能放进 USB 回调**。两侧的 cache 一致性都由驱动自己做，这里
     * 不需要补 esp_cache_msync（逐行核实过 IDF v6.0 的 esp_driver_jpeg）：
     *   - 输入 C2M 回写：jpeg_encode.c:250（带 UNALIGNED 标志，所以输入缓冲
     *     用普通 heap_caps_malloc(MALLOC_CAP_SPIRAM) 就行，无对齐要求）；
     *   - 输出 M2C 失效：jpeg_encode.c:281-284，按压缩后长度向上对齐到 cache line
     *     再 invalidate。**所以不会出现「头部正常、尾部是上一帧旧数据」那种现象。**
     */
    esp_err_t err = jpeg_encoder_process(s_enc, &cfg, (const uint8_t *)src,
                                         (uint32_t)w * (uint32_t)h * 2,
                                         s_out[idx], (uint32_t)s_out_cap[idx],
                                         &produced);
    s_last_us = (uint32_t)(esp_timer_get_time() - t0);

    if (err != ESP_OK || produced == 0 || produced > UVC_MAX_FRAME_BYTES) {
        /*
         * **可见的失败路径，不截断。** 超过 UVC_MAX_FRAME_BYTES 的帧 host 会按
         * 描述符声明值截断，半张 JPEG 在 host 侧表现为下半屏纯绿/纯灰，极难归因；
         * 丢掉这一帧只是画面卡一拍，而且 s_failed 计数会在自检行里说出真相。
         */
        s_failed++;
        return err != ESP_OK ? err : ESP_ERR_INVALID_SIZE;
    }

    s_encoded++;
    s_last_bytes = produced;
    s_total_bytes += produced;
    if (produced > s_peak_bytes)
        s_peak_bytes = produced;
    *out = s_out[idx];
    *len = produced;
    return ESP_OK;
}

void cam_jpeg_frame_committed(void)
{
    s_busy_idx = cam_jpeg_spare_idx();
}

void cam_jpeg_stats(uint32_t *encoded, uint32_t *failed, size_t *last_bytes,
                    size_t *avg_bytes, size_t *peak_bytes, uint32_t *last_us)
{
    if (encoded)    *encoded = s_encoded;
    if (failed)     *failed = s_failed;
    if (last_bytes) *last_bytes = s_last_bytes;
    if (avg_bytes)  *avg_bytes = s_encoded ? (size_t)(s_total_bytes / s_encoded) : 0;
    if (peak_bytes) *peak_bytes = s_peak_bytes;
    if (last_us)    *last_us = s_last_us;
}
