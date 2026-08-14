#include "codec_audio.h"

#include <inttypes.h>
#include <stdbool.h>
#include <stdint.h>
#include <string.h>

#include "driver/i2s_std.h"
#include "esp_check.h"
#include "esp_codec_dev.h"
#include "esp_codec_dev_defaults.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "soc/i2s_struct.h"
#include "tusb.h"

#include "audio_frame.h"
#include "board_power.h"
#include "tab5_pins.h"
#include "usb_descriptors.h"

static const char *TAG = "codec_audio";

#define AUDIO_I2S_PORT       I2S_NUM_0
/* DMA 每个描述符正好装一个 USB 帧(1 ms)的样本，让 I2S 读写与 USB 帧天然同拍：
 * 数据泵拿 i2s_channel_read() 当节拍源，读满即返回，比 vTaskDelay(1) 更贴。 */
#define AUDIO_DMA_FRAME_NUM  UAC_FRAME_SAMPLES
#define AUDIO_DMA_DESC_NUM   4

#define AUDIO_TASK_STACK_SIZE 4096
/*
 * **必须低于** TinyUSB 的任务优先级（esp_tinyusb 的 TINYUSB_DEFAULT_TASK_PRIO = 5）。
 *
 * 此前取 5（同优先级），理由是「本任务绝大部分时间阻塞在 i2s_channel_read() 上」——
 * 这个前提在 I2S 通道**未进入 RUNNING** 时不成立：那时 i2s_channel_read() 会立即
 * 返回错误而不是阻塞满超时，循环随即退化成不让出 CPU 的忙转，独占一个核。
 * USB 是这块板的命脉（显示/键盘/触摸/音频全走它），任何情况下都不该被音频抢；
 * 排在它下面，最坏情况也只是音频卡顿，而不是整个设备枚举不出来。
 */
#define AUDIO_TASK_PRIORITY   4

/* 欠载/溢出汇总日志的间隔。⚠️ 绝不在每帧路径里打日志 ——
 * 1 kHz 的 ESP_LOGW 会自己把音频饿死，属于观测干扰被观测。 */
#define AUDIO_STAT_PERIOD_FRAMES 10000   /* 10 秒 */

static i2s_chan_handle_t s_tx;
static i2s_chan_handle_t s_rx;
static esp_codec_dev_handle_t s_spk_dev;
static esp_codec_dev_handle_t s_mic_dev;

/*
 * host 有没有把两条 AudioStreaming 接口切到 alt 1。
 *
 * 全双工下两个方向**各自独立**，不存在「谁接管谁」—— Cardputer 上那套
 * AUDIO_MODE_SPEAKER/MICROPHONE 三态仲裁是因为它的扬声器 WS 与麦克风 PDM CLK
 * 共用同一个 GPIO，Tab5 的 DOUT/DSIN 是两根脚，整段逻辑不移植。
 *
 * 写在 USB 中断/控制回调上下文，读在数据泵任务里，故用 volatile；两个 bool
 * 之间没有需要保持一致的不变式，不需要临界区。
 */
static volatile bool s_spk_on;
static volatile bool s_mic_on;

/*
 * 显式判定 I2S 是否真的组成了全双工，**不依赖 IDF 那条看不见的 DEBUG 日志**。
 *
 * i2s_std.c 的 i2s_std_set_slot() 在 controller->full_duplex 成立时调
 * i2s_ll_share_bck_ws()，在 P4 上写的就是 I2S0.tx_conf.sig_loopback（bit 30）——
 * 它是硬件层面「TX 与 RX 共用 BCLK/WS」的开关。两个通道都 init 完之后这一位
 * 必须是 1。
 *
 * 为 0 意味着驱动判定两边配置不同、退回了 simplex —— 而 P4(HW_VERSION_2) 遇到
 * 这种情况**只打一条 DEBUG 级日志就放行**，所有函数照样返回 ESP_OK，然后两个
 * 方向各自去驱动 BCLK/WS，症状是噪声或全静音。这是本模块最容易静默踩掉的坑，
 * 所以在这里把它变成一条真正的失败。
 */
_Static_assert(AUDIO_I2S_PORT == I2S_NUM_0, "i2s_duplex_active() 读的是 I2S0 的寄存器");

static bool i2s_duplex_active(void)
{
    return I2S0.tx_conf.sig_loopback != 0;
}

/*
 * I2S 实际要配的引脚。⚠️ 排障旋钮 CONFIG_AIO_AUDIO_I2S_GPIO（见 Kconfig.projbuild）：
 * 把「I2S 外设/GDMA/时钟 bring-up」与「I2S 抢 GPIO」拆开验证用。
 * DOUT(G26)/BCLK(G27) 与 USB 内部全速 PHY 的 D−/D+ 是同一对焊盘，见 tab5_pins.h。
 * 根因坐实后应当把这段 #if 连同 Kconfig 里的 choice 一起删掉。
 */
#if CONFIG_AIO_AUDIO_I2S_GPIO_NONE
#  define I2S_GPIO_MCLK  I2S_GPIO_UNUSED
#  define I2S_GPIO_BCLK  I2S_GPIO_UNUSED
#  define I2S_GPIO_WS    I2S_GPIO_UNUSED
#  define I2S_GPIO_DOUT  I2S_GPIO_UNUSED
#  define I2S_GPIO_DSIN  I2S_GPIO_UNUSED
#elif CONFIG_AIO_AUDIO_I2S_GPIO_NO_USB_PADS
#  define I2S_GPIO_MCLK  PIN_I2S_MCLK
#  define I2S_GPIO_BCLK  I2S_GPIO_UNUSED   /* G27 = USB 全速 PHY 的 D+ */
#  define I2S_GPIO_WS    PIN_I2S_LRCK
#  define I2S_GPIO_DOUT  I2S_GPIO_UNUSED   /* G26 = USB 全速 PHY 的 D− */
#  define I2S_GPIO_DSIN  PIN_I2S_DSIN
#else /* CONFIG_AIO_AUDIO_I2S_GPIO_ALL：正常行为 */
#  define I2S_GPIO_MCLK  PIN_I2S_MCLK
#  define I2S_GPIO_BCLK  PIN_I2S_SCLK
#  define I2S_GPIO_WS    PIN_I2S_LRCK
#  define I2S_GPIO_DOUT  PIN_I2S_DOUT
#  define I2S_GPIO_DSIN  PIN_I2S_DSIN
#endif

static esp_err_t i2s_full_duplex_init(void)
{
    i2s_chan_config_t chan_cfg = I2S_CHANNEL_DEFAULT_CONFIG(AUDIO_I2S_PORT, I2S_ROLE_MASTER);
    chan_cfg.dma_desc_num  = AUDIO_DMA_DESC_NUM;
    chan_cfg.dma_frame_num = AUDIO_DMA_FRAME_NUM;
    chan_cfg.auto_clear    = true;   /* 欠载时自动填 0，而不是重放上一帧（那是「嗡」声的来源） */

    /*
     * ⚠️ TX 与 RX 必须在**这一次调用**里同时要到，不能先起 TX 再追加 RX ——
     * ESP32-P4 的 I2S v2 上分两次建通道会失败（esphome#16043）。
     */
    ESP_RETURN_ON_ERROR(i2s_new_channel(&chan_cfg, &s_tx, &s_rx), TAG, "i2s chan");

    /*
     * ⚠️ TX 与 RX 必须传**同一份** config：i2s_std.c 的
     * s_i2s_channel_try_to_constitude_std_duplex() 对两边的 i2s_std_config_t 做
     * memcmp，相等才组成全双工（共享 BCLK/WS），不相等就退回 simplex 且不报错
     * （见 i2s_duplex_active() 上的注释）。所以 dout 与 din **两个都填**，
     * 且两次调用传的是**同一个对象的地址**，而不是两份长得一样的结构体 ——
     * 「结构上不可能填错」比「记得填一样」可靠。
     */
    const i2s_std_config_t std_cfg = {
        .clk_cfg  = {
            .sample_rate_hz = UAC_SAMPLE_RATE,
            .clk_src        = I2S_CLK_SRC_DEFAULT,
            /* 显式写 256×fs：ES8388 与 ES7210 的内部分频器都按这个假设工作，
             * 且下面 esp_codec_dev 重配时钟时用的也是这个默认值，必须一致。 */
            .mclk_multiple  = I2S_MCLK_MULTIPLE_256,
        },
        /* 线上固定走**立体声 2 slot**：ES8388 是立体声 DAC、ES7210 是双麦，
         * 且全双工要求两个方向 slot 配置一致。USB 侧的单声道由 audio_frame.c
         * 转换，不靠 I2S 的 MONO 模式 —— MONO 会把 slot_mask 设成只剩左声道，
         * 录音就只拿得到 MIC1，MIC2 白装。 */
        .slot_cfg = I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(I2S_DATA_BIT_WIDTH_16BIT,
                                                        I2S_SLOT_MODE_STEREO),
        .gpio_cfg = {
            .mclk = I2S_GPIO_MCLK,
            .bclk = I2S_GPIO_BCLK,
            .ws   = I2S_GPIO_WS,
            .dout = I2S_GPIO_DOUT,
            .din  = I2S_GPIO_DSIN,
            .invert_flags = { .mclk_inv = false, .bclk_inv = false, .ws_inv = false },
        },
    };

    ESP_RETURN_ON_ERROR(i2s_channel_init_std_mode(s_tx, &std_cfg), TAG, "i2s tx");
    ESP_RETURN_ON_ERROR(i2s_channel_init_std_mode(s_rx, &std_cfg), TAG, "i2s rx");

    const bool duplex = i2s_duplex_active();
    ESP_LOGI(TAG, "I2S %d Hz / 16 bit / 2 slot, duplex=%d", UAC_SAMPLE_RATE, duplex);
    ESP_RETURN_ON_FALSE(duplex, ESP_ERR_INVALID_STATE, TAG,
                        "I2S 未组成全双工：两次 init 传的不是同一份 std_cfg");
    return ESP_OK;
}

/* 两颗 codec 共用的线上格式：立体声 2 slot / 16 bit / 同采样率。
 * 与上面 std_cfg 声明的必须一致 —— esp_codec_dev 打开时会拿它去 reconfig
 * I2S 的 slot 与 clock，值对不上就等于把刚配好的全双工参数改掉了。 */
static esp_codec_dev_sample_info_t wire_format(void)
{
    esp_codec_dev_sample_info_t fs = {
        .bits_per_sample = 16,
        .channel         = 2,
        /* channel_mask 留 0 = 不过滤，两个 slot 都要（左 = MIC1，右 = MIC2）。 */
        .sample_rate     = UAC_SAMPLE_RATE,
    };
    return fs;
}

static esp_err_t es8388_init(void)
{
    audio_codec_i2c_cfg_t i2c_cfg = {
        .port       = I2C_NUM_0,
        .addr       = ES8388_I2C_ADDR8,      /* ⚠️ 8 bit 形式(0x20)，驱动内部会 >>1 */
        .bus_handle = board_i2c_bus(),       /* 复用内部总线，绝不新建 master */
    };
    const audio_codec_ctrl_if_t *ctrl = audio_codec_new_i2c_ctrl(&i2c_cfg);
    ESP_RETURN_ON_FALSE(ctrl, ESP_FAIL, TAG, "es8388 i2c ctrl");

    audio_codec_i2s_cfg_t i2s_cfg = {
        .port = AUDIO_I2S_PORT, .tx_handle = s_tx, .rx_handle = NULL,
    };
    const audio_codec_data_if_t *data = audio_codec_new_i2s_data(&i2s_cfg);
    ESP_RETURN_ON_FALSE(data, ESP_FAIL, TAG, "es8388 i2s data");

    es8388_codec_cfg_t cfg = {
        .ctrl_if     = ctrl,
        .codec_mode  = ESP_CODEC_DEV_WORK_MODE_DAC,  /* 只做播放，ADC 归 ES7210 */
        .master_mode = false,                        /* ESP 是 I2S master，codec 是 slave */
        /* ⚠️ −1 让驱动内建的 PA 控制变成空操作。Tab5 的功放没有独立 GPIO
         * （esp-bsp 的 BSP_POWER_AMP_IO = GPIO_NUM_NC），使能在 IO 扩展 0x43 的
         * PIN1 上，由 board_speaker_enable() 管，时序见 codec_audio_start()。 */
        .pa_pin      = -1,
    };
    const audio_codec_if_t *codec = es8388_codec_new(&cfg);
    ESP_RETURN_ON_FALSE(codec, ESP_FAIL, TAG, "es8388 new");

    esp_codec_dev_cfg_t dev_cfg = {
        .dev_type = ESP_CODEC_DEV_TYPE_OUT, .codec_if = codec, .data_if = data,
    };
    s_spk_dev = esp_codec_dev_new(&dev_cfg);
    ESP_RETURN_ON_FALSE(s_spk_dev, ESP_FAIL, TAG, "es8388 dev");

    /* ⓘ esp_codec_dev_open() 内部会经 data_if 去 i2s_channel_enable(s_tx)，
     * 所以**不要**再自己 enable 一次（会返回 ESP_ERR_INVALID_STATE）。 */
    esp_codec_dev_sample_info_t fs = wire_format();
    ESP_RETURN_ON_FALSE(esp_codec_dev_open(s_spk_dev, &fs) == ESP_CODEC_DEV_OK,
                        ESP_FAIL, TAG, "es8388 open");

    /* 开机音量取 70%：满量程直推板载小喇叭在中低频容易破音，而破音很容易被误判
     * 成时钟配错。host 侧还会再叠一层软件音量（本阶段不声明 Feature Unit）。 */
    esp_codec_dev_set_out_vol(s_spk_dev, 70);
    return ESP_OK;
}

static esp_err_t es7210_init(void)
{
    audio_codec_i2c_cfg_t i2c_cfg = {
        .port       = I2C_NUM_0,
        .addr       = ES7210_I2C_ADDR8,      /* ⚠️ 8 bit 形式(0x80)，驱动内部会 >>1 */
        .bus_handle = board_i2c_bus(),
    };
    const audio_codec_ctrl_if_t *ctrl = audio_codec_new_i2c_ctrl(&i2c_cfg);
    ESP_RETURN_ON_FALSE(ctrl, ESP_FAIL, TAG, "es7210 i2c ctrl");

    audio_codec_i2s_cfg_t i2s_cfg = {
        .port = AUDIO_I2S_PORT, .tx_handle = NULL, .rx_handle = s_rx,
    };
    const audio_codec_data_if_t *data = audio_codec_new_i2s_data(&i2s_cfg);
    ESP_RETURN_ON_FALSE(data, ESP_FAIL, TAG, "es7210 i2s data");

    es7210_codec_cfg_t cfg = {
        .ctrl_if      = ctrl,
        .master_mode  = false,                               /* ESP 是 I2S master */
        .mic_selected = ES7210_SEL_MIC1 | ES7210_SEL_MIC2,   /* Tab5 是双麦 */
        .mclk_src     = ES7210_MCLK_FROM_PAD,                /* MCLK 由 ESP 的 G30 提供 */
        .mclk_div     = I2S_MCLK_MULTIPLE_256,               /* 与 std_cfg 的 mclk_multiple 一致 */
    };
    /*
     * ⚠️ 必须走 STD 立体声 2 slot，**不能改用 TDM**：驱动本身也是「≥3 只麦才开
     * TDM」，2 只麦时 REG12 写 0x00、MIC1 走左 slot、MIC2 走右 slot。而且混不得 ——
     * 全双工要求 TX 与 RX 的 mode_info 相等，一个 STD 一个 TDM 直接组不成全双工。
     */
    const audio_codec_if_t *codec = es7210_codec_new(&cfg);
    ESP_RETURN_ON_FALSE(codec, ESP_FAIL, TAG, "es7210 new");

    esp_codec_dev_cfg_t dev_cfg = {
        .dev_type = ESP_CODEC_DEV_TYPE_IN, .codec_if = codec, .data_if = data,
    };
    s_mic_dev = esp_codec_dev_new(&dev_cfg);
    ESP_RETURN_ON_FALSE(s_mic_dev, ESP_FAIL, TAG, "es7210 dev");

    esp_codec_dev_sample_info_t fs = wire_format();
    ESP_RETURN_ON_FALSE(esp_codec_dev_open(s_mic_dev, &fs) == ESP_CODEC_DEV_OK,
                        ESP_FAIL, TAG, "es7210 open");

    /* 30 dB 是 IDF 官方 es7210 例子的取值，对驻极体麦是个「能听清说话又不啸叫」
     * 的起点。真要调，先在 host 侧用 `sox -n stat` 看 RMS 再动。 */
    esp_codec_dev_set_in_gain(s_mic_dev, 30.0f);
    return ESP_OK;
}

/*
 * 数据泵：每 1 ms 一转，同时搬两个方向。
 *
 * 以 i2s_channel_read() 作节拍源：DMA 描述符正好是 1 ms 的样本数，读满即返回，
 * 阻塞到下一个 1 ms —— 比 vTaskDelay(1) 更贴合 USB 帧，也省掉一个定时器。
 */
static void audio_pump_task(void *arg)
{
    int16_t rx_stereo[UAC_FRAME_SAMPLES * 2];
    int16_t tx_stereo[UAC_FRAME_SAMPLES * 2];
    int16_t usb_mono[UAC_FRAME_SAMPLES];
    uint32_t tx_underrun = 0, mic_overrun = 0, rx_fail = 0, frames = 0;
    /* 上一转录音是否在流。用来把「清空软件 FIFO」做成**边沿触发**，见下方。 */
    bool mic_streaming = false;

    (void)arg;

    while (1) {
        size_t got = 0;
        if (s_rx == NULL) {
            /*
             * CONFIG_AIO_AUDIO_FULL_STAGE == 0（反向验证档）：codec/I2S 一个字
             * 都没初始化，句柄是 NULL。此时改用 1 ms 定时当节拍源，让本任务只
             * 剩下 USB 侧的调用 —— 这一档专门用来验「数据泵对 tud_audio_* 的
             * 调用本身是否有罪」。正常构建（STAGE 5）永远走不到这里。
             */
            vTaskDelay(pdMS_TO_TICKS(1));
            memset(rx_stereo, 0, sizeof(rx_stereo));
        } else if (i2s_channel_read(s_rx, rx_stereo, sizeof(rx_stereo), &got,
                                    pdMS_TO_TICKS(50)) != ESP_OK ||
                   got != sizeof(rx_stereo)) {
            rx_fail++;
            /*
             * ⚠️ 这里的延时不可省。上面那个 50 ms 超时**只在通道已 RUNNING 时**
             * 才会真的阻塞；通道没使能时 i2s_channel_read() 立即返回错误，
             * 于是 continue 会把本循环变成不让出 CPU 的忙转、独占一个核，
             * 把同核上的低优先级任务连同 idle 任务一起饿死。
             * 也就是说「音频没起来」会升级成「整块板子不正常」。
             */
            vTaskDelay(pdMS_TO_TICKS(10));
            continue;
        }

        /* ── 录音：I2S RX → USB IN ──
         * tud_audio_write() 只写进软件 FIFO，真正的分包由 TinyUSB 按
         * CFG_TUD_AUDIO_EP_IN_FLOW_CONTROL 决定（标称 16 样本 ±1）——
         * 这正是「异步 IN 不需要反馈端点」的实现基础。 */
        if (s_mic_on && tud_mounted()) {
            audio_frame_stereo_to_mono(rx_stereo, usb_mono, UAC_FRAME_SAMPLES);
            if (tud_audio_write(usb_mono, UAC_FRAME_BYTES) != UAC_FRAME_BYTES)
                mic_overrun++;
            mic_streaming = true;
        } else if (mic_streaming) {
            /*
             * host 关掉录音时清空软件 FIFO，否则下次打开会先放出一段陈旧音频。
             * **只在关闭的那一刻清一次**，不是每毫秒清一次：没在流的时候 FIFO
             * 本来就没人往里写，重复清纯属空转，而且会让「host 还没枚举完」这段
             * 窗口里本任务无谓地每毫秒碰一次 TinyUSB 的内部结构。
             * 参照实现 cardputer-all-in-one 也是只在方向切换的边沿上清。
             */
            tud_audio_clear_ep_in_ff();
            mic_streaming = false;
        }

        /* ── 播放：USB OUT → I2S TX ──
         * host 没选 alt 1 时灌静音而不是停写：I2S 时钟保持连续，ES8388 不会
         * 因为 BCLK 断续而「咔」一声。代价是一直有 DMA 活动，每毫秒 64 字节。 */
        uint16_t read = 0;
        if (s_spk_on && tud_mounted())
            read = tud_audio_read(usb_mono, UAC_FRAME_BYTES);
        if (read < UAC_FRAME_BYTES)
            memset((uint8_t *)usb_mono + read, 0, UAC_FRAME_BYTES - read);
        audio_frame_mono_to_stereo(usb_mono, tx_stereo, UAC_FRAME_SAMPLES);

        size_t written = 0;
        if (s_tx != NULL &&                          /* NULL 只可能出现在 STAGE 0，见上 */
            (i2s_channel_write(s_tx, tx_stereo, sizeof(tx_stereo), &written,
                               pdMS_TO_TICKS(20)) != ESP_OK || written != sizeof(tx_stereo)))
            tx_underrun++;

        /* 只计数，每 10 秒汇总一条 —— 见 AUDIO_STAT_PERIOD_FRAMES 上的注释。 */
        if (++frames >= AUDIO_STAT_PERIOD_FRAMES) {
            if (tx_underrun || mic_overrun || rx_fail)
                ESP_LOGW(TAG, "10s 统计：TX 欠载 %" PRIu32 "，麦克风 FIFO 溢出 %" PRIu32
                              "，RX 读失败 %" PRIu32, tx_underrun, mic_overrun, rx_fail);
            tx_underrun = mic_overrun = rx_fail = frames = 0;
        }
    }
}

/*
 * ⚠️ 下面那个 stage 是**排障旋钮**（CONFIG_AIO_AUDIO_FULL_STAGE，默认 5 = 完整行为）。
 *
 * 根因已坐实（见下面 codec_audio_init() 上方那段与 main/tab5_pins.h），
 * stage 只剩回归排查的价值。各级含义见 main/Kconfig.projbuild 的表。
 * **修法实机确认后应当把 stage 连同那段 Kconfig 一起删掉**，别留成永久配置项。
 */

/*
 * ⚠️⚠️⚠️ **本函数必须在 tinyusb_driver_install() 之前调用。** 这是这块板最贵的
 *        那个坑的修法之一，改顺序等于把 bug 放回去。
 *
 * i2s_channel_init_std_mode() → i2s_gpio_check_and_set() → gpio_func_sel(26/27) →
 * IDF 的 gpio_ll_func_sel()（esp_hal_gpio/esp32p4/include/hal/gpio_ll.h:676-686）
 * 见到 G26/G27 就会写一次
 *         USB_WRAP.otg_conf.usb_pad_enable = 0;
 * 它的注释写着 "We only consider the default connection here: PHY0 -> USJ,
 * PHY1 -> USB_OTG" —— 而 app_main.c 的 route_fsls_phy0_to_otg() 恰恰把这个映射
 * 对调了。于是这一位实际关掉的是 **PHY0 = G24/G25 = Tab5 的 USB-C**。
 *
 * 症状：主机看得到设备（D+ 上拉还在），但 EP0 一个控制传输都不应答，CPU 不复位。
 * 反证：CONFIG_AIO_AUDIO_I2S_GPIO_NO_USB_PADS（整套音频照跑、只让开 G26/G27）
 *       下 GUD 与声卡全部正常 —— 罪就在「碰这两个脚」本身。
 *
 * 放在 tinyusb_driver_install() 之前，误伤发生时 USB 还没连主机；install 内部的
 * usb_new_phy() → usb_wrap_hal_init() → usb_wrap_ll_phy_set_defaults() 会把
 * usb_pad_enable 置回 1（esp_hal_usb/usb_wrap_hal.c:11-19），因此**没有任何
 * 「已枚举设备被短暂拔掉」的窗口**。install 之后 app_main.c 还会跑一次
 * otg_fsls_pads_repair() 兜底并撤销驱动能力误伤。
 *
 * ⓘ 前提：调用本函数时 USB_WRAP 的总线时钟必须已经开着，否则上面那次
 *   otg_conf 写入是对被门控外设的访问。route_fsls_phy0_to_otg() 已经负责打开。
 */
esp_err_t codec_audio_init(void)
{
    const int stage = CONFIG_AIO_AUDIO_FULL_STAGE;

    if (stage >= 1)
        ESP_RETURN_ON_ERROR(i2s_full_duplex_init(), TAG, "i2s");
    if (stage >= 2)
        ESP_RETURN_ON_ERROR(es8388_init(), TAG, "es8388");
    if (stage >= 3)
        ESP_RETURN_ON_ERROR(es7210_init(), TAG, "es7210");

    return ESP_OK;
}

/*
 * 功放上电 + 数据泵任务。**必须在 tinyusb_driver_install() 之后**：数据泵一起来
 * 就会调 tud_audio_*。硬件 bring-up 在 codec_audio_init() 里，见上。
 */
esp_err_t codec_audio_start(void)
{
    const int stage = CONFIG_AIO_AUDIO_FULL_STAGE;
    /* 0 与 5 都起数据泵，二者互为反向验证：0 是「只有数据泵」（codec/I2S 一个字
     * 不碰，句柄留 NULL），5 是「全都要」。中间四级都不起泵。 */
    const bool run_pump = (stage == 0 || stage == 5);

    if (stage >= 4) {
        /*
         * 功放**最后**开。ES8388 的 open() 第一条就是 DACCONTROL3 静音，随后由
         * esp_codec_dev_open() 内部解除静音；等 DAC 输出电平稳定下来再导通功放，
         * 否则开机会有一声「啪」。50 ms 是保守值，只在启动走一次。
         *
         * 对称地，若日后加关流路径，必须**先** board_speaker_enable(false) **再**
         * esp_codec_dev_close() —— esp_codec_dev_close() 不会碰这个引脚，顺序反了
         * 就是关机 pop。本阶段音频一路常开，不做关流。
         */
        vTaskDelay(pdMS_TO_TICKS(50));
        board_speaker_enable(true);
    }

    if (run_pump && xTaskCreate(audio_pump_task, "audio", AUDIO_TASK_STACK_SIZE, NULL,
                                AUDIO_TASK_PRIORITY, NULL) != pdPASS) {
        board_speaker_enable(false);
        return ESP_ERR_NO_MEM;
    }

    if (stage == 5)
        ESP_LOGI(TAG, "UAC1 全双工音频就绪：%d Hz / %d ch / 16 bit",
                 UAC_SAMPLE_RATE, UAC_CHANNEL_COUNT);
    else
        ESP_LOGW(TAG, "排障档 CONFIG_AIO_AUDIO_FULL_STAGE=%d：音频未完整启动", stage);
    return ESP_OK;
}

/*
 * ── TinyUSB 音频类回调 ────────────────────────────────────────────
 * host 用 SET_INTERFACE 在 alt 0（零带宽）与 alt 1（有端点）之间切换某个方向。
 */
static void update_stream_request(uint8_t itf, bool on)
{
    if (itf == ITF_NUM_AUDIO_STREAMING_OUT)
        s_spk_on = on;
    else if (itf == ITF_NUM_AUDIO_STREAMING_IN)
        s_mic_on = on;
}

bool tud_audio_set_itf_cb(uint8_t rhport, tusb_control_request_t const *request)
{
    (void)rhport;
    update_stream_request(tu_u16_low(request->wIndex), tu_u16_low(request->wValue) == 1);
    return true;
}

bool tud_audio_set_itf_close_ep_cb(uint8_t rhport, tusb_control_request_t const *request)
{
    (void)rhport;
    update_stream_request(tu_u16_low(request->wIndex), false);
    return true;
}

/*
 * UAC1 的采样率控制走**端点**请求（AUDIO10_EP_CTRL_SAMPLING_FREQ），
 * 不是 UAC2 的 clock source 实体。本设备只支持一个采样率：GET 如实回报，
 * SET 只接受这一个值 —— 返回 false 会让 TinyUSB STALL，host 据此知道协商失败。
 */
bool tud_audio_get_req_ep_cb(uint8_t rhport, tusb_control_request_t const *request)
{
    /* UAC1 的采样率是 3 字节小端。**不能是 const**：
     * tud_audio_buffer_and_schedule_control_xfer() 收的是 void*，加 const 只能靠
     * 丢弃限定符的强制转换蒙混过去，而那正是「看起来对、其实在说谎」的写法。 */
    static uint8_t sample_rate[3] = {
        (uint8_t)(UAC_SAMPLE_RATE & 0xff),
        (uint8_t)((UAC_SAMPLE_RATE >> 8) & 0xff),
        (uint8_t)((UAC_SAMPLE_RATE >> 16) & 0xff),
    };

    if (tu_u16_high(request->wValue) != AUDIO10_EP_CTRL_SAMPLING_FREQ ||
        request->bRequest != AUDIO10_CS_REQ_GET_CUR)
        return false;

    return tud_audio_buffer_and_schedule_control_xfer(rhport, request, sample_rate,
                                                      sizeof(sample_rate));
}

bool tud_audio_set_req_ep_cb(uint8_t rhport, tusb_control_request_t const *request,
                             uint8_t *buffer)
{
    (void)rhport;

    if (tu_u16_high(request->wValue) != AUDIO10_EP_CTRL_SAMPLING_FREQ ||
        request->bRequest != AUDIO10_CS_REQ_SET_CUR || request->wLength != 3)
        return false;

    const uint32_t rate = (uint32_t)buffer[0] |
                          ((uint32_t)buffer[1] << 8) |
                          ((uint32_t)buffer[2] << 16);
    return rate == UAC_SAMPLE_RATE;
}
