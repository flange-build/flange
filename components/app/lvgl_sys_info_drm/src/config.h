/**
 * config.h — 运行时配置持久化
 *
 * 持久化到 /var/lib/lvgl_sys_info_drm/config.json（扁平对象）。首次启动以默认值
 * 生成。wrapper 脚本以 grep 读取 autostart 标志位，故 JSON 须保持可 grep 的
 * "autostart": true/false 形式。
 */
#ifndef CONFIG_H
#define CONFIG_H

typedef struct {
    int rotation;     /* 0/90/180/270 */
    int autostart;    /* 0/1 */
    int refresh_ms;   /* 刷新间隔毫秒 */
    int brightness;   /* 背光亮度 %（0-100），-1 表示未设置/无背光 */
} app_config_t;

/** 加载配置；文件缺失/字段缺失时以默认值填充（rotation 0/autostart 1/refresh 1000/brightness -1） */
void config_load(app_config_t *cfg);

/** 保存配置到 JSON。成功返回 0。 */
int config_save(const app_config_t *cfg);

#endif /* CONFIG_H */
