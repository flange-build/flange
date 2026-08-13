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

/* Tab5 Keyboard：独立的 STM32F030 I2C 从机，挂在与内部 I2C 分离的另一条总线上。
 * INT 低有效（键盘固件拉低表示有事件），故 ESP 侧上拉 + 下降沿触发。 */
#define PIN_KBD_SDA        0
#define PIN_KBD_SCL        1
#define PIN_KBD_INT        50
#define KBD_I2C_ADDR       0x6D

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
