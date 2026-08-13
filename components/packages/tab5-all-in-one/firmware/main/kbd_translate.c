#include "kbd_translate.h"
#include "tab5_kbd_map.h"

/* 四个功能键的位置，取自官方固件 updatemodifier_mask() */
#define IS_SYM(r, c) ((r) == 3 && (c) == 0)
#define IS_AA(r, c)  ((r) == 3 && (c) == 1)

/*
 * 分层规则（与官方固件 convert_to_hid() 语义一致）：
 *   - Sym(3,0) / Aa(3,1)：**本地层键，不上报**。官方表里它们的 firstKeyCode 是
 *     KEY_LEFTSHIFT，但物理键盘上标「!」的键其基础层本身就是 Shift+1 ——
 *     Sym 不是 Shift，而是切到第二层。当 Shift 上报会让符号全错。
 *   - Ctrl(4,0) / Alt(4,1)：查表得到的 usage 落在 0xE0~0xE7（HID 修饰键区间），
 *     由下面的通用规则自动归入 modifier 字节，不占 keycode 槽。
 *   - 字母键：Aa 生效**且未按住 Ctrl/Alt** → 用 second 层（大写）。
 *   - 其余键：Sym 按住且 key_modifier_flag 置位 → 用 second 层。
 */
int kbd_translate(const bool pressed[KBD_ROWS][KBD_COLS], uint8_t *out_modifier, uint8_t out_keys[6])
{
    bool sym  = pressed[3][0];
    bool ctrl = pressed[4][0];
    bool alt  = pressed[4][1];

    /*
     * Aa 的大写层必须被 Ctrl/Alt 排除（官方 convert_to_hid() 的
     * `aa_flag && ctrl_state == false && alt_state == false` 同义）。
     *
     * 为什么：按住 Aa 时再按 Ctrl+C，若不排除，'c' 会走第二层带上
     * KEY_MOD_LSHIFT，最终发出的是 **Ctrl+Shift+C** —— 终端里那通常是
     * 「复制」，而 Ctrl+C 是 SIGINT，**两个完全不同的绑定**。用户只会看到
     * 「按 Ctrl+C 中断不了程序」，极难联想到是键盘分层逻辑的问题。
     *
     * 状态取自 pressed 而非累加中的 modifier —— 后者此刻还没算完。
     * 这个条件不是冗余的，别顺手删。
     */
    bool aa = pressed[3][1] && !ctrl && !alt;

    uint8_t modifier = 0;
    uint8_t keys[6] = {0};
    int nk = 0;

    for (int r = 0; r < KBD_ROWS; r++) {
        for (int c = 0; c < KBD_COLS; c++) {
            if (!pressed[r][c]) continue;
            if (IS_SYM(r, c) || IS_AA(r, c)) continue;   /* 本地层键，不上报 */

            const key_value_t *k = &key_value_map[r][c];
            bool is_letter = (k->firstKeyCode >= KEY_A && k->firstKeyCode <= KEY_Z);
            bool use_second = is_letter ? aa : (sym && key_modifier_flag[r][c]);

            uint8_t mod, code;
            if (use_second) {
                mod  = k->secondModifierMask;
                code = k->secondKeyCode;
            } else if (is_letter) {
                /* ⚠️ 不能取表里的 firstModifierMask：上游把底排 z/x/c/v/b/n/m 的
                 * firstModifierMask 写成了 KEY_MOD_LSHIFT。官方 convert_to_hid()
                 * 的小写分支根本不读这个字段（只用运行时 modifier_mask），从而
                 * 绕开了它；照抄字段会让这一整排打出大写。这里照同样语义处理。 */
                mod  = 0;
                code = k->firstKeyCode;
            } else {
                mod  = k->firstModifierMask;
                code = k->firstKeyCode;
            }

            modifier |= mod;
            /* 0xE0~0xE7 是 HID 修饰键 usage：转成 modifier 位，不占 keycode 槽 */
            if (code >= KEY_LEFTCTRL && code <= KEY_RIGHTMETA) {
                modifier |= (uint8_t)(1u << (code - KEY_LEFTCTRL));
            } else if (code != KEY_NONE && nk < 6) {
                keys[nk++] = code;
            }
            /* 超过 6 个非修饰键时静默丢弃，**这是有意选择**，不是疏漏。
             * 标准 HID 的做法是全槽填 KEY_ERR_OVF(0x01)，但那是给真·全键盘用的；
             * 这块 70 键小键盘上同时按 7 个键属于误触而非有意输入，丢弃比让 host
             * 收到一串 ErrorRollOver 更无害。 */
        }
    }

    *out_modifier = modifier;
    for (int i = 0; i < 6; i++)
        out_keys[i] = keys[i];
    return nk;
}
