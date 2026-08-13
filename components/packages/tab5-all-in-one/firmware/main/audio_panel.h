#pragma once
/*
 * bring-up 期的屏上状态面板。整个模块由 CONFIG_TAB5_AUDIO_PANEL 门控，
 * 关闭时下面三个函数全部编译成空（见 audio_panel.c 的 #if），调用点不必加条件。
 *
 * 为什么需要它：这块板默认没有可用串口，而 codec/I2S bring-up 阶段 USB 侧还
 * 什么都没有 —— 屏幕是那一段唯一看得见的输出。详见计划的硬约束 C。
 */
#include <stdint.h>
#include "esp_err.h"

/* 分配 PSRAM 缓冲。须在 display_init() 之后调用（要用 display_blit）。 */
esp_err_t audio_panel_init(void);

/* 设置第 line 行（0..AUDIO_PANEL_STATUS_LINES-1）的文本。
 * **内容没变就不重画**，因此可以在任何地方无脑调用。 */
void audio_panel_status(int line, const char *text);

/* 更新电平条。**内部按 5 Hz 节流**，因此可以在每毫秒的数据泵里无脑调用。 */
void audio_panel_levels(uint16_t peak_l, uint16_t peak_r);
