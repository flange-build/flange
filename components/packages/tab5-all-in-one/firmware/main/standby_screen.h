#pragma once
/*
 * 待机画面（"NO SIGNAL" OSD）的渲染，纯函数、零依赖。
 *
 * 只往调用方给的紧凑 RGB565 缓冲里写像素，不碰 PPA、不碰面板、不 malloc、
 * 不用任何 ESP-IDF 头 —— 上屏由 display_dsi.c 的 display_standby_screen()
 * 负责（分配 PSRAM → 本文件渲染 → display_blit）。
 *
 * 拆成独立文件而不是塞进 display_dsi.c，是为了能在宿主机上把版式渲染成 PPM
 * 肉眼验收（test/test_standby_screen.c 直接编译本文件，不是复制体），与
 * kbd_translate.c / touch_map.c 的做法一致：能在宿主机钉死的逻辑就别只能靠烧板验。
 */
#include <stdint.h>

/*
 * 整幅待机画面 → buf（GUD_W × GUD_H 个 RGB565，紧凑排列，stride = GUD_W）。
 * 等待点那一小块画成背景色（相当于 phase 0），随后由动画单独刷新。
 */
void standby_render(uint16_t *buf);

/*
 * 等待点的局部矩形，GUD 坐标系。动画只重画这一块（48×32 = 3 KB），
 * 不重画 460 KB 整屏 —— 整屏 PPA 搬运既浪费又可能挤占 USB 时序。
 */
#define STANDBY_DOTS_X      480
#define STANDBY_DOTS_Y      236
#define STANDBY_DOTS_W      48    /* 3 字符 × 8 px × 2 倍 */
#define STANDBY_DOTS_H      32    /* 16 px × 2 倍 */
#define STANDBY_DOTS_PHASES 4     /* 0..3 个点循环 */

/*
 * 把 n_dots（0..3）个点渲染进紧凑的 STANDBY_DOTS_W × STANDBY_DOTS_H 缓冲。
 * 越界的 n_dots 按 0..3 钳位。
 */
void standby_render_dots(uint16_t *buf, int n_dots);
