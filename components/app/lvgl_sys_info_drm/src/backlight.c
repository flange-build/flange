/**
 * backlight.c — 见 backlight.h
 */
#include "backlight.h"

#include <dirent.h>
#include <stdio.h>
#include <string.h>

#define BL_BASE "/sys/class/backlight"

static char s_dir[256];   /* 选定背光设备目录，空表示无 */
static int  s_max;

static int read_int_file(const char *path)
{
    FILE *f = fopen(path, "r");
    if (!f)
        return -1;
    int v = -1;
    if (fscanf(f, "%d", &v) != 1)
        v = -1;
    fclose(f);
    return v;
}

int backlight_init(void)
{
    s_dir[0] = '\0';
    DIR *d = opendir(BL_BASE);
    if (!d)
        return -1;
    struct dirent *de;
    while ((de = readdir(d))) {
        if (de->d_name[0] == '.')
            continue;
        snprintf(s_dir, sizeof(s_dir), "%s/%s", BL_BASE, de->d_name);
        break;
    }
    closedir(d);
    if (!s_dir[0])
        return -1;

    char p[300];
    snprintf(p, sizeof(p), "%s/max_brightness", s_dir);
    s_max = read_int_file(p);
    if (s_max <= 0) {
        s_dir[0] = '\0';
        return -1;
    }
    fprintf(stderr, "[backlight] %s (max=%d)\n", s_dir, s_max);
    return 0;
}

void backlight_set_percent(int pct)
{
    if (!s_dir[0])
        return;
    if (pct < 0) pct = 0;
    if (pct > 100) pct = 100;
    int v = pct * s_max / 100;
    if (v < 1 && pct > 0) v = 1;  /* 非零亮度至少 1，避免全黑 */

    char p[300];
    snprintf(p, sizeof(p), "%s/brightness", s_dir);
    FILE *f = fopen(p, "w");
    if (!f) {
        fprintf(stderr, "[backlight] 无法写入 %s\n", p);
        return;
    }
    fprintf(f, "%d\n", v);
    fclose(f);
}

int backlight_get_percent(void)
{
    if (!s_dir[0])
        return -1;
    char p[300];
    snprintf(p, sizeof(p), "%s/brightness", s_dir);
    int v = read_int_file(p);
    if (v < 0)
        return -1;
    return v * 100 / s_max;
}
