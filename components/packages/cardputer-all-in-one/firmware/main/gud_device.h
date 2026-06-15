#pragma once
#include <stdbool.h>
#include <stdint.h>
#include "tusb.h"

/*
 * GUD 控制协议状态机（P0 最小子集）。
 *
 * 单 connector / 单模式 240x135 / 单像素格式 RGB565，全部硬编码。
 * 仅实现让 mainline gud 驱动 probe 成功所需的 GET/SET 请求；
 * framebuffer 帧搬运（bulk OUT + SET_BUFFER）是 Task 4，不在此处。
 */

/* 初始化（当前仅打印 banner，状态全为静态常量，预留挂点） */
void gud_device_init(void);

/*
 * 处理一个 vendor 类 EP0 控制请求，分阶段调用。
 * 返回 true 表示已处理（含已 tud_control_xfer / tud_control_status）；
 * 返回 false 表示不认识该请求，由调用方 STALL。
 */
bool gud_handle_control(uint8_t rhport, uint8_t stage,
                        tusb_control_request_t const *req);
