#pragma once
/*
 * UVC 测试图案：8 根竖直色条 + 一个随帧号往返移动的白方块 + 底部灰阶带。
 *
 * 纯函数，不依赖 ESP-IDF —— 与 kbd_translate.c / touch_map.c / audio_frame.c /
 * standby_screen.c 同样的理由：画错了在 host 侧只表现为「颜色不对 / 有黑边 /
 * 方块跑出画面」，从现象反推不出来；而在宿主机上不但能断言，还能直接导 PPM 看图。
 * 见 firmware/test/test_uvc_pattern.c。
 *
 * 两个用途，一前一后：
 *  ① 宿主机渲染 → ffmpeg 压成 JPEG → uvc_test_jpeg.h，给 P4 Task5 的静态图流用；
 *  ② P4 Task6 起编进固件，在片上渲染 RGB565 喂给硬件 JPEG 编码器。
 * 于是「静态图能显示」与「片上编码能显示」之间只差编码器一个变量。
 *
 * 图案的三个元素各有诊断用途，不是好看：
 *  - **色条**：颜色顺序错 ⇒ RGB565 的字节序或 R/B 通道搞反了（这在 host 侧
 *    只表现为"颜色怪怪的"，对着标准彩条一眼可辨）；
 *  - **移动方块**：ffplay 里方块不动 ⇒ 帧根本没在更新（host 在重复显示同一帧）；
 *    方块跳跃/回退 ⇒ 丢帧；方块被撕成两半 ⇒ 帧缓冲在编码时被改写了；
 *  - **底部灰阶带**：每帧亮度加一档，截图就能读出帧号，用来核对实测帧率。
 */
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

/* 色条根数。640 = 8 × 80，每根 80 像素宽，整除，没有余数条。 */
#define UVC_PATTERN_BARS 8

/*
 * 把第 frame_no 帧渲染成紧凑排列的 RGB565（stride = w，无 padding，小端），
 * 写入 dst 的前 w*h 个 uint16_t。
 *
 * w 必须能被 UVC_PATTERN_BARS 整除，h 必须 ≥ 32（底部灰阶带占 16 行，
 * 方块 40×40 需要余下的空间）；不满足时**不写任何字节**并返回 false ——
 * 静默画半张图比不画更难查。
 * frame_no 只用于方块位置与灰阶带亮度，任意 uint32_t 都合法（自动回绕）。
 */
bool uvc_pattern_render(uint16_t *dst, int w, int h, uint32_t frame_no);

/* 方块左上角的 x 坐标（供测试断言与 host 侧核对）。纯算术，无副作用。 */
int uvc_pattern_square_x(int w, uint32_t frame_no);
