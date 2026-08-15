#pragma once
/*
 * GT911 电容触摸（内部 I2C 0x14）读取。本阶段只把坐标打到日志上，
 * 不涉及 USB —— HID digitizer 上报是后续任务的事。
 */
#include "esp_err.h"

/* 初始化 GT911 并起轮询任务。须在 board_power_init() 之后调用
 * （触摸电源使能在 IO 扩展上，由它拉高）。 */
esp_err_t touch_start(void);
