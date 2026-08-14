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
 * boot loop 好。
 *
 * ⚠️ 降级的粒度是**每条链路**，不是「音频」整体。播放(ES8388) 与录音(ES7210)
 * 是两颗独立芯片、USB 侧也是两条独立的 AudioStreaming 接口：
 *     ES7210 挂 ⇒ 播放照常工作，录音向 host 上报静音
 *     ES8388 挂 ⇒ 录音照常工作，播放把 host 送来的数据丢弃
 *     I2S 本身挂 ⇒ 才整体放弃（连时钟都没有，谈不上降级）
 * 因此 codec_audio_init() **只在 I2S 起不来时**返回错误；单颗 codec 的失败记进
 * 自检快照，不体现在返回值里。调用方**必须无条件调用 codec_audio_start()**，
 * 由它按「哪条链路可用」决定开不开功放、数据泵怎么跑。
 */
esp_err_t codec_audio_init(void);
esp_err_t codec_audio_start(void);

/*
 * 把「音频卡在哪一步」打成五行日志：三条链路各自的 init 返回值、I2S 全双工判定、
 * ES7210 的 i2c_master_probe 结果与卡住的那一句、ES8388/ES7210 的寄存器回读、
 * 功放状态、数据泵的帧数与信号峰值。
 *
 * ⚠️ **必须在日志通道可用之后调用**，而且要**反复调用**。
 * codec_audio_init() 跑在 tinyusb_driver_install() 之前，那时这块板唯一的
 * 日志出口（CONFIG_AIO_DEBUG_CDC 的 USB CDC 串口）还不存在；而 CDC 的 TX
 * 环形缓冲又会把 host 打开 ttyACM 之前的内容覆盖掉。所以 app_main 的主循环
 * 每 10 秒复读一次，用户什么时候接上 monitor 都能看到完整一份。
 *
 * codec_audio_init() 失败后照样可以调（没跑到的步骤打成「未运行」，与真实
 * 错误码严格区分 —— ESP_FAIL 与 ESP_CODEC_DEV_DRV_ERR 都是 −1，不能拿 −1 当哨兵）。
 * 每次调用会做几次 I2C 读，不要放进实时路径。
 */
void codec_audio_report(void);
