#include "gud_device.h"
#include "gud_protocol.h"
#include "tab5_pins.h"   /* GUD_W / GUD_H */
#include "display_dsi.h" /* display_blit */
#include "esp_log.h"
#include "esp_heap_caps.h" /* heap_caps_malloc(MALLOC_CAP_SPIRAM)：帧缓冲放 PSRAM */
#include "lz4.h" /* LZ4_decompress_safe：解 GUD host 端 LZ4 压缩帧 */
#include <assert.h>
#include <string.h>

static const char *TAG = "gud";

/*
 * 固定显示参数：单 connector / 单模式 240x135 / RGB565。
 * LCD_W/LCD_H 来自 cardputer_pins.h，与显示模块共用，避免分叉。
 */
/* 单一支持的像素格式 */
static const uint8_t k_formats[] = {GUD_PIXEL_FORMAT_RGB565};

/*
 * 显示描述符。max_buffer_size=0 让 host 自行按 format×尺寸 计算（240x135xRGB565
 * ≈64KB，远小于驱动 64MB 上限）。单模式设备 min==max。flags=0：不声明
 * STATUS_ON_SET（probe 全是 GET，无需 SET 后状态轮询）。
 * compression=GUD_COMPRESSION_LZ4：声明支持 LZ4，host(CONFIG_LZ4_COMPRESS) 会对
 * 划算的帧压缩后再发，FS 12Mbps 下显著提升有效帧率(UI 内容收益大)。host 逐帧择优，
 * 不划算时仍发未压缩(compression=0)，故收帧两条路径都要处理。
 */
static const struct gud_display_descriptor_req k_descriptor = {
    .magic = GUD_DISPLAY_MAGIC,
    .version = 1,
    .flags = 0,
    .compression = GUD_COMPRESSION_LZ4,
    .max_buffer_size = 0,
    .min_width = GUD_W,
    .max_width = GUD_W,
    .min_height = GUD_H,
    .max_height = GUD_H,
};

/* 单 connector：PANEL 类型，无特殊 flags */
static const struct gud_connector_descriptor_req k_connector = {
    .connector_type = GUD_CONNECTOR_TYPE_PANEL,
    .flags = 0,
};

/*
 * 单显示模式 640x360（面板 720x1280 竖屏，由 PPA 放大 2× 并旋转 90° 铺满）。
 * 时序填合理值：htotal/vtotal 必须 > 显示尺寸，否则被 drm_mode_validate_basic 剪除。
 * clock(kHz) 取 ~60Hz：htotal=680, vtotal=370 → 680*370=251600 px/frame;
 * *60Hz/1000 ≈ 15096 kHz。标记 PREFERRED 让 userspace 自动选中此唯一模式。
 */
static const struct gud_display_mode_req k_mode = {
    .clock = 15096,
    .hdisplay = GUD_W,
    .hsync_start = GUD_W + 8,
    .hsync_end = GUD_W + 16,
    .htotal = GUD_W + 40,
    .vdisplay = GUD_H,
    .vsync_start = GUD_H + 2,
    .vsync_end = GUD_H + 4,
    .vtotal = GUD_H + 10,
    .flags = GUD_DISPLAY_MODE_FLAG_PREFERRED,
};

/* GET_STATUS 应答（仅当某个 GET 被 STALL 时 host 才会读；防御性提供 OK） */
static const uint8_t k_status_ok = GUD_STATUS_OK;
static const uint8_t k_connector_connected = GUD_CONNECTOR_STATUS_CONNECTED;

/*
 * SET 请求 payload 的接收缓冲。SET_BUFFER 的 payload(gud_set_buffer_req, 25 字节)
 * 在控制传输的 DATA 阶段收进此处，ACK 阶段解析。最大 payload =
 * gud_state_req(SET_STATE_CHECK)，仍 ≤ 64。
 */
static uint8_t s_set_buf[64];

/*
 * 帧缓冲：整屏 RGB565 = 640*360*2 ≈ 450KB，超出内部 SRAM 容量，放 PSRAM。
 * s_fb   : 解压后/未压缩的像素帧(最终 byteswap+blit 的目标)。
 * s_cbuf : 压缩帧的接收缓冲。host 仅在压缩更小时才发压缩帧，故 compressed_length
 *          < 该矩形未压缩大小 ≤ GUD_FB_CAP，按整屏容量足够。
 * 由 gud_device_init() 用 heap_caps_malloc(MALLOC_CAP_SPIRAM) 分配。
 */
#define GUD_FB_CAP (GUD_W * GUD_H * 2)
static uint8_t *s_fb;
static uint8_t *s_cbuf;

/*
 * "待收帧"状态机：
 *   s_frame_active=false → idle，bulk OUT 数据视为异常丢弃；
 *   SET_BUFFER 解析成功后 → active，记下 damage 矩形/未压缩长度/本次 bulk 传输长度，
 *   received=0；tud_vendor_rx_cb 按 received 偏移累积到目标缓冲，收满 xferlen 即
 *   (压缩则先解压)→byteswap→blit 并回 idle。
 */
/* control 回调(arm)与 rx_cb(consume)同处 TinyUSB 单任务上下文，无真正并发；
 * 仅 s_frame_active 作为 arm/disarm 门控声明 volatile 以防寄存器缓存，
 * 其余 s_frame_* 受 active 门控、无需 volatile。 */
static volatile bool s_frame_active = false;
static uint32_t s_frame_x, s_frame_y, s_frame_w, s_frame_h;
static uint32_t s_frame_length;   /* 未压缩像素字节数(=w*h*2)，即 blit 数据量 */
static uint32_t s_frame_xferlen;  /* 本次 bulk 应收字节数(压缩=compressed_length，否则=length) */
static uint32_t s_frame_received; /* 已累积字节数 */
static bool s_frame_compressed;   /* 本帧是否 LZ4 压缩 */

/* 解析刚收进 s_set_buf 的 SET_BUFFER 请求并武装一次收帧 */
static void gud_arm_set_buffer(void)
{
    struct gud_set_buffer_req req;
    /* s_set_buf 可能未对齐到 4 字节边界且结构体 packed，用 memcpy 安全取出 */
    memcpy(&req, s_set_buf, sizeof(req));

    /* 只支持未压缩与 LZ4(descriptor 已声明 LZ4)；其它压缩类型丢弃 */
    if (req.compression != 0 && req.compression != GUD_COMPRESSION_LZ4) {
        ESP_LOGW(TAG, "SET_BUFFER compression=0x%02x 不支持 丢弃",
                 req.compression);
        s_frame_active = false;
        return;
    }

    /* 矩形越界防御 */
    if (req.x + req.width > GUD_W || req.y + req.height > GUD_H ||
        req.width == 0 || req.height == 0) {
        ESP_LOGW(TAG, "SET_BUFFER 矩形越界 x=%u y=%u w=%u h=%u 丢弃",
                 (unsigned)req.x, (unsigned)req.y,
                 (unsigned)req.width, (unsigned)req.height);
        s_frame_active = false;
        return;
    }

    /* length 防御：必须 == w*h*2 且不超过缓冲容量(length 恒为未压缩大小) */
    uint32_t expect = req.width * req.height * 2;
    if (req.length != expect || req.length > GUD_FB_CAP) {
        ESP_LOGW(TAG, "SET_BUFFER length=%u 异常(期望 %u, 容量 %u) 丢弃",
                 (unsigned)req.length, (unsigned)expect, (unsigned)GUD_FB_CAP);
        s_frame_active = false;
        return;
    }

    /* 本次 bulk 应收字节数：压缩取 compressed_length，否则取 length。
     * compressed_length 防御：>0 且不超过缓冲容量(host 压缩更小时才用，理应 < length)。 */
    s_frame_compressed = (req.compression == GUD_COMPRESSION_LZ4);
    if (s_frame_compressed) {
        if (req.compressed_length == 0 || req.compressed_length > GUD_FB_CAP) {
            ESP_LOGW(TAG, "SET_BUFFER compressed_length=%u 异常(容量 %u) 丢弃",
                     (unsigned)req.compressed_length, (unsigned)GUD_FB_CAP);
            s_frame_active = false;
            return;
        }
        s_frame_xferlen = req.compressed_length;
    } else {
        s_frame_xferlen = req.length;
    }

    s_frame_x = req.x;
    s_frame_y = req.y;
    s_frame_w = req.width;
    s_frame_h = req.height;
    s_frame_length = req.length;
    s_frame_received = 0;
    s_frame_active = true;
    ESP_LOGD(TAG, "SET_BUFFER 武装: %ux%u @(%u,%u) length=%u xfer=%u %s",
             (unsigned)req.width, (unsigned)req.height,
             (unsigned)req.x, (unsigned)req.y, (unsigned)req.length,
             (unsigned)s_frame_xferlen, s_frame_compressed ? "LZ4" : "raw");
}

void gud_device_init(void)
{
    s_fb = heap_caps_malloc(GUD_FB_CAP, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    s_cbuf = heap_caps_malloc(GUD_FB_CAP, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    assert(s_fb && s_cbuf);

    ESP_LOGI(TAG, "GUD device init: %dx%d RGB565, single connector(PANEL), single mode",
             GUD_W, GUD_H);
    ESP_LOGI(TAG, "descriptor size=%u connector=%u mode=%u (packed check)",
             (unsigned)sizeof(struct gud_display_descriptor_req),
             (unsigned)sizeof(struct gud_connector_descriptor_req),
             (unsigned)sizeof(struct gud_display_mode_req));
}

/* 设备→host：在 SETUP 阶段提供数据；host 实际取 min(wLength, len) 字节 */
static bool reply_in(uint8_t rhport, tusb_control_request_t const *req,
                     const void *data, uint16_t len)
{
    /* 强转去 const：tinyusb 的 IN 传输不会写该缓冲 */
    return tud_control_xfer(rhport, req, (void *)data, len);
}

/* host→设备：在 SETUP 阶段挂接收缓冲；DATA 阶段返回 true 即 ACK */
static bool recv_out(uint8_t rhport, tusb_control_request_t const *req)
{
    uint16_t len = req->wLength;
    if (len > sizeof(s_set_buf))
        len = sizeof(s_set_buf); /* 截断为缓冲大小；host 会短收(short transfer)。
                                  * probe 阶段所有 SET payload ≤ 26 字节，此路径不会触发 */
    return tud_control_xfer(rhport, req, s_set_buf, len);
}

bool gud_handle_control(uint8_t rhport, uint8_t stage,
                        tusb_control_request_t const *req)
{
    /* 只在 SETUP 阶段记录与决策；DATA/ACK 阶段直接放行已挂起的传输 */
    if (stage == CONTROL_STAGE_SETUP) {
        const bool dev_to_host = (req->bmRequestType_bit.direction == TUSB_DIR_IN);
        ESP_LOGI(TAG, "ctrl bRequest=0x%02x wValue=0x%04x wIndex=0x%04x wLength=%u dir=%s",
                 req->bRequest, req->wValue, req->wIndex, req->wLength,
                 dev_to_host ? "IN(dev->host)" : "OUT(host->dev)");
    } else {
        /*
         * ACK 阶段：SET_BUFFER 的 payload 此时已收进 s_set_buf，解析并武装收帧。
         * 在 ACK(而非 DATA)解析，确保数据阶段已完整落入缓冲。随后 host 发 bulk OUT。
         */
        if (stage == CONTROL_STAGE_ACK && req->bRequest == GUD_REQ_SET_BUFFER &&
            req->wLength >= sizeof(struct gud_set_buffer_req)) {
            gud_arm_set_buffer();
        }
        /* DATA / ACK：放行（SETUP 已 tud_control_xfer 的传输由 stack 推进） */
        return true;
    }

    switch (req->bRequest) {

    /* ---- GET（设备→host）---- */
    case GUD_REQ_GET_STATUS:
        return reply_in(rhport, req, &k_status_ok, sizeof(k_status_ok));

    case GUD_REQ_GET_DESCRIPTOR:
        return reply_in(rhport, req, &k_descriptor, sizeof(k_descriptor));

    case GUD_REQ_GET_FORMATS:
        return reply_in(rhport, req, k_formats, sizeof(k_formats));

    case GUD_REQ_GET_PROPERTIES:
        /* 0 条全局属性：零长 IN 数据阶段 */
        return reply_in(rhport, req, NULL, 0);

    case GUD_REQ_GET_CONNECTORS:
        return reply_in(rhport, req, &k_connector, sizeof(k_connector));

    case GUD_REQ_GET_CONNECTOR_PROPERTIES:
        /* 0 条 connector 属性（wValue=connector index，单 connector 忽略） */
        return reply_in(rhport, req, NULL, 0);

    case GUD_REQ_GET_CONNECTOR_STATUS:
        return reply_in(rhport, req, &k_connector_connected,
                        sizeof(k_connector_connected));

    case GUD_REQ_GET_CONNECTOR_MODES:
        return reply_in(rhport, req, &k_mode, sizeof(k_mode));

    case GUD_REQ_GET_CONNECTOR_EDID:
        /* 无 EDID：返回零长，host 回落到 GET_CONNECTOR_MODES */
        return reply_in(rhport, req, NULL, 0);

    /* ---- SET（host→设备）：接收并 ACK，本任务不真正驱动 ---- */
    case GUD_REQ_SET_CONNECTOR_FORCE_DETECT:
    case GUD_REQ_SET_BUFFER:
    case GUD_REQ_SET_STATE_CHECK:
    case GUD_REQ_SET_STATE_COMMIT:
    case GUD_REQ_SET_CONTROLLER_ENABLE:
    case GUD_REQ_SET_DISPLAY_ENABLE:
        if (req->wLength == 0) {
            /* 无 payload 的 SET：直接 ACK 状态阶段 */
            return tud_control_status(rhport, req);
        }
        return recv_out(rhport, req);

    default:
        ESP_LOGW(TAG, "UNHANDLED bRequest=0x%02x -> STALL (照真机日志补齐)",
                 req->bRequest);
        return false;
    }
}

/*
 * tinyusb 弱回调：vendor 类 EP0 控制请求入口。
 * esp_tinyusb 不实现此符号，此处定义即被链接采用（Task 2 已确认）。
 * 仅转发 vendor 类型请求给 GUD 状态机；其它类型让 stack 处理 / STALL。
 */
bool tud_vendor_control_xfer_cb(uint8_t rhport, uint8_t stage,
                                tusb_control_request_t const *request)
{
    if (request->bmRequestType_bit.type != TUSB_REQ_TYPE_VENDOR)
        return false;
    return gud_handle_control(rhport, stage, request);
}

/* 消费一段 vendor bulk OUT 数据，FIFO/direct 两种 TinyUSB 模式共用。 */
static void gud_consume_rx_chunk(uint8_t const *buffer, uint32_t bufsize)
{
    if (!s_frame_active) {
        ESP_LOGW(TAG, "bulk OUT %u bytes 无待收帧 丢弃", bufsize);
        return;
    }

    /* 压缩帧累积到 s_cbuf，未压缩直接累积到 s_fb */
    uint8_t *dst = s_frame_compressed ? s_cbuf : s_fb;
    uint32_t remain = s_frame_xferlen - s_frame_received;
    uint32_t n = bufsize;
    if (n > remain) {
        ESP_LOGW(TAG, "bulk OUT 超出 remain=%u 截断", (unsigned)remain);
        n = remain; /* 防御：理论不应超，超出部分截断不写垃圾 */
    }

    memcpy(dst + s_frame_received, buffer, n);
    s_frame_received += n;

    if (s_frame_received >= s_frame_xferlen) {
        /* 压缩帧：先 LZ4 解压到 s_fb，得到 s_frame_length 字节未压缩 RGB565。
         * 用 _safe 变体带边界检查；解压长度必须恰为期望未压缩大小，否则丢帧。 */
        if (s_frame_compressed) {
            int dlen = LZ4_decompress_safe((const char *)s_cbuf, (char *)s_fb,
                                           (int)s_frame_xferlen, (int)GUD_FB_CAP);
            if (dlen < 0 || (uint32_t)dlen != s_frame_length) {
                ESP_LOGW(TAG, "LZ4 解压失败 ret=%d 期望=%u 丢帧",
                         dlen, (unsigned)s_frame_length);
                s_frame_active = false;
                s_frame_received = 0;
                return;
            }
        }

        /* 无需 byteswap：DSI/DPI 链路按小端 RGB565 直接取用（BSP_LCD_BIGENDIAN=0），
         * 与 Cardputer 的 ST7789 4-line SPI 不同。 */
        display_blit((int)s_frame_x, (int)s_frame_y,
                     (int)s_frame_w, (int)s_frame_h, s_fb);
        ESP_LOGD(TAG, "帧收满 xfer=%u(%s) blit %ux%u @(%u,%u)",
                 (unsigned)s_frame_xferlen, s_frame_compressed ? "LZ4" : "raw",
                 (unsigned)s_frame_w, (unsigned)s_frame_h,
                 (unsigned)s_frame_x, (unsigned)s_frame_y);
        s_frame_active = false;
        s_frame_received = 0;
    }
}

/*
 * bulk OUT 数据回调（framebuffer 像素）。
 * SET_BUFFER 武装后，host 经 bulk OUT 发 s_frame_xferlen 字节(压缩=LZ4 数据，
 * 否则=未压缩 RGB565)。FS EP 一次通常只收 ≤64 字节，要跨多次回调累积；
 * 收满后(压缩则先解压)→byteswap→blit 并回 idle。
 *
 * TinyUSB Vendor 有两种 RX 语义：
 *   - FIFO 模式：回调的 buffer=NULL / bufsize=0，必须用 tud_vendor_n_read()
 *     从 FIFO 取数据；
 *   - direct 模式：回调参数就是当前收到的数据。
 * 项目默认 CONFIG_TINYUSB_VENDOR_RX_BUFSIZE=64，实际走 FIFO 模式。
 */
#if CFG_TUD_API_V0_19_COMPAT
void tud_vendor_rx_cb(uint8_t itf, uint8_t const *buffer, uint16_t bufsize)
#else
void tud_vendor_rx_cb(uint8_t itf, uint8_t const *buffer, uint32_t bufsize)
#endif
{
#if CFG_TUD_VENDOR_TXRX_BUFFERED
    uint8_t fifo_buf[CFG_TUD_VENDOR_RX_BUFSIZE];

    /* FIFO 容量可大于单个 USB packet，一次回调内尽量排空。 */
    while (tud_vendor_n_available(itf) > 0) {
        uint32_t available = tud_vendor_n_available(itf);
        uint32_t want = available;
        if (want > sizeof(fifo_buf))
            want = sizeof(fifo_buf);

        uint32_t got = tud_vendor_n_read(itf, fifo_buf, want);
        if (got == 0)
            break;
        gud_consume_rx_chunk(fifo_buf, got);
    }
#else
    gud_consume_rx_chunk(buffer, bufsize);
#endif
}
