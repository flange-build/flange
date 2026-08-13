#pragma once
/*
 * bring-up 屏上状态面板的版式与渲染，纯函数、零依赖（只用 standby_screen.h
 * 导出的绘制原语与 tab5_pins.h 的 GUD_W/GUD_H）。上屏由 audio_panel.c 负责。
 *
 * 拆成独立文件的理由与 standby_screen.c 相同：电平条的长度换算、数字格式化、
 * 越界钳位都能在宿主机上钉死，而这些错在实机上只表现为"条画得不对"，
 * 从现象几乎反推不出来。见 test/test_audio_panel_render.c。
 */
#include <stdint.h>

/* ── 版式（GUD 640×360 横向坐标系；上屏时 PPA 会 2× 放大并旋转 90°）──
 *
 * 面板放在屏幕**最下方**，理由是必须避开待机画面的等待点动画（y 236..268）——
 * 两者都在周期性重画，重叠就会互相覆盖，表现为文字闪烁或缺一块。
 * audio_panel_render.c 里那条 _Static_assert 把这个约束钉死。
 */
#define AUDIO_PANEL_X            64
#define AUDIO_PANEL_Y            276
#define AUDIO_PANEL_STATUS_W     512
#define AUDIO_PANEL_STATUS_LINES 3
#define AUDIO_PANEL_STATUS_H     (AUDIO_PANEL_STATUS_LINES * 16)   /* 48 */
#define AUDIO_PANEL_COLS         (AUDIO_PANEL_STATUS_W / 8)        /* 64 列，1× 字号 */

#define AUDIO_PANEL_METER_X      AUDIO_PANEL_X
#define AUDIO_PANEL_METER_Y      (AUDIO_PANEL_Y + AUDIO_PANEL_STATUS_H + 4)  /* 328 */
#define AUDIO_PANEL_METER_W      256
#define AUDIO_PANEL_METER_H      32     /* 两行 × 16 px：L 一行、R 一行 */
#define AUDIO_PANEL_BAR_W        140    /* 条的最大长度，像素 */

/* 电平条满刻度。与 audio_frame_peak() 的返回域一致（0..32768），
 * 取 32768 而不是 32767 是因为 INT16_MIN 的绝对值就是 32768。 */
#define AUDIO_PANEL_PEAK_FULL    32768

/*
 * 状态区渲染：n 行文本 → 紧凑的 AUDIO_PANEL_STATUS_W × AUDIO_PANEL_STATUS_H 缓冲。
 * lines[i] 为 NULL 或空串时该行画成背景色。超过 AUDIO_PANEL_COLS 的部分被截断
 * （截断而不是换行：面板是定高的，换行会把后面的行挤出画）。
 * n 超过 AUDIO_PANEL_STATUS_LINES 时按上限截断。
 */
void audio_panel_render_status(uint16_t *buf, const char *const *lines, int n);

/*
 * 电平条渲染：两路峰值 → 紧凑的 AUDIO_PANEL_METER_W × AUDIO_PANEL_METER_H 缓冲。
 * 每行 = 标签("L"/"R") + 条 + 5 位十进制峰值。
 * peak 超过 AUDIO_PANEL_PEAK_FULL 时条按满格画（钳位，不是绕回）。
 */
void audio_panel_render_meter(uint16_t *buf, uint16_t peak_l, uint16_t peak_r);

/*
 * 峰值 → 条长度（像素）。单独导出是为了能在宿主机上单独钉死这条换算 ——
 * 它是整块面板里唯一一处算术，也是唯一一处会被"顺手优化"改错的地方。
 * 用 uint32_t 中间量：32768 × 140 = 4,587,520，早已超出 uint16_t。
 */
uint16_t audio_panel_bar_len(uint16_t peak);
