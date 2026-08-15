#pragma once
/*
 * 把键盘「当前按下集合」翻译成标准 HID 键盘报告（modifier + 最多 6 个
 * keycode）。纯函数，不依赖 I2C / TinyUSB —— 从 kbd_i2c.c 的
 * kbd_build_and_report() 拆出来，专门是为了让这段刚踩过坑的分层逻辑
 * （Sym/Aa/Ctrl/Alt、底行 firstModifierMask 陷阱）能在宿主机用普通 gcc
 * 跑回归测试，见 firmware/test/test_kbd_translate.c。
 */
#include <stdbool.h>
#include <stdint.h>

#define KBD_ROWS 5
#define KBD_COLS 14

/* 标准 HID 键盘报告的非修饰键槽数（6KRO）。 */
#define KBD_KEYS_MAX 6

/*
 * out_modifier / out_keys 由调用者提供存储；out_keys 必须能容纳 KBD_KEYS_MAX 个
 * 字节，未用满的槽位写 0。返回值 = 写入 out_keys 的有效 keycode 数（0~KBD_KEYS_MAX）。
 * 分层规则见 kbd_translate.c 顶部注释。
 */
int kbd_translate(const bool pressed[KBD_ROWS][KBD_COLS], uint8_t *out_modifier, uint8_t out_keys[KBD_KEYS_MAX]);
