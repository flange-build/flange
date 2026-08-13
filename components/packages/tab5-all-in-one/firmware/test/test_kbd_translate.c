/*
 * kbd_translate() 宿主机回归测试 —— M5Stack Tab5 键盘分层逻辑
 * （Sym/Aa/Ctrl/Alt、底行 firstModifierMask 陷阱）目前是这个包里唯一纯
 * 逻辑、可在宿主机跑、且已经被证明容易写错的部分（P1 Task3 才修过一次
 * Aa/Ctrl 互斥的 bug），所以给它固化一套用例，下次谁动分层逻辑都能立刻
 * 发现回归。
 *
 * 不引入任何测试框架，就是 main() + assert()。直接编译被测的真实源码
 * （main/kbd_translate.c），不是复制粘贴的另一份实现，故不会与真实固件
 * 行为脱钩。
 *
 * 编译运行：
 *   cd firmware/test
 *   cc -std=c11 -Wall -Wextra -I../main test_kbd_translate.c ../main/kbd_translate.c \
 *       -o /tmp/test_kbd_translate && /tmp/test_kbd_translate
 *
 * 全部用例通过时打印 "OK (N cases)" 并以 0 退出；任何一条 assert 失败会
 * 中止并打印失败的文件:行号。
 */
#include "kbd_translate.h"
#include "tab5_kbd_map.h"

#include <assert.h>
#include <stdio.h>
#include <string.h>

/* 行列坐标，来自 tab5_kbd_map.h 顶部注释与 kbd_i2c.c 的 IS_SYM/IS_AA。 */
#define R_SYM 3
#define C_SYM 0
#define R_AA  3
#define C_AA  1
#define R_CTRL 4
#define C_CTRL 0
#define R_ALT  4
#define C_ALT  1

static void press(bool p[KBD_ROWS][KBD_COLS], int r, int c)
{
    p[r][c] = true;
}

/* 断言 modifier/keys 与期望完全一致；keys 用 -1 结尾（比 6 短时其余按 0 比较）。 */
static void expect(const char *name, bool p[KBD_ROWS][KBD_COLS],
                    uint8_t want_mod, int want_nk, const uint8_t want_keys[])
{
    uint8_t mod = 0xAA;         /* 哨兵值：确保函数真的写了它 */
    uint8_t keys[6] = {1, 1, 1, 1, 1, 1};
    int nk = kbd_translate((const bool (*)[KBD_COLS])p, &mod, keys);

    uint8_t want_full[6] = {0};
    for (int i = 0; i < want_nk; i++)
        want_full[i] = want_keys[i];

    if (mod != want_mod || nk != want_nk || memcmp(keys, want_full, sizeof(keys)) != 0) {
        fprintf(stderr, "FAIL [%s]: mod=0x%02x(want 0x%02x) nk=%d(want %d) "
                         "keys=%02x %02x %02x %02x %02x %02x\n",
                name, mod, want_mod, nk, want_nk,
                keys[0], keys[1], keys[2], keys[3], keys[4], keys[5]);
        assert(0 && "kbd_translate 用例失败");
    }
}

int main(void)
{
    int n = 0;

    /* 1. 无按键：modifier=0, nk=0 */
    {
        bool p[KBD_ROWS][KBD_COLS] = {0};
        expect("empty", p, 0x00, 0, NULL);
        n++;
    }

    /* 2. 单个小写字母 'a'（行3列2），无任何层键：mod=0, key=KEY_A。
     * 这也顺带验证字母键不取表里的 firstModifierMask（'a' 本身是 0）。 */
    {
        bool p[KBD_ROWS][KBD_COLS] = {0};
        press(p, 3, 2);
        uint8_t want[] = {KEY_A};
        expect("letter a plain", p, 0x00, 1, want);
        n++;
    }

    /* 3. ⚠️ 回归用例：底行字母 'c'（行4列4）不能因表里 firstModifierMask=
     * KEY_MOD_LSHIFT 而被误判成大写 —— 这正是 tab5_kbd_map.h 顶部注释
     * 记录的上游数据坑。若实现退化为直接取 firstModifierMask，这里会
     * 得到 mod=0x02 而不是 0x00。 */
    {
        bool p[KBD_ROWS][KBD_COLS] = {0};
        press(p, 4, 4);
        uint8_t want[] = {KEY_C};
        expect("bottom-row c plain (firstModifierMask trap)", p, 0x00, 1, want);
        n++;
    }

    /* 4. Ctrl+C：Ctrl 本身是修饰键 usage(0xE0)，应归入 modifier 位而不占
     * keycode 槽；'c' 仍是小写（不应变成 Shift+C）。这是终端 SIGINT 依赖
     * 的行为。 */
    {
        bool p[KBD_ROWS][KBD_COLS] = {0};
        press(p, R_CTRL, C_CTRL);
        press(p, 4, 4); /* c */
        uint8_t want[] = {KEY_C};
        expect("ctrl+c", p, 0x01 /* KEY_MOD_LCTRL */, 1, want);
        n++;
    }

    /* 5. ⚠️ P1 Task3 修的那个 bug 的回归用例：Aa + Ctrl + C 必须仍是
     * Ctrl+C（SIGINT），不能因为 Aa 生效把 'c' 推上第二层变成
     * Ctrl+Shift+C（那通常是「复制」，两个完全不同的绑定）。 */
    {
        bool p[KBD_ROWS][KBD_COLS] = {0};
        press(p, R_AA, C_AA);
        press(p, R_CTRL, C_CTRL);
        press(p, 4, 4); /* c */
        uint8_t want[] = {KEY_C};
        expect("aa+ctrl+c must stay ctrl+c, not ctrl+shift+c", p, 0x01, 1, want);
        n++;
    }

    /* 6. Aa + 'c'（不按 Ctrl/Alt）：应该走 second 层，即真正的大写——
     * 对字母键 second 层的 modifier 是 KEY_MOD_LSHIFT。 */
    {
        bool p[KBD_ROWS][KBD_COLS] = {0};
        press(p, R_AA, C_AA);
        press(p, 4, 4); /* c */
        uint8_t want[] = {KEY_C};
        expect("aa+c alone -> uppercase via shift", p, 0x02 /* KEY_MOD_LSHIFT */, 1, want);
        n++;
    }

    /* 7. Alt + 'c'（不按 Aa）：Aa 未生效，字母按小写处理；Alt 本身归入
     * modifier(0x04 = KEY_MOD_LALT 对应位)。 */
    {
        bool p[KBD_ROWS][KBD_COLS] = {0};
        press(p, R_ALT, C_ALT);
        press(p, 4, 4); /* c */
        uint8_t want[] = {KEY_C};
        expect("alt+c stays lowercase c + alt modifier", p, 0x04, 1, want);
        n++;
    }

    /* 8. Sym 对不敏感位置无效：数字 '1'（行0列1）所在整行
     * key_modifier_flag 全 0，按 Sym 不应改变输出。 */
    {
        bool p[KBD_ROWS][KBD_COLS] = {0};
        press(p, R_SYM, C_SYM);
        press(p, 0, 1); /* '1' */
        uint8_t want[] = {KEY_1};
        expect("sym has no effect on digit row (flag=0)", p, 0x00, 1, want);
        n++;
    }

    /* 9. Sym 对敏感位置生效：反引号键（行1列0）key_modifier_flag=1，
     * 不按 Sym 时出 ` ，按 Sym 时切到 second 层出 ~（Shift+`）。 */
    {
        bool p[KBD_ROWS][KBD_COLS] = {0};
        press(p, 1, 0); /* ` */
        uint8_t want[] = {KEY_GRAVE};
        expect("grave key, no sym -> `", p, 0x00, 1, want);
        n++;
    }
    {
        bool p[KBD_ROWS][KBD_COLS] = {0};
        press(p, R_SYM, C_SYM);
        press(p, 1, 0); /* ` under sym */
        uint8_t want[] = {KEY_GRAVE};
        expect("grave key + sym -> ~ (shift+grave)", p, 0x02, 1, want);
        n++;
    }

    /* 10. Sym/Aa 自身不上报（本地层键，不进 keys[]，也不产生 modifier）。 */
    {
        bool p[KBD_ROWS][KBD_COLS] = {0};
        press(p, R_SYM, C_SYM);
        press(p, R_AA, C_AA);
        expect("sym+aa alone -> nothing reported", p, 0x00, 0, NULL);
        n++;
    }

    /* 11. 非字母、非 0xE0~0xE7 的 "_"/"=" 键（行3列12）：key_modifier_flag=1。
     * 不按 Sym 时出 "_"（firstModifierMask=LSHIFT + KEY_MINUS）；
     * 按 Sym 时出 "="（secondModifierMask=RESERVED + KEY_EQUAL）。 */
    {
        bool p[KBD_ROWS][KBD_COLS] = {0};
        press(p, 3, 12);
        uint8_t want[] = {KEY_MINUS};
        expect("underscore/equal key, no sym -> _ (shift+minus)", p, 0x02, 1, want);
        n++;
    }
    {
        bool p[KBD_ROWS][KBD_COLS] = {0};
        press(p, R_SYM, C_SYM);
        press(p, 3, 12);
        uint8_t want[] = {KEY_EQUAL};
        expect("underscore/equal key + sym -> = (no shift)", p, 0x00, 1, want);
        n++;
    }

    /* 12. 多个纯修饰键同时按下（Ctrl+Alt，无其它键）：modifier 按位或，
     * nk=0。 */
    {
        bool p[KBD_ROWS][KBD_COLS] = {0};
        press(p, R_CTRL, C_CTRL);
        press(p, R_ALT, C_ALT);
        expect("ctrl+alt alone -> modifier OR'd, no keycodes", p, 0x05, 0, NULL);
        n++;
    }

    /* 13. 超过 6 个非修饰键同时按下：静默截断到 6，不做 ErrorRollOver。
     * 用第 3 行（tab q w e r t y ...）连续 7 个键位。 */
    {
        bool p[KBD_ROWS][KBD_COLS] = {0};
        for (int c = 1; c <= 7; c++) /* q w e r t y u */
            press(p, 2, c);
        uint8_t mod = 0xAA;
        uint8_t keys[6] = {0};
        int nk = kbd_translate((const bool (*)[KBD_COLS])p, &mod, keys);
        assert(nk == 6 && "超过 6 个按键应截断到 6");
        assert(mod == 0x00);
        n++;
    }

    /* 14. 未按任何键时 out_keys 全零（调用者不需要预先清零缓冲区）。 */
    {
        bool p[KBD_ROWS][KBD_COLS] = {0};
        uint8_t mod = 0xAA;
        uint8_t keys[6] = {9, 9, 9, 9, 9, 9};
        int nk = kbd_translate((const bool (*)[KBD_COLS])p, &mod, keys);
        assert(nk == 0);
        for (int i = 0; i < 6; i++)
            assert(keys[i] == 0);
        n++;
    }

    printf("OK (%d cases)\n", n);
    return 0;
}
