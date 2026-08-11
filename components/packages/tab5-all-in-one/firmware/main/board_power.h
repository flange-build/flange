#pragma once
#include "esp_err.h"
#include "driver/i2c_master.h"

/* 初始化内部 I2C 总线(G31/G32) 与 PI4IOE5V6408-1，并给面板/触摸上电。 */
esp_err_t board_power_init(void);

/* 内部 I2C 总线句柄，供触摸/codec 等后续阶段复用。 */
i2c_master_bus_handle_t board_i2c_bus(void);
