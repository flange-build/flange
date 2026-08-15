#pragma once
#include "esp_err.h"

/* 初始化键盘 I2C 总线(G0/G1)、探测 0x6D、设为 Normal 模式，并启动读取任务。
 * 须在 TinyUSB 安装之后调用（上报依赖 tud_hid_ready()）。 */
esp_err_t kbd_start(void);
