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

/* 开关喇叭功放（IO 扩展 0x43 的 PIN1）。与背光同构：board_power_init() 只把引脚
 * 配成推挽输出并**保持关闭**，真正打开归音频域（codec_audio.c）。
 *
 * 不变式：**功放导通 ⟺ ES8388 已配置完成且已解除静音**。提前导通会在开机时
 * 发出一声「啪」—— ES8388 在 esp_codec_dev_open() 之前 DAC 未上电、输出端电平
 * 未定。关流/关机时必须**先关它再关 codec**：esp_codec_dev_close() 不会碰这个
 * 引脚，顺序反了就是关机 pop。 */
void board_speaker_enable(bool on);
