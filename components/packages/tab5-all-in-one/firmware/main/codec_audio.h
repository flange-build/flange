#pragma once
/*
 * M5Stack Tab5 音频：ES8388(I2C 0x10) 播放 + ES7210(I2C 0x40) 双麦录音，
 * 经**一个** I2S 端口全双工，向 host 呈现为 UAC1 声卡（16 kHz / 单声道 / S16_LE）。
 *
 * 两颗芯片与 IO 扩展/触摸同挂内部 I2C(G31/G32)，故复用 board_i2c_bus() 的总线
 * 句柄、不新建 master —— 与 touch_hid.c 同一处置。
 */
#include "esp_err.h"

/*
 * 初始化 I2S 全双工 + 两颗 codec，打开功放，并起数据泵任务。
 * 须在 board_power_init()（要 I2C 总线与 IO 扩展）与 tinyusb_driver_install()
 * （数据泵会调 tud_audio_*）之后调用。
 *
 * 失败时调用方只降级、不拦启动（同 kbd_start / touch_start）：USB 描述符是静态的，
 * host 侧照样会枚举出声卡，只是收发到的都是静音 —— 这比让整机进 boot loop 好。
 */
esp_err_t codec_audio_start(void);
