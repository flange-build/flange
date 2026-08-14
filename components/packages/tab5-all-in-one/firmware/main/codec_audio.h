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
 * 音频启动被**刻意切成两半**，因为这两半对 tinyusb_driver_install() 的位置
 * 要求正好相反。别把它们合回去。
 *
 *   codec_audio_init()   硬件 bring-up：I2S 全双工 + ES8388 + ES7210。
 *                        必须在 board_power_init()（要 I2C 总线与 IO 扩展）之后、
 *                        **tinyusb_driver_install() 之前**。
 *                        ⚠️ 之所以要在前：配 G26/G27 会让 IDF 的 gpio_ll_func_sel()
 *                        误关 USB-C 的焊盘（USB_WRAP.otg_conf.usb_pad_enable），
 *                        放在 USB 上电之前误伤才是无害的，随后 usb_new_phy() 会把
 *                        那一位置回去。完整机理见 main/tab5_pins.h 的音频段。
 *
 *   codec_audio_start()  功放上电 + 数据泵任务。
 *                        必须在 **tinyusb_driver_install() 之后**：
 *                        数据泵一起来就会调 tud_audio_*。
 *
 * 两者失败时调用方都只降级、不拦启动（同 kbd_start / touch_start）：USB 描述符
 * 是静态的，host 侧照样会枚举出声卡，只是收发到的都是静音 —— 这比让整机进
 * boot loop 好。codec_audio_init() 失败后 codec_audio_start() 仍可安全调用
 * （句柄为 NULL，数据泵走它的 NULL 分支）。
 */
esp_err_t codec_audio_init(void);
esp_err_t codec_audio_start(void);
