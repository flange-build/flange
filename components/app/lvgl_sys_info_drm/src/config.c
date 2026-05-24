/**
 * config.c — 见 config.h
 */
#include "config.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>

#define CFG_DIR  "/var/lib/lvgl_sys_info_drm"
#define CFG_PATH CFG_DIR "/config.json"

/* 在 json 中查找 "key" 后的整数值；命中返回 1 */
static int find_int(const char *json, const char *key, int *out)
{
    char pat[48];
    snprintf(pat, sizeof(pat), "\"%s\"", key);
    const char *p = strstr(json, pat);
    if (!p)
        return 0;
    p = strchr(p, ':');
    if (!p)
        return 0;
    *out = (int)strtol(p + 1, NULL, 10);
    return 1;
}

/* 在 json 中查找 "key" 后的布尔值；命中返回 1 */
static int find_bool(const char *json, const char *key, int *out)
{
    char pat[48];
    snprintf(pat, sizeof(pat), "\"%s\"", key);
    const char *p = strstr(json, pat);
    if (!p)
        return 0;
    p = strchr(p, ':');
    if (!p)
        return 0;
    while (*++p == ' ') ;
    *out = (strncmp(p, "true", 4) == 0) ? 1 : 0;
    return 1;
}

void config_load(app_config_t *cfg)
{
    /* 默认值 */
    cfg->rotation   = 0;
    cfg->autostart  = 1;
    cfg->refresh_ms = 1000;
    cfg->brightness = -1;

    FILE *f = fopen(CFG_PATH, "r");
    if (!f) {
        /* 首次启动：生成默认配置 */
        config_save(cfg);
        return;
    }
    char buf[1024];
    size_t n = fread(buf, 1, sizeof(buf) - 1, f);
    fclose(f);
    buf[n] = '\0';

    find_int(buf, "rotation", &cfg->rotation);
    find_bool(buf, "autostart", &cfg->autostart);
    find_int(buf, "refresh_ms", &cfg->refresh_ms);
    find_int(buf, "brightness", &cfg->brightness);

    /* 量化/夹紧 */
    cfg->rotation = ((cfg->rotation % 360) + 360) % 360 / 90 * 90;
    if (cfg->refresh_ms < 200) cfg->refresh_ms = 200;
}

int config_save(const app_config_t *cfg)
{
    mkdir(CFG_DIR, 0755);  /* 幂等，已存在则忽略 */

    FILE *f = fopen(CFG_PATH, "w");
    if (!f) {
        fprintf(stderr, "[config] 无法写入 %s\n", CFG_PATH);
        return -1;
    }
    fprintf(f,
        "{\n"
        "  \"rotation\": %d,\n"
        "  \"autostart\": %s,\n"
        "  \"refresh_ms\": %d,\n"
        "  \"brightness\": %d\n"
        "}\n",
        cfg->rotation,
        cfg->autostart ? "true" : "false",
        cfg->refresh_ms,
        cfg->brightness);
    fclose(f);
    return 0;
}
