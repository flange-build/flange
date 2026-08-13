/*
 * touch_map_panel_to_gud() / touch_map_gud_to_hid() 宿主机回归测试。
 *
 * 触摸坐标反变换必须与 display_dsi.c 的 90° CCW 正变换严格互逆，否则实机
 * 表现是「点哪儿指针跑到别处」—— 从现象几乎反推不出是哪一步算错。这类
 * 纯算式最适合在宿主机钉死，所以照 test_kbd_translate.c 的做法：不引入
 * 任何测试框架，就是 main() + assert()，直接编译被测的真实源码
 * （main/touch_map.c），不是复制粘贴的另一份实现。
 *
 * 编译运行：
 *   cd firmware/test
 *   cc -std=c11 -Wall -Wextra -I../main test_touch_map.c ../main/touch_map.c \
 *       -o /tmp/test_touch_map && /tmp/test_touch_map
 *
 * 全部用例通过时打印 "OK (N cases)" 并以 0 退出。
 */
#include "touch_map.h"
#include "tab5_pins.h"

#include <assert.h>
#include <stdio.h>
#include <string.h>

static void expect(const char *name, uint16_t px, uint16_t py,
                   uint16_t want_x, uint16_t want_y)
{
    uint16_t gx = 0xFFFF, gy = 0xFFFF;   /* 哨兵值：确保函数真的写了它们 */
    touch_map_panel_to_gud(px, py, &gx, &gy);
    if (gx != want_x || gy != want_y) {
        fprintf(stderr, "FAIL [%s]: panel(%u,%u) -> gud(%u,%u), want (%u,%u)\n",
                name, px, py, gx, gy, want_x, want_y);
        assert(0 && "touch_map 用例失败");
    }
}

static void expect_hid(const char *name, uint16_t gud, uint16_t gud_max, uint16_t want)
{
    const uint16_t got = touch_map_gud_to_hid(gud, gud_max);
    if (got != want) {
        fprintf(stderr, "FAIL [%s]: gud(%u)/max(%u) -> %u, want %u\n",
                name, gud, gud_max, got, want);
        assert(0 && "touch_map_gud_to_hid 用例失败");
    }
}

/*
 * display_blit() 的正变换：一个 GUD 像素 (gx,gy) 被放大成面板上的
 * GUD_SCALE × GUD_SCALE 方块，左上角在
 *   panel_x = GUD_SCALE·gy
 *   panel_y = PANEL_H − GUD_SCALE·gx − GUD_SCALE
 * 这里按 (sx,sy) 取该方块内的第 (sx,sy) 个像素。
 */
static void gud_to_panel(uint16_t gx, uint16_t gy, int sx, int sy,
                         uint16_t *panel_x, uint16_t *panel_y)
{
    *panel_x = (uint16_t)(GUD_SCALE * gy + sx);
    *panel_y = (uint16_t)(PANEL_H - GUD_SCALE * gx - GUD_SCALE + sy);
}

int main(void)
{
    int n = 0;

    /* 1. 四角。手算依据：gud_x = (1279 − panel_y)/2、gud_y = panel_x/2。
     * 横持视角下面板的四个物理角与 GUD 四角的对应关系： */
    expect("panel(0,1279) -> gud 左上", 0, PANEL_H - 1, 0, 0);                         n++;
    expect("panel(719,1279) -> gud 左下", PANEL_W - 1, PANEL_H - 1, 0, GUD_H - 1);      n++;
    expect("panel(0,0) -> gud 右上", 0, 0, GUD_W - 1, 0);                              n++;
    expect("panel(719,0) -> gud 右下", PANEL_W - 1, 0, GUD_W - 1, GUD_H - 1);           n++;
    /* 计划正文里写的 panel(718,0) 与 panel(719,0) 落在同一个 GUD 像素上
     * （718/2 == 719/2 == 359），两者都应给出 gud(639,359)。 */
    expect("panel(718,0) 与 719 同像素", 718, 0, GUD_W - 1, GUD_H - 1);                n++;

    /* 2. 正中。GUD 正中像素 (320,180) 的面板方块是 x∈[360,362)、y∈[638,640)，
     * 故 panel(360,639) 与 panel(361,638) 都应还原成 (320,180)；
     * 紧邻的 panel(360,640) 属于 gx=319 那一列，用来确认边界没差一。 */
    expect("正中 panel(360,639)", 360, 639, 320, 180);                                 n++;
    expect("正中 panel(361,638)", 361, 638, 320, 180);                                 n++;
    expect("正中相邻 panel(360,640)", 360, 640, 319, 180);                             n++;

    /* 3. 越界钳位。触摸控制器可能报出略超面板范围的值；panel_y 超界尤其危险，
     * PANEL_H-1-panel_y 会变负、转 uint16_t 后绕成巨大值。 */
    expect("panel_y 超界 -> 钳到 y=1279", 0, PANEL_H, 0, 0);                           n++;
    expect("panel_y 大幅超界", 100, 60000, 0, 50);                                     n++;
    expect("panel_x 超界 -> 钳到 x=719", PANEL_W, PANEL_H - 1, 0, GUD_H - 1);           n++;
    expect("两轴同时超界", 60000, 60000, 0, GUD_H - 1);                                n++;

    /* 4. 与显示正变换的往返一致性。
     *
     * 容差取 0（不是 ±1）—— 这不是放松，而是可以证明的更强断言：
     * 一个 GUD 像素放大成 2×2 面板方块，方块内 4 个像素分别是
     *   panel_x = 2gy + sx        → panel_x/2 == gy         (sx∈{0,1})
     *   panel_y = 1278 − 2gx + sy → (1279−panel_y)/2 == gx  (sy∈{0,1})
     * 整数除法把两个子像素都收回同一个 GUD 坐标，故往返**精确**相等。
     * 若哪天变换改了导致出现 ±1 偏差，这里应该失败而不是被容差放过。
     *
     * 穷举全部 640×360 个 GUD 像素 × 4 个子像素（约 92 万次），宿主机上瞬时完成。
     */
    for (uint16_t gx = 0; gx < GUD_W; gx++) {
        for (uint16_t gy = 0; gy < GUD_H; gy++) {
            for (int sx = 0; sx < GUD_SCALE; sx++) {
                for (int sy = 0; sy < GUD_SCALE; sy++) {
                    uint16_t px, py, back_x, back_y;
                    gud_to_panel(gx, gy, sx, sy, &px, &py);
                    assert(px < PANEL_W && py < PANEL_H && "正变换落点越出面板");
                    touch_map_panel_to_gud(px, py, &back_x, &back_y);
                    if (back_x != gx || back_y != gy) {
                        fprintf(stderr, "FAIL [往返]: gud(%u,%u)+sub(%d,%d) -> panel(%u,%u)"
                                        " -> gud(%u,%u)\n", gx, gy, sx, sy, px, py, back_x, back_y);
                        assert(0 && "往返一致性失败");
                    }
                }
            }
        }
    }
    n++;

    /* 5. 反方向穷举：任意面板像素都必须落在 GUD 范围内（no-panic 保证）。 */
    for (uint32_t px = 0; px < PANEL_W; px++) {
        for (uint32_t py = 0; py < PANEL_H; py++) {
            uint16_t gx, gy;
            touch_map_panel_to_gud((uint16_t)px, (uint16_t)py, &gx, &gy);
            assert(gx < GUD_W && gy < GUD_H && "反解越出 GUD 范围");
        }
    }
    n++;

    /*
     * 6. HID 归一化 touch_map_gud_to_hid()。
     * 这是整条链路里最容易写出整数溢出的一步：639 × 32767 = 20,938,113，
     * 中间量若用 uint16_t 会绕回，表现是指针在屏幕上乱跳。
     */
    expect_hid("x 左端 0 -> 0", 0, GUD_W - 1, 0);                                      n++;
    expect_hid("x 右端 639 -> 满量程", GUD_W - 1, GUD_W - 1, TOUCH_HID_LOGICAL_MAX);   n++;
    expect_hid("y 上端 0 -> 0", 0, GUD_H - 1, 0);                                      n++;
    expect_hid("y 下端 359 -> 满量程", GUD_H - 1, GUD_H - 1, TOUCH_HID_LOGICAL_MAX);   n++;
    /* 中点。手算：320×32767 = 10,485,440，10,485,440/639 = 16409 余 89。
     * 180×32767 = 5,898,060，5,898,060/359 = 16429 余 49。
     * 都在半量程 16383 附近（GUD 像素索引 0..639 的正中是 319.5，故略偏大）。 */
    expect_hid("x 中点 320", 320, GUD_W - 1, 16409);                                   n++;
    expect_hid("y 中点 180", 180, GUD_H - 1, 16429);                                   n++;
    /* 越界钳位：钳的是入参而非结果，所以越多界都只到满量程，不会绕回。 */
    expect_hid("x 超界钳到满量程", 1000, GUD_W - 1, TOUCH_HID_LOGICAL_MAX);            n++;
    expect_hid("x 极端超界 65535", 65535, GUD_W - 1, TOUCH_HID_LOGICAL_MAX);           n++;
    expect_hid("y 极端超界 65535", 65535, GUD_H - 1, TOUCH_HID_LOGICAL_MAX);           n++;

    /* 7. 两轴各自穷举：值域不越 Logical Maximum，且随输入单调不减。
     * 单调性是溢出/绕回的直接探针 —— 一旦中间量在某个输入处绕回，
     * 输出必然出现一次下跌。 */
    for (int axis = 0; axis < 2; axis++) {
        const uint16_t gud_max = axis ? (uint16_t)(GUD_H - 1) : (uint16_t)(GUD_W - 1);
        uint16_t prev = 0;
        for (uint16_t g = 0; g <= gud_max; g++) {
            const uint16_t h = touch_map_gud_to_hid(g, gud_max);
            if (h > TOUCH_HID_LOGICAL_MAX || h < prev) {
                fprintf(stderr, "FAIL [归一化单调]: axis=%d gud=%u -> %u (前一个 %u)\n",
                        axis, g, h, prev);
                assert(0 && "归一化越界或非单调");
            }
            prev = h;
        }
        assert(prev == TOUCH_HID_LOGICAL_MAX && "轴末端应恰好是满量程");
    }
    n++;

    /*
     * 8. 多点报告装配 touch_report_fill()。
     *
     * 这一步写错的症状是「多指时某几根手指坐标错位 / 抬手后 host 以为还按着」，
     * 与坐标算错在现象上几乎无法区分，所以同样在宿主机钉死。
     *
     * 每个用例都顺带校验两条不变量：
     *   a) contact_count 恰好等于 tip=1 的 slot 数；
     *   b) 非活跃 slot 必须整体清零（不只是 tip=0）。
     */
    {
        /* 6 个源触点，超出 TOUCH_CONTACTS_MAX=5，用于检验截断 */
        touch_contact_t src[6];
        for (unsigned i = 0; i < 6; i++) {
            src[i].tip = 0;                     /* 故意填 0：应被 fill 覆写成 1 */
            src[i].contact_id = (uint8_t)(10 + i);
            src[i].x = (uint16_t)(1000 + i);
            src[i].y = (uint16_t)(2000 + i);
        }

        static const uint8_t in_n[]   = { 0, 1, 2, 5, 6, 255 };
        static const uint8_t want_n[] = { 0, 1, 2, 5, 5, 5   };

        for (unsigned c = 0; c < sizeof(in_n) / sizeof(in_n[0]); c++) {
            touch_report_t rpt;
            memset(&rpt, 0xAA, sizeof(rpt));    /* 脏底：漏写的字节会被抓到 */
            touch_report_fill(&rpt, src, in_n[c]);

            const uint8_t exp = want_n[c];
            if (rpt.contact_count != exp) {
                fprintf(stderr, "FAIL [fill n=%u]: contact_count=%u, want %u\n",
                        in_n[c], rpt.contact_count, exp);
                assert(0 && "contact_count 不对");
            }

            unsigned tips = 0;
            for (unsigned i = 0; i < TOUCH_CONTACTS_MAX; i++) {
                const touch_contact_t *s = &rpt.contacts[i];
                if (i < exp) {
                    tips++;
                    if (s->tip != 1 || s->contact_id != src[i].contact_id ||
                        s->x != src[i].x || s->y != src[i].y) {
                        fprintf(stderr, "FAIL [fill n=%u]: slot%u = {%u,%u,%u,%u}\n",
                                in_n[c], i, s->tip, s->contact_id, s->x, s->y);
                        assert(0 && "活跃 slot 内容不对（tip 必须被置 1）");
                    }
                } else {
                    if (s->tip || s->contact_id || s->x || s->y) {
                        fprintf(stderr, "FAIL [fill n=%u]: 空 slot%u 未清零 "
                                        "{%u,%u,%u,%u}\n",
                                in_n[c], i, s->tip, s->contact_id, s->x, s->y);
                        assert(0 && "非活跃 slot 必须整体清零");
                    }
                }
            }
            assert(tips == rpt.contact_count && "contact_count 应等于 tip=1 的 slot 数");
            n++;
        }

        /* n=0 的产物必须与「全零报告」逐字节相同 —— touch_task() 用这个
         * 等价关系做 last_rpt 的初值，不成立就会在开机后多发一条空报告。 */
        {
            touch_report_t rpt, zero;
            memset(&rpt, 0xAA, sizeof(rpt));
            memset(&zero, 0, sizeof(zero));
            touch_report_fill(&rpt, src, 0);
            assert(memcmp(&rpt, &zero, sizeof(rpt)) == 0 && "空报告应是全零");
            n++;
        }

        /* 装配同样的输入两次，结果必须逐字节相同 —— touch_task() 靠 memcmp
         * 判「状态没变」，若 fill 留下任何未初始化的洞，那条判定就会失效，
         * 表现为按住不动却每 20ms 重发一次报告。 */
        {
            touch_report_t a, b;
            memset(&a, 0x00, sizeof(a));
            memset(&b, 0xFF, sizeof(b));
            touch_report_fill(&a, src, 3);
            touch_report_fill(&b, src, 3);
            assert(memcmp(&a, &b, sizeof(a)) == 0 && "同输入应产出逐字节相同的报告");
            n++;
        }
    }

    printf("OK (%d cases)\n", n);
    return 0;
}
