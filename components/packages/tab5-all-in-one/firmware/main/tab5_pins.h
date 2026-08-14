#pragma once
/*
 * M5Stack Tab5 板级常量。
 * 引脚值取自 esp-bsp bsp/m5stack_tab5（Apache-2.0）与官方原理图，勿凭记忆改。
 */

/* 内部 I2C：IO 扩展 / 触摸 / 音频 codec / IMU / RTC 共用 */
#define PIN_I2C_SDA        31
#define PIN_I2C_SCL        32

/* 显示 */
#define PIN_LCD_BL         22    /* 背光 LEDA */
#define IOEXP_ADDR         0x43  /* PI4IOE5V6408-1：管 LCD/TOUCH/SPEAKER/CAMERA 使能 */
#define ST7123_I2C_ADDR    0x55  /* ST7123 显示触控一体，存在即表明是 ST7123 批次 */
#define GT911_I2C_ADDR     0x14  /* GT911 触摸，存在即表明面板为 ILI9881C */
#define PIN_TOUCH_INT      23    /* GT911 INT；触摸电源使能在 IO 扩展 0x43 的 PIN5，board_power_init() 已拉高 */

/* Tab5 Keyboard：独立的 STM32F030 I2C 从机，挂在与内部 I2C 分离的另一条总线上。
 * INT 低有效（键盘固件拉低表示有事件），故 ESP 侧上拉 + 下降沿触发。 */
#define PIN_KBD_SDA        0
#define PIN_KBD_SCL        1
#define PIN_KBD_INT        50
#define KBD_I2C_ADDR       0x6D

/* ── 音频 ────────────────────────────────────────────────────────
 * I2S 的收发数据线**物理独立**（DOUT/DSIN 是两根脚），SCLK/LRCK/MCLK 共用，
 * 因此可以在一个 I2S 端口上组成真全双工 —— 不需要 Cardputer 上那套
 * 「扬声器与麦克风抢同一根 WS 脚」的半双工仲裁。
 * 取自 esp-bsp bsp/m5stack_tab5（Apache-2.0）。 */
#define PIN_I2S_MCLK       30
#define PIN_I2S_SCLK       27   /* BCLK */
#define PIN_I2S_LRCK       29   /* WS */
#define PIN_I2S_DOUT       26   /* ESP → ES8388，播放 */
#define PIN_I2S_DSIN       28   /* ES7210 → ESP，录音 */

/* 喇叭功放使能：与 LCD_EN(PIN4) / TOUCH_EN(PIN5) 同在 0x43 那颗 PI4IOE5V6408 上
 * （esp-bsp 的 BSP_SPEAKER_EN = IO_EXPANDER_PIN_NUM_1，其 BSP_IO_EXPANDER_ADDRESS
 * 即 ..._ADDRESS_LOW = 0x43）。功放**没有**独立 GPIO：esp-bsp 的
 * BSP_POWER_AMP_IO = GPIO_NUM_NC，所以 es8388_codec_cfg_t.pa_pin 那条路是空操作
 * （es8388.c 见 pa_pin == -1 直接 return），必须由我们经 IO 扩展自己驱动。 */
#define IOEXP_PIN_SPEAKER_EN  IO_EXPANDER_PIN_NUM_1

/* ⚠️ 两种 I2C 地址形式必须分开定名：i2c_master_probe() 收 **7 bit**，而
 * esp_codec_dev 的 audio_codec_i2c_cfg_t.addr 收 **8 bit**（驱动内部再 >>1，见
 * platform/audio_codec_ctrl_i2c.c）。混用的症状是 codec 初始化失败，或把寄存器
 * 写到别的器件上 —— 而 I2C 写没有任何反馈。 */
#define ES8388_I2C_ADDR7   0x10 /* 播放 codec，内部 I2C（实测 i2cscan 已应答） */
#define ES8388_I2C_ADDR8   0x20 /* == ES8388_CODEC_DEFAULT_ADDR */
#define ES7210_I2C_ADDR7   0x40 /* 双麦录音前端 */
#define ES7210_I2C_ADDR8   0x80 /* == ES7210_CODEC_DEFAULT_ADDR */

/* 面板原生分辨率（竖屏）与 DSI 参数 */
#define PANEL_W            720
#define PANEL_H            1280
#define DSI_LANE_NUM       2
#define DSI_LANE_MBPS      1000
#define DSI_PHY_LDO_CHAN   3     /* LDO_VO3 → VDD_MIPI_DPHY */
#define DSI_PHY_LDO_MV     2500

/*
 * 对 host 声明的 GUD 分辨率（横向）。USB-C 只有 12 Mbps 全速，720p 整帧 1.84MB
 * 约需 1.8 秒，交互不可用；640×360 整帧 460KB，且相对面板恰为整数 2 倍，
 * PPA 放大无插值伪影。GUD_W*2 == PANEL_H、GUD_H*2 == PANEL_W（因为要旋转 90°）。
 */
#define GUD_W              640
#define GUD_H              360
#define GUD_SCALE          2

_Static_assert(GUD_W * GUD_SCALE == PANEL_H, "GUD 宽度放大后应等于面板高度(旋转 90°)");
_Static_assert(GUD_H * GUD_SCALE == PANEL_W, "GUD 高度放大后应等于面板宽度(旋转 90°)");
