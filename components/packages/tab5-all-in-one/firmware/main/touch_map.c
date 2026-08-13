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

/*
 * ⚠️ 溢出：gud_max 取 GUD_W-1 = 639 时，中间积是 639 × 32767 = 20,938,113 ——
 * 早已超出 uint16_t，也超出 int16_t。这里显式用 uint32_t 中间量，而不是
 * 依赖「int 至少 32 位」的整型提升：C 只保证 int ≥ 16 位，在 16 位 int 的
 * 实现上 uint16_t 会提升成 int 并直接溢出（未定义行为）。宿主机与 P4 上
 * int 都是 32 位，但把它钉死是零成本的。
 *
 * 结果范围：分子 ≤ gud_max × 32767，除以 gud_max 后 ≤ 32767，故转 uint16_t
 * 无损；且入参钳位保证了这个上界（不钳的话超界入参会算出 >32767 的值，
 * host 侧表现为指针冲到屏幕外或绕回）。
 */
uint16_t touch_map_gud_to_hid(uint16_t gud, uint16_t gud_max)
{
    if (gud > gud_max)
        gud = gud_max;

    return (uint16_t)(((uint32_t)gud * TOUCH_HID_LOGICAL_MAX) / gud_max);
}

/*
 * 见 touch_map.h 的契约说明。刻意做成不依赖 esp_lcd_touch 的纯函数：
 * 「几个触点装进几个 slot、多出来的怎么办、contact_count 填几」这几件事
 * 写错了在实机上都表现为「多指时坐标错位或干脆没反应」，从现象反推极难，
 * 放到宿主机上钉死（见 firmware/test/test_touch_map.c）成本几乎为零。
 *
 * **未使用的 slot 必须整体清零**，不能只清 tip：Linux hid-multitouch 是按
 * contact_count 决定处理前几个 slot，剩下的本就该是干净的 tip=0 空槽；
 * 留着上一帧的残值只会在排查时误导人。
 */
void touch_report_fill(touch_report_t *rpt, const touch_contact_t *active, uint8_t n)
{
    if (n > TOUCH_CONTACTS_MAX)
        n = TOUCH_CONTACTS_MAX;

    for (uint8_t i = 0; i < TOUCH_CONTACTS_MAX; i++) {
        if (i < n) {
            rpt->contacts[i] = active[i];
            rpt->contacts[i].tip = 1;   /* 不信调用方填的，见头文件契约 */
        } else {
            const touch_contact_t empty = {0};
            rpt->contacts[i] = empty;
        }
    }

    rpt->contact_count = n;
}
