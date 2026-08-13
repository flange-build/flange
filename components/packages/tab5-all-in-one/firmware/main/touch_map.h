#pragma once
/*
 * 触摸坐标反变换：面板原生坐标 → host 看到的 GUD 坐标。
 *
 * 纯函数，不依赖 ESP-IDF —— 与 kbd_translate.c 同样的理由：这段算式
 * 完全可以在宿主机验证，且写错了在实机上只表现为「点哪儿指针跑到别处」，
 * 极难从现象反推。见 firmware/test/test_touch_map.c。
 */
#include <stdint.h>

/*
 * 把面板原生坐标(720×1280 竖向)还原成 host 看到的 GUD 坐标(640×360 横向)，
 * 与 display_blit() 的 2× 放大 + 90° CCW 旋转互逆。
 *
 * 入参会先被钳到面板范围内（触摸控制器可能报出略超范围的值），因此输出
 * 必然落在 [0,GUD_W-1] × [0,GUD_H-1]。gud_x / gud_y 由调用者提供存储。
 */
void touch_map_panel_to_gud(uint16_t panel_x, uint16_t panel_y,
                            uint16_t *gud_x, uint16_t *gud_y);

/*
 * HID digitizer 报告里 X/Y 的 Logical Maximum。报告描述符与下面的归一化
 * 共用这一个常量（usb_descriptors.c 为此包含本头文件）—— 两处写死不同的数
 * 只会表现为「指针位置按比例偏移」，从现象很难反推。
 *
 * 取 32767 而非 65535：Logical Maximum 在 HID 里是**有符号**量，超过 32767
 * 就得用 3/4 字节编码并小心正负，没必要。
 */
#define TOUCH_HID_LOGICAL_MAX 32767

/*
 * 把 GUD 坐标归一化成 HID 逻辑值 [0, TOUCH_HID_LOGICAL_MAX]。
 * gud_max 传该轴的最大合法坐标（GUD_W-1 / GUD_H-1），入参超界会先钳到它。
 *
 * 归一化让报告描述符与 GUD 分辨率解耦：换分辨率只改调用方传的 gud_max。
 * gud_max 必须非 0（调用方传的都是编译期常量 639 / 359）。
 */
uint16_t touch_map_gud_to_hid(uint16_t gud, uint16_t gud_max);
