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
