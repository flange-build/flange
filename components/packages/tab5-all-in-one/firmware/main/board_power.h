#pragma once
#include "esp_err.h"
#include "driver/i2c_master.h"
#include <stdbool.h>

/* 初始化内部 I2C 总线(G31/G32) 与 PI4IOE5V6408-1，并给面板/触摸上电。
 * 背光 GPIO 在此配好但保持熄灭，点亮时机归显示域（见 board_backlight）。 */
esp_err_t board_power_init(void);

/* 内部 I2C 总线句柄，供触摸/codec 等后续阶段复用。 */
i2c_master_bus_handle_t board_i2c_bus(void);

/* 开关背光(G22)。不变式：背光亮 ⟺ 面板正在输出有效视频，
 * 因此由 display_init() 在面板就绪后调用，不由 app_main 编排。 */
void board_backlight(bool on);
