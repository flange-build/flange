#pragma once
#include "esp_err.h"
#include <stdint.h>

esp_err_t display_init(void);
/* 把一块 GUD 坐标系（640×360 横向）内的 RGB565 矩形送上屏。
 * pixels 为紧凑排列的 w*h 个 RGB565 像素，无 stride。 */
void display_blit(int x, int y, int w, int h, const void *pixels);

/*
 * 在面板上画一个 w×h 的实心方块（**面板原生坐标系** 720×1280 竖向，
 * 不是 display_blit() 用的 GUD 坐标系）。
 *
 * 仅用于无串口时的现场诊断：把固件内部状态直接显示出来。本机关掉了
 * USB-Serial/JTAG（TinyUSB 要占那条 PHY），UART0 在 M5-Bus 排针上，
 * 现场没有串口可看，ESP_LOG* 等于不存在。
 *
 * 超出面板范围的部分自动截断；display_init() 之前调用是安全的空操作。
 * 内部会做整帧 cache 回写，开销不小，不要放进任何常态路径。
 */
void display_debug_marker(uint16_t panel_x, uint16_t panel_y,
                          uint16_t w, uint16_t h, uint16_t rgb565);

/* 面板自检：整帧显示四象限色块（左上红/右上绿/左下蓝/右下白）加中心黑方块，
 * 用于确认面板时序、颜色通道与 PPA 缩放旋转的落点。
 * 亦作为「显示链路还活着」的基准信号：host 的 GUD 帧一送上来就会覆盖它。 */
void display_test_pattern(void);
