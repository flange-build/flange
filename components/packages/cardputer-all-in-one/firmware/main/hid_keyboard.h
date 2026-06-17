#pragma once

#include "cardputer_kbd_map.h"

/* 启动 HID 键盘任务：常驻扫描 74HC138 矩阵键盘。 */
void hid_keyboard_start(void);

/* 取当前(去抖后)按下的键位集合，写入 out（最多 max 个），返回实际数量。
 * 供键值映射/上报使用。 */
int kbd_get_pressed(KbdPos_t *out, int max);
