#include "touch_map.h"
#include "tab5_pins.h"

/*
 * display_blit() 在 DISPLAY_ROT_CCW90 = 1（已实机标定）下的逐像素正变换是：
 *
 *     GUD gy ↦ panel x ∈ [GUD_SCALE·gy, GUD_SCALE·gy + GUD_SCALE)
 *     GUD gx ↦ panel y ∈ [PANEL_H − GUD_SCALE·gx − GUD_SCALE, PANEL_H − GUD_SCALE·gx)
 *
 * 反解即下面两行。边界自检：gud(0,0) ↔ panel(0,1279)、gud(639,359) ↔ panel(718,0)。
 *
 * ⚠️ panel_y 超过 PANEL_H-1 时 PANEL_H-1-panel_y 会变成负数（整型提升后是
 * 有符号运算），除完再转 uint16_t 就绕成一个巨大值 —— 所以**必须先钳入参**，
 * 光钳结果救不回来。钳完之后输出的上界是自动成立的：
 * tab5_pins.h 里的 _Static_assert 保证 GUD_W·GUD_SCALE == PANEL_H、
 * GUD_H·GUD_SCALE == PANEL_W，故 (PANEL_H-1)/GUD_SCALE == GUD_W-1、
 * (PANEL_W-1)/GUD_SCALE == GUD_H-1，不需要再对结果钳一次。
 */
void touch_map_panel_to_gud(uint16_t panel_x, uint16_t panel_y,
                            uint16_t *gud_x, uint16_t *gud_y)
{
    if (panel_x > PANEL_W - 1)
        panel_x = PANEL_W - 1;
    if (panel_y > PANEL_H - 1)
        panel_y = PANEL_H - 1;

    *gud_x = (uint16_t)((PANEL_H - 1 - panel_y) / GUD_SCALE);
    *gud_y = (uint16_t)(panel_x / GUD_SCALE);
}
