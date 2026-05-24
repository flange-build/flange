/**
 * ui.h — UI 入口
 *
 * L1 仪表盘（四类卡片 + 设置入口）⇄ L2 分类详情 ⇄ 设置页，触摸导航，定时刷新。
 */
#ifndef UI_H
#define UI_H

#include "lvgl_port.h"
#include "config.h"

/**
 * 构建 UI 并启动刷新定时器（须在 ui_theme_init 之后）。
 * port 用于设置页改方向；gpu_renderer 用于系统信息页；cfg 为可读写配置
 * （设置页修改后写回并持久化）。
 */
void ui_create(lvgl_port_t *port, const char *gpu_renderer, app_config_t *cfg);

#endif /* UI_H */
