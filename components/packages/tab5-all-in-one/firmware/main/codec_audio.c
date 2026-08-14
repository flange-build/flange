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
 * ── 开机自检快照 ───────────────────────────────────────────────────
 *
 * 本模块**最关键的那几行日志天生打不出来**：codec_audio_init() 必须跑在
 * tinyusb_driver_install() 之前（见下方那段长注释），而这块板唯一可用的日志
 * 通道 —— CONFIG_AIO_DEBUG_CDC 那条 USB CDC 串口 —— 恰恰要等 install 之后才起得来。
 * 现场又没有 UART（USJ 被 TinyUSB 收走，UART0 只在 M5-Bus 排针上）。
 *
 * 所以把 init 阶段的每一个判定记成静态快照，等控制台可用后由
 * codec_audio_report() 复读。调用点见 app_main.c：默认档（日志走 UART0）打一遍，
 * 开了 CONFIG_AIO_DEBUG_CDC 时每 10 秒复读 —— CDC 的 TX 环形缓冲会把 host
 * 打开 ttyACM 之前的日志覆盖掉，只打一遍等于没打。
 */
/*
 * ⚠️ 三步的结果**各记各的**，不再共用「一个被反复覆写的 s_init_err + 一个事后
 * 才写的步数计数器」。上一版那个写法让「第 3 步没跑」与「第 3 步失败」在日志里
 * 长得一样，现场读到 `步数=2/3 err=ESP_OK` 这种自相矛盾的组合，白烧一次板。
 *
 * 哨兵值必须是一个**不可能是 esp_err_t 的数**：ESP_FAIL 与
 * ESP_CODEC_DEV_DRV_ERR 都等于 −1，拿 −1 当「没跑过」正是上一版骗人的地方
 * （`mic_open=-1` 既可能是没跑到那句，也可能是真的返回了 DRV_ERR）。
 */
#define STEP_NOT_RUN  INT32_MIN

static int  s_st_i2s = STEP_NOT_RUN;      /* i2s_full_duplex_init() 返回值 */
static int  s_st_spk = STEP_NOT_RUN;      /* es8388_init() 返回值 */
static int  s_st_mic = STEP_NOT_RUN;      /* es7210_init() 返回值 */
static bool s_init_duplex;                /* i2s_duplex_active() 的实测值 */
static int  s_open_spk = STEP_NOT_RUN;    /* esp_codec_dev_open(播放) 返回值 */
static int  s_open_mic = STEP_NOT_RUN;    /* esp_codec_dev_open(录音) 返回值 */
static bool s_pa_on;                      /* board_speaker_enable() 到底调没调 */
static const audio_codec_ctrl_if_t *s_spk_ctrl;   /* 留着回读寄存器用 */
static const audio_codec_ctrl_if_t *s_mic_ctrl;

/*
 * 三条链路各自可用与否。**播放与录音必须能各自降级**：ES8388 与 ES7210 是两颗
 * 独立的芯片，USB 侧也是两条独立的 AudioStreaming 接口，一颗挂掉不该拖死另一条。
 *   s_mic_ok=false ⇒ 播放照常，录音上报静音
 *   s_spk_ok=false ⇒ 录音照常，播放收到的数据直接丢弃
 * 只有 s_i2s_ok 为假（通道没建起来 / 没组成全双工）才两个方向一起放弃 ——
 * 那时候连时钟都没有，谈不上降级。
 */
static bool s_i2s_ok;
static bool s_spk_ok;
static bool s_mic_ok;

/*
 * ES7210 的细粒度排障位。init 跑在 CDC 日志串口起来之前，现场看不到它的
 * ESP_LOG*，所以「卡在哪一句」必须记进快照由 codec_audio_report() 复读。
 * s_mic_probe 单独存在的理由：把「芯片根本不应答」与「驱动初始化失败」分开 ——
 * 上一版这两种情况都只表现成一串 ffffffff，无从分辨。
 */
static const char *s_mic_step = "未开始";
static int s_mic_probe = STEP_NOT_RUN;

/*
 * 数据泵的 10 秒统计量。做成文件作用域（而不是任务局部）是为了让
 * codec_audio_report() 能在数据泵没起来时也照样打印一份「全 0」——
 * 「泵没在跑」与「泵在跑但没数据」是两个完全不同的结论。
 *
 * usb_peak / mic_peak 是这组数字里最值钱的两个：它们把
 * 「host 根本没送音频」与「送了但设备没放出来」一刀分开。
 */
static uint32_t s_stat_tx_underrun, s_stat_mic_overrun, s_stat_rx_fail;
static uint32_t s_stat_frames_total;
/* 本窗口内的最大 |sample|。初值 −1 = 「数据泵一转都没跑过」，与
 * 「跑了但全是静音(0)」是两个不同的结论，所以不能都用 0。 */
static int32_t  s_stat_usb_peak = -1;     /* USB OUT（host 送来的播放数据） */
static int32_t  s_stat_mic_peak = -1;     /* I2S RX（ES7210 送来的录音数据） */

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
        /* ⚠️ 配 bclk(G27) 与 dout(G26) 这一步会顺手关掉 USB-C 的焊盘 ——
         * 本板最贵的坑，机理见 tab5_pins.h 的音频段，修法是本函数所在的
         * codec_audio_init() 必须排在 tinyusb_driver_install() 之前。 */
        .gpio_cfg = {
            .mclk = PIN_I2S_MCLK,
            .bclk = PIN_I2S_SCLK,
            .ws   = PIN_I2S_LRCK,
            .dout = PIN_I2S_DOUT,
            .din  = PIN_I2S_DSIN,
            .invert_flags = { .mclk_inv = false, .bclk_inv = false, .ws_inv = false },
        },
    };

    ESP_RETURN_ON_ERROR(i2s_channel_init_std_mode(s_tx, &std_cfg), TAG, "i2s tx");
    ESP_RETURN_ON_ERROR(i2s_channel_init_std_mode(s_rx, &std_cfg), TAG, "i2s rx");

    const bool duplex = i2s_duplex_active();
    s_init_duplex = duplex;
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
    s_spk_ctrl = ctrl;   /* 留给 codec_audio_report() 回读寄存器 */

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
    s_open_spk = esp_codec_dev_open(s_spk_dev, &fs);
    ESP_RETURN_ON_FALSE(s_open_spk == ESP_CODEC_DEV_OK, ESP_FAIL, TAG, "es8388 open");

    /* 开机音量取 70%：满量程直推板载小喇叭在中低频容易破音，而破音很容易被误判
     * 成时钟配错。host 侧还会再叠一层软件音量（本阶段不声明 Feature Unit）。 */
    esp_codec_dev_set_out_vol(s_spk_dev, 70);
    return ESP_OK;
}

static esp_err_t es7210_init(void)
{
    /*
     * 先 probe 再 init。这一句把「芯片不应答」与「驱动初始化失败」彻底分开 ——
     * 二者在上一版里都只表现成寄存器读出一串 ffffffff，无从分辨。
     *
     * 地址核对（原理图第 3 页 U13）：AD0(pin1) 与 AD1(pin2) **双双接 AGND**
     * ⇒ 7 bit 地址 0x40 / 8 bit 0x80，与 esp-bsp 的 m5stack_tab5 用的
     * ES7210_CODEC_DEFAULT_ADDR(0x80) 一致，也与实机 i2cscan 扫到的 0x40 对上。
     * ⚠️ 板上 R34/R36 那两颗 0R **不是**地址跳线：它们是 CDATA(pin3)/CCLK(pin4)
     * 串到 xG31_SYS_SDA / xG32_SYS_SCL 的跳线电阻，与 AD0/AD1 无关。
     */
    s_mic_probe = i2c_master_probe(board_i2c_bus(), ES7210_I2C_ADDR7, 100);
    ESP_LOGI(TAG, "ES7210 probe(0x%02x) = %s", ES7210_I2C_ADDR7,
             esp_err_to_name(s_mic_probe));

    audio_codec_i2c_cfg_t i2c_cfg = {
        .port       = I2C_NUM_0,
        .addr       = ES7210_I2C_ADDR8,      /* ⚠️ 8 bit 形式(0x80)，驱动内部会 >>1 */
        .bus_handle = board_i2c_bus(),
    };
    /* s_mic_step 逐句推进：失败时它停在**出事的那一句**上，由自检日志复读。 */
    s_mic_step = "audio_codec_new_i2c_ctrl";
    const audio_codec_ctrl_if_t *ctrl = audio_codec_new_i2c_ctrl(&i2c_cfg);
    ESP_RETURN_ON_FALSE(ctrl, ESP_FAIL, TAG, "es7210 i2c ctrl");
    s_mic_ctrl = ctrl;   /* 留给 codec_audio_report() 回读寄存器 */

    audio_codec_i2s_cfg_t i2s_cfg = {
        .port = AUDIO_I2S_PORT, .tx_handle = NULL, .rx_handle = s_rx,
    };
    s_mic_step = "audio_codec_new_i2s_data";
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
    /* ⓘ es7210_codec_new() 内部就会跑整段 I2C 寄存器序列（es7210_open()）。
     * 它返回 NULL ⇒ 那串写全 NAK 了 ⇒ 芯片没在总线上应答，看 probe 的结果对齐。 */
    s_mic_step = "es7210_codec_new";
    const audio_codec_if_t *codec = es7210_codec_new(&cfg);
    ESP_RETURN_ON_FALSE(codec, ESP_FAIL, TAG, "es7210 new");

    esp_codec_dev_cfg_t dev_cfg = {
        .dev_type = ESP_CODEC_DEV_TYPE_IN, .codec_if = codec, .data_if = data,
    };
    s_mic_step = "esp_codec_dev_new";
    s_mic_dev = esp_codec_dev_new(&dev_cfg);
    ESP_RETURN_ON_FALSE(s_mic_dev, ESP_FAIL, TAG, "es7210 dev");

    /* ⚠️ 全场最不放心的一句：它会去 reconfig **已经在跑的**那条全双工 I2S
     * （esp_codec_dev → audio_codec_data_i2s.c 的 check_fs_compatible() →
     *   i2s_channel_reconfig_std_slot/clock）。失败时 s_mic_step 停在这里，
     * 而 probe=ESP_OK 就说明芯片本身没问题、问题出在 I2S 重配这一侧。 */
    s_mic_step = "esp_codec_dev_open";
    esp_codec_dev_sample_info_t fs = wire_format();
    s_open_mic = esp_codec_dev_open(s_mic_dev, &fs);
    ESP_RETURN_ON_FALSE(s_open_mic == ESP_CODEC_DEV_OK, ESP_FAIL, TAG, "es7210 open");

    /* 30 dB 是 IDF 官方 es7210 例子的取值，对驻极体麦是个「能听清说话又不啸叫」
     * 的起点。真要调，先在 host 侧用 `sox -n stat` 看 RMS 再动。 */
    esp_codec_dev_set_in_gain(s_mic_dev, 30.0f);
    s_mic_step = "完成";
    return ESP_OK;
}

/* 一段 16 bit 样本里的最大绝对值。用来回答「这条链路上到底有没有信号」——
 * 比任何寄存器都直接。取反用 int32 中转，免得 INT16_MIN 溢出。 */
static int32_t frame_peak(const int16_t *buf, size_t n)
{
    int32_t peak = 0;

    for (size_t i = 0; i < n; i++) {
        int32_t v = buf[i] < 0 ? -(int32_t)buf[i] : buf[i];
        if (v > peak)
            peak = v;
    }
    return peak;
}

/*
 * 数据泵：每 1 ms 一转，同时搬两个方向。
 *
 * ⚠️ 节拍源是**动态**的，这正是「播放与录音解耦」在泵里的落点。
 * 上一版把 i2s_channel_read() 当唯一节拍源，读失败就 `continue` 掉整轮 ——
 * 于是 ES7210 一挂，完好的 ES8388 也跟着一声不出：播放被录音挟持。现在改成
 * 「谁阻塞成功谁就是节拍」：
 *
 *   录音可用   → i2s_channel_read()  读满一个 DMA 描述符(= 1 ms 的样本)才返回
 *   只有播放   → i2s_channel_write() 在 DMA 排满时阻塞，同样是 1 ms 一拍
 *   两个都没有 → 退回 vTaskDelay()（两颗 codec 都没起来时走这条）
 *
 * 一整轮谁都没阻塞成功时**必须**补一次延时：那两个超时只在通道已 RUNNING 时
 * 才真的阻塞，通道没使能时两个调用都立即返回错误，不补延时本循环就退化成不让出
 * CPU 的忙转、独占一个核，把同核的低优先级任务连同 idle 任务一起饿死 ——
 * 「音频没起来」会升级成「整块板子不正常」。
 */
static void audio_pump_task(void *arg)
{
    int16_t rx_stereo[UAC_FRAME_SAMPLES * 2];
    int16_t tx_stereo[UAC_FRAME_SAMPLES * 2];
    int16_t usb_mono[UAC_FRAME_SAMPLES];
    uint32_t frames = 0;
    /* 上一转录音是否在流。用来把「清空软件 FIFO」做成**边沿触发**，见下方。 */
    bool mic_streaming = false;

    /* 两个方向各自到底能不能收发。init 之后这两个值不再变，所以只读一次。 */
    const bool rx_live = (s_i2s_ok && s_rx != NULL && s_mic_ok);
    const bool tx_live = (s_i2s_ok && s_tx != NULL && s_spk_ok);

    (void)arg;

    /* 从 −1（没跑过）转成 0（跑了，静音），见两者的声明处。 */
    s_stat_usb_peak = 0;
    s_stat_mic_peak = 0;

    ESP_LOGI(TAG, "数据泵启动：播放(TX)=%d 录音(RX)=%d", tx_live, rx_live);

    while (1) {
        /* 本轮有没有真的在某个 I2S 调用上阻塞过 —— 见函数头那段节拍源说明。 */
        bool paced = false;
        size_t got = 0;

        if (rx_live &&
            i2s_channel_read(s_rx, rx_stereo, sizeof(rx_stereo), &got,
                             pdMS_TO_TICKS(50)) == ESP_OK &&
            got == sizeof(rx_stereo)) {
            paced = true;
        } else {
            if (rx_live)
                s_stat_rx_fail++;
            /* 录音不可用（或本轮读失败）就上报静音。**绝不 continue** ——
             * 那正是上一版让录音挟持播放的那一行。 */
            memset(rx_stereo, 0, sizeof(rx_stereo));
        }

        /* ── 录音：I2S RX → USB IN ──
         * tud_audio_write() 只写进软件 FIFO，真正的分包由 TinyUSB 按
         * CFG_TUD_AUDIO_EP_IN_FLOW_CONTROL 决定（标称 16 样本 ±1）——
         * 这正是「异步 IN 不需要反馈端点」的实现基础。 */
        {
            /* 录音侧的信号电平**无条件**统计：host 没开录音时也想知道
             * ES7210 有没有在往 DSIN 上送东西。 */
            int32_t p = frame_peak(rx_stereo, UAC_FRAME_SAMPLES * 2);
            if (p > s_stat_mic_peak)
                s_stat_mic_peak = p;
        }

        if (s_mic_on && tud_mounted()) {
            audio_frame_stereo_to_mono(rx_stereo, usb_mono, UAC_FRAME_SAMPLES);
            if (tud_audio_write(usb_mono, UAC_FRAME_BYTES) != UAC_FRAME_BYTES)
                s_stat_mic_overrun++;
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
        {
            int32_t p = frame_peak(usb_mono, UAC_FRAME_SAMPLES);
            if (p > s_stat_usb_peak)
                s_stat_usb_peak = p;
        }
        audio_frame_mono_to_stereo(usb_mono, tx_stereo, UAC_FRAME_SAMPLES);

        size_t written = 0;
        if (tx_live) {
            if (i2s_channel_write(s_tx, tx_stereo, sizeof(tx_stereo), &written,
                                  pdMS_TO_TICKS(20)) != ESP_OK ||
                written != sizeof(tx_stereo))
                s_stat_tx_underrun++;
            else
                paced = true;   /* DMA 排满时它会阻塞 —— TX-only 下的节拍源 */
        }

        /*
         * ⚠️ 无条件计数。上一版把它排在 RX 那条 `continue` 之后，于是
         * 「泵在转但 RX 一直读不到」会被自检报成 pump=0（= 泵根本没起来），
         * 把人往完全错误的方向带。现在 pump≠0 ⟺ 泵任务活着，仅此而已。
         */
        s_stat_frames_total++;

        if (!paced)
            vTaskDelay(pdMS_TO_TICKS((rx_live || tx_live) ? 10 : 1));

        /* 只计数，每 10 秒汇总一条 —— 见 AUDIO_STAT_PERIOD_FRAMES 上的注释。
         * 无条件打印（不再只在出错时打）：现场唯一的日志通道是那条 CDC 串口，
         * 「spk_on 有没有变 1、usb_peak 是不是一直 0」正是判断
         * 「host 到底送没送音频」的那一行，比错误计数值钱得多。 */
        if (++frames >= AUDIO_STAT_PERIOD_FRAMES) {
            ESP_LOGI(TAG, "10s 泵：spk_on=%d mic_on=%d usb_peak=%" PRId32
                          " mic_peak=%" PRId32 " | TX 欠载 %" PRIu32
                          " 麦 FIFO 溢出 %" PRIu32 " RX 读失败 %" PRIu32,
                     s_spk_on, s_mic_on, s_stat_usb_peak, s_stat_mic_peak,
                     s_stat_tx_underrun, s_stat_mic_overrun, s_stat_rx_fail);
            s_stat_tx_underrun = s_stat_mic_overrun = s_stat_rx_fail = 0;
            s_stat_usb_peak = s_stat_mic_peak = 0;
            frames = 0;
        }
    }
}

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
 * 反证（当时的二分实测）：整套音频照跑、只把 G26/G27 从 gpio_cfg 里让开时，
 *       GUD 与声卡全部正常 —— 罪就在「碰这两个脚」本身。
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
    /*
     * 每一步的结果都记进各自的快照槽：本函数跑在 CDC 日志串口起来之前，
     * 这里的 ESP_LOG* 现场看不到，全靠 codec_audio_report() 复读。
     *
     * ⚠️ **两颗 codec 各自失败、各自降级**，一颗挂掉不中断另一颗的初始化。
     * 只有 I2S 本身起不来才提前返回错误 —— 那时候连时钟都没有，两个方向都没戏。
     */
    s_st_i2s = i2s_full_duplex_init();
    if (s_st_i2s != ESP_OK) {
        ESP_LOGE(TAG, "I2S 起不来(%s)，播放与录音一起放弃", esp_err_to_name(s_st_i2s));
        return s_st_i2s;
    }
    s_i2s_ok = true;

    s_st_spk = es8388_init();
    s_spk_ok = (s_st_spk == ESP_OK);
    if (!s_spk_ok)
        ESP_LOGE(TAG, "ES8388(播放)初始化失败(%s)；录音不受影响，继续",
                 esp_err_to_name(s_st_spk));

    s_st_mic = es7210_init();
    s_mic_ok = (s_st_mic == ESP_OK);
    if (!s_mic_ok)
        ESP_LOGE(TAG, "ES7210(录音)初始化失败(%s，卡在 %s，probe=%s)；播放不受影响，继续",
                 esp_err_to_name(s_st_mic), s_mic_step, esp_err_to_name(s_mic_probe));

    return ESP_OK;
}

/* 回读一个 codec 寄存器；读不到（或 ctrl 还没建出来）返回 −1
 * ——下面按 %02x 打，所以现场看到的是一串 `ffffffff`，与 00~ff 一眼可分。
 * 只在 codec_audio_report() 里用，10 秒一次，不在任何实时路径上。 */
static int reg_rd(const audio_codec_ctrl_if_t *ctrl, int reg)
{
    int v = 0;

    if (ctrl == NULL || ctrl->read_reg == NULL)
        return -1;
    if (ctrl->read_reg(ctrl, reg, 1, &v, 1) != ESP_CODEC_DEV_OK)
        return -1;
    return v & 0xff;
}

/*
 * 把「音频到底卡在哪一步」一次性打出来。
 *
 * 为什么需要它：见文件上方那段「开机自检快照」。调用节奏见 app_main.c
 * （默认档打一遍；开 CDC 时每 10 秒复读，因为它的 TX 环形缓冲会覆盖）。
 *
 * 读法（从上往下，第一条不对的就是根因）：
 *   I2S!=ESP_OK / duplex=0 → I2S 没起来或没组成全双工，两个方向都没戏，先修它。
 *   播放=... / 录音=...    → 两条链路**各自**的 init 返回值。「未运行」= 那一步
 *                            压根没跑（I2S 失败提前返回了），与「失败」严格区分。
 *   ES7210 probe=ESP_OK 但 init 失败 → 芯片在总线上、应答正常，罪在驱动那一侧，
 *                            「卡在=」指出具体是哪一句。
 *   ES7210 probe=ESP_ERR_NOT_FOUND  → 芯片不应答（地址/供电/走线），别再查驱动。
 *   ES8388 寄存器全打成 ffffffff → 回读失败，I2C 根本没通（地址/总线/上电）。
 *   DACPOWER!=0x3c 或 DACCONTROL3 的 bit2=1 → DAC 没上电 / 还在静音。
 *   pa=0               → 功放没导通（ES8388 没起来，或 IO 扩展写失败）。
 *   pump=0             → 数据泵任务没起来（≠「起来了但没数据」，见泵里的计数说明）。
 *   spk_on=0           → **host 从没把播放接口切到 alt 1**：问题在主机侧
 *                        （没选对声卡 / 没在放音），不在固件。
 *   spk_on=1 但 usb_peak=0 → host 选了接口却只送静音。
 *   usb_peak>0 但仍没声 → 数字侧全通，问题在 codec 之后的模拟侧（音量/路由/功放/喇叭）。
 */

/* 把一个快照槽打成人话。哨兵与真实错误码严格分开 —— 见 STEP_NOT_RUN 的声明。
 * esp_err_to_name() 返回的是常量表里的指针，同一条 printf 里多次调用是安全的。 */
static const char *step_str(int v)
{
    return v == STEP_NOT_RUN ? "未运行" : esp_err_to_name(v);
}

void codec_audio_report(void)
{
    ESP_LOGI(TAG, "[自检] I2S=%s duplex=%d | 播放 ES8388=%s open=%s | "
                  "录音 ES7210=%s open=%s | pa=%d pump=%d",
             step_str(s_st_i2s), s_init_duplex,
             step_str(s_st_spk), step_str(s_open_spk),
             step_str(s_st_mic), step_str(s_open_mic),
             s_pa_on, s_stat_frames_total != 0);

    /* ES7210 的两条硬证据：芯片认不认这个地址（probe），以及 init 停在哪一句。 */
    ESP_LOGI(TAG, "[自检] ES7210 probe(0x%02x)=%s 卡在=%s",
             ES7210_I2C_ADDR7, step_str(s_mic_probe), s_mic_step);

    /* ES8388：0x02 CHIPPOWER(期望 0x00)、0x04 DACPOWER(期望 0x3c)、
     * 0x19 DACCONTROL3(bit2=1 即静音)、0x1a/0x1b DAC 左右音量(0=0dB，越大越轻)、
     * 0x2e/0x2f LOUT1/ROUT1 音量(0x1e=0dB)、0x30/0x31 LOUT2/ROUT2 音量(驱动写 0x00)。
     * 全打成 ffffffff 就说明 I2C 没通，那比任何别的结论都优先。 */
    ESP_LOGI(TAG, "[自检] ES8388 chippwr=%02x dacpwr=%02x dacctl3=%02x vol L/R=%02x/%02x "
                  "LOUT1/ROUT1=%02x/%02x LOUT2/ROUT2=%02x/%02x",
             reg_rd(s_spk_ctrl, 0x02), reg_rd(s_spk_ctrl, 0x04), reg_rd(s_spk_ctrl, 0x19),
             reg_rd(s_spk_ctrl, 0x1a), reg_rd(s_spk_ctrl, 0x1b),
             reg_rd(s_spk_ctrl, 0x2e), reg_rd(s_spk_ctrl, 0x2f),
             reg_rd(s_spk_ctrl, 0x30), reg_rd(s_spk_ctrl, 0x31));

    /* ES7210：MIC1/MIC2 增益(0x43/0x44) 与 MIC12 电源(0x4b)。同样只为证明 I2C 通没通。 */
    ESP_LOGI(TAG, "[自检] ES7210 mic1gain=%02x mic2gain=%02x mic12pwr=%02x",
             reg_rd(s_mic_ctrl, 0x43), reg_rd(s_mic_ctrl, 0x44), reg_rd(s_mic_ctrl, 0x4b));

    ESP_LOGI(TAG, "[自检] 泵 帧=%" PRIu32 " spk_on=%d mic_on=%d usb_peak=%" PRId32
                  " mic_peak=%" PRId32,
             s_stat_frames_total, s_spk_on, s_mic_on, s_stat_usb_peak, s_stat_mic_peak);
}

/*
 * 功放上电 + 数据泵任务。**必须在 tinyusb_driver_install() 之后**：数据泵一起来
 * 就会调 tud_audio_*。硬件 bring-up 在 codec_audio_init() 里，见上。
 */
esp_err_t codec_audio_start(void)
{
    /*
     * 功放只在 ES8388 真的配好时才导通 —— 接在一颗没配好的 DAC 后面只会放大噪声。
     * ⚠️ 与 ES7210 无关：那是另一颗芯片、另一条 USB 接口，它挂了播放照样要出声。
     */
    if (s_spk_ok) {
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
        s_pa_on = true;
    }

    if (xTaskCreate(audio_pump_task, "audio", AUDIO_TASK_STACK_SIZE, NULL,
                    AUDIO_TASK_PRIORITY, NULL) != pdPASS) {
        if (s_pa_on) {
            board_speaker_enable(false);
            s_pa_on = false;
        }
        return ESP_ERR_NO_MEM;
    }

    ESP_LOGI(TAG, "UAC1 音频就绪：%d Hz / %d ch / 16 bit（播放=%s，录音=%s）",
             UAC_SAMPLE_RATE, UAC_CHANNEL_COUNT,
             s_spk_ok ? "可用" : "降级：丢弃 host 送来的数据",
             s_mic_ok ? "可用" : "降级：向 host 上报静音");
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
