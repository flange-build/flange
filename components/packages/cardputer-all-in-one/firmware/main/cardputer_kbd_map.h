/*
 * cardputer_kbd_map.h — M5Cardputer 74HC138 矩阵键盘引脚与坐标常量
 *
 * 来源：M5Cardputer 库
 *   src/utility/Keyboard/KeyboardReader/IOMatrix.h
 *   src/utility/Keyboard/KeyboardReader/IOMatrix.cpp
 * SPDX-License-Identifier: MIT（原库）
 *
 * 坐标系：
 *   X 轴（列方向）：0..13，共 14 列
 *   Y 轴（行方向）：0..3，共 4 行（y = 3 为顶行）
 *   对应关系见 KBD_X_MAP 注释
 */
#pragma once

#include <stdint.h>

/* ------------------------------------------------------------------ */
/* 引脚定义（GPIO 编号）                                               */
/* ------------------------------------------------------------------ */

/* 74HC138 地址输入：A0/A1/A2（3 位列选，8 种组合）*/
#define KBD_COL_PIN_COUNT  3
static const int KBD_COL_PINS[KBD_COL_PIN_COUNT] = {8, 9, 11};

/* 行输入引脚（7 根，INPUT_PULLUP，按下时为低电平）*/
#define KBD_ROW_PIN_COUNT  7
static const int KBD_ROW_PINS[KBD_ROW_PIN_COUNT] = {13, 15, 3, 4, 5, 6, 7};

/* ------------------------------------------------------------------ */
/* 矩阵尺寸                                                            */
/* ------------------------------------------------------------------ */

#define KBD_COL_SEL_COUNT  8   /* 74HC138 列选值范围 0..7 */
#define KBD_ROW_COUNT      7   /* 行输入数量 */

/* ------------------------------------------------------------------ */
/* X 坐标映射表                                                        */
/* 原库 X_map_chart[7]：每个行引脚 j 对应两个可能的 X 坐标，            */
/*   列选值 i > 3 时取 x_1，否则取 x_2                                 */
/*                                                                     */
/* 表格格式：{行引脚位掩码(未使用，保留原库字段), x_1, x_2}            */
/* ------------------------------------------------------------------ */
typedef struct {
    uint8_t mask;  /* 原库 value 字段（位掩码），此处仅作参考 */
    uint8_t x_1;   /* 列选 i > 3 时的 X 坐标 */
    uint8_t x_2;   /* 列选 i <= 3 时的 X 坐标 */
} KbdXMapEntry_t;

static const KbdXMapEntry_t KBD_X_MAP[KBD_ROW_COUNT] = {
    /* j=0 */ {1,   0,  1},
    /* j=1 */ {2,   2,  3},
    /* j=2 */ {4,   4,  5},
    /* j=3 */ {8,   6,  7},
    /* j=4 */ {16,  8,  9},
    /* j=5 */ {32, 10, 11},
    /* j=6 */ {64, 12, 13},
};

/* ------------------------------------------------------------------ */
/* 键位坐标结构                                                        */
/* ------------------------------------------------------------------ */

typedef struct {
    int8_t x;  /* 0..13 */
    int8_t y;  /* 0..3  */
} KbdPos_t;

/* 最多同时按下的键数（6KRO，留余量）*/
#define KBD_MAX_PRESSED  14
