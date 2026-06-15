#include "gud_device.h"
#include "gud_protocol.h"
#include "cardputer_pins.h" /* LCD_W / LCD_H */
#include "esp_log.h"
#include <string.h>

static const char *TAG = "gud";

/*
 * 固定显示参数：单 connector / 单模式 240x135 / RGB565。
 * LCD_W/LCD_H 来自 cardputer_pins.h，与显示模块共用，避免分叉。
 */
#define GUD_W LCD_W
#define GUD_H LCD_H

/* 单一支持的像素格式 */
static const uint8_t k_formats[] = {GUD_PIXEL_FORMAT_RGB565};

/*
 * 显示描述符。max_buffer_size=0 让 host 自行按 format×尺寸 计算（240x135xRGB565
 * ≈64KB，远小于驱动 64MB 上限）。单模式设备 min==max。flags=0：P0 不声明压缩、
 * 不声明 STATUS_ON_SET（probe 全是 GET，无需 SET 后状态轮询）。
 */
static const struct gud_display_descriptor_req k_descriptor = {
    .magic = GUD_DISPLAY_MAGIC,
    .version = 1,
    .flags = 0,
    .compression = 0,
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
 * 单显示模式 240x135。
 * 时序填合理值：留少量 porch（htotal/vtotal 必须 > 显示尺寸，否则被
 * drm_mode_validate_basic 剪除）。clock(kHz) 取 ~60Hz：
 *   htotal=280, vtotal=145 → 280*145=40600 px/frame; *60Hz/1000 ≈ 2436 kHz。
 * 标记 PREFERRED 让 userspace 自动选中此唯一模式。
 */
static const struct gud_display_mode_req k_mode = {
    .clock = 2436,
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
 * SET 请求 payload 的接收缓冲。当前仅接收并丢弃（让 host 认为成功），
 * 真正驱动显示在 Task 4。最大 payload = gud_state_req(SET_STATE_CHECK)。
 */
static uint8_t s_set_buf[64];

void gud_device_init(void)
{
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

/*
 * bulk OUT 数据回调（framebuffer）。Task 4 才搬运；此处丢弃，避免干扰 probe。
 * 仍需读出 FIFO 否则后续传输阻塞。
 */
void tud_vendor_rx_cb(uint8_t itf, uint8_t const *buffer, uint16_t bufsize)
{
    (void)buffer;
    tud_vendor_n_read_flush(itf);
    ESP_LOGD(TAG, "bulk OUT %u bytes discarded (Task4 will handle)", bufsize);
}
