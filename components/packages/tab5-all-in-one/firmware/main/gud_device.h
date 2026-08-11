#pragma once
#include <stdbool.h>
#include <stdint.h>
#include "esp_err.h"
#include "tusb.h"

/*
 * GUD 控制协议状态机（P0 最小子集）。
 *
 * 单 connector / 单模式 640x360 / 单像素格式 RGB565，全部硬编码。
 * 实现让 mainline gud 驱动 probe 成功所需的 GET/SET 请求，
 * 以及 framebuffer 帧搬运（bulk OUT + SET_BUFFER，见 .c 的 tud_vendor_rx_cb）。
 */

/* 初始化：分配 PSRAM 帧缓冲并打印 banner。失败返回 ESP_ERR_NO_MEM。 */
esp_err_t gud_device_init(void);

/*
 * 处理一个 vendor 类 EP0 控制请求，分阶段调用。
 * 返回 true 表示已处理（含已 tud_control_xfer / tud_control_status）；
 * 返回 false 表示不认识该请求，由调用方 STALL。
 */
bool gud_handle_control(uint8_t rhport, uint8_t stage,
                        tusb_control_request_t const *req);
