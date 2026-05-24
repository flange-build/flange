/**
 * backlight.h — 背光亮度控制（/sys/class/backlight）
 */
#ifndef BACKLIGHT_H
#define BACKLIGHT_H

/** 探测首个背光设备并读取 max_brightness。无背光返回 -1。 */
int backlight_init(void);

/** 设置亮度百分比（0-100）。无背光时 no-op。 */
void backlight_set_percent(int pct);

/** 读取当前亮度百分比（0-100）；无背光返回 -1。 */
int backlight_get_percent(void);

#endif /* BACKLIGHT_H */
