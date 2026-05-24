/**
 * ui.c — 见 ui.h
 *
 * nothing-design 系统信息面板：L1 仪表盘四类卡片 ⇄ L2 分类详情。
 * 单一刷新定时器读取 sysinfo 并更新当前视图的动态控件。
 */
#include "ui.h"
#include "ui_theme.h"
#include "sysinfo.h"
#include "backlight.h"

#include <stdio.h>
#include <string.h>

/* ------------------------------------------------------------------ */
/* 全局状态                                                            */
/* ------------------------------------------------------------------ */

typedef enum { VIEW_DASH, VIEW_CPU, VIEW_MEM, VIEW_NET, VIEW_SYS, VIEW_SETTINGS } view_t;

static sysinfo_cpu_t  s_cpu;
static sysinfo_mem_t  s_mem;
static sysinfo_net_t  s_net;
static sysinfo_sys_t  s_sys;
static char           s_gpu[96];

static lvgl_port_t   *s_port;      /* 用于设置页改方向 */
static app_config_t  *s_cfg;       /* 可读写配置 */
static lv_timer_t    *s_timer;     /* 刷新定时器（改间隔用） */

static view_t   s_view = VIEW_DASH;
static void   (*s_update)(void);   /* 当前视图的刷新函数 */

/* ------------------------------------------------------------------ */
/* 格式化工具                                                          */
/* ------------------------------------------------------------------ */

static void fmt_kb(char *b, size_t n, uint64_t kb)
{
    if (kb >= (1ull << 20)) snprintf(b, n, "%.1f GB", kb / 1048576.0);
    else if (kb >= 1024)    snprintf(b, n, "%.0f MB", kb / 1024.0);
    else                    snprintf(b, n, "%llu KB", (unsigned long long)kb);
}

static void fmt_rate(char *b, size_t n, double bps)
{
    if (bps >= 1e6)      snprintf(b, n, "%.1f MB/s", bps / 1e6);
    else if (bps >= 1e3) snprintf(b, n, "%.0f KB/s", bps / 1e3);
    else                 snprintf(b, n, "%.0f B/s", bps);
}

static void fmt_uptime(char *b, size_t n, uint64_t s)
{
    uint64_t d = s / 86400, h = (s % 86400) / 3600, m = (s % 3600) / 60;
    if (d)      snprintf(b, n, "%llud %lluh %llum", (unsigned long long)d, (unsigned long long)h, (unsigned long long)m);
    else        snprintf(b, n, "%lluh %llum", (unsigned long long)h, (unsigned long long)m);
}

/* ------------------------------------------------------------------ */
/* 控件工具                                                            */
/* ------------------------------------------------------------------ */

static lv_obj_t *new_screen(void)
{
    lv_obj_t *scr = lv_obj_create(NULL);
    lv_obj_set_style_bg_color(scr, NT_COL_BG, 0);
    lv_obj_set_style_bg_opa(scr, LV_OPA_COVER, 0);
    lv_obj_set_style_text_color(scr, NT_COL_TEXT, 0);
    lv_obj_set_style_text_font(scr, g_fonts.body, 0);
    lv_obj_set_style_pad_all(scr, 24, 0);
    lv_obj_set_style_border_width(scr, 0, 0);
    return scr;
}

static lv_obj_t *mklabel(lv_obj_t *p, const char *t, const lv_font_t *f, lv_color_t c)
{
    lv_obj_t *l = lv_label_create(p);
    lv_label_set_text(l, t);
    lv_obj_set_style_text_font(l, f, 0);
    lv_obj_set_style_text_color(l, c, 0);
    return l;
}

/* label + value 行（label 左、value 右）；返回 value 标签 */
static lv_obj_t *stat_row(lv_obj_t *p, const char *label)
{
    lv_obj_t *row = lv_obj_create(p);
    lv_obj_remove_style_all(row);
    lv_obj_set_width(row, lv_pct(100));
    lv_obj_set_height(row, LV_SIZE_CONTENT);
    lv_obj_set_flex_flow(row, LV_FLEX_FLOW_ROW);
    lv_obj_set_flex_align(row, LV_FLEX_ALIGN_SPACE_BETWEEN, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);
    mklabel(row, label, g_fonts.label, NT_COL_TEXT_SEC);
    return mklabel(row, "--", g_fonts.body, NT_COL_TEXT);
}

/* 扁平进度条（nothing 风：无圆角、灰底、深色指示） */
static lv_obj_t *flat_bar(lv_obj_t *p)
{
    lv_obj_t *bar = lv_bar_create(p);
    lv_obj_set_width(bar, lv_pct(100));
    lv_obj_set_height(bar, 8);
    lv_obj_set_style_radius(bar, 0, 0);
    lv_obj_set_style_bg_color(bar, NT_COL_SURFACE, LV_PART_MAIN);
    lv_obj_set_style_bg_color(bar, NT_COL_TEXT, LV_PART_INDICATOR);
    lv_obj_set_style_radius(bar, 0, LV_PART_INDICATOR);
    lv_bar_set_range(bar, 0, 100);
    return bar;
}

static void nav_to(view_t v);  /* 前置声明 */

/* 卡片点击事件：跳转到对应详情 */
static void card_clicked(lv_event_t *e)
{
    nav_to((view_t)(intptr_t)lv_event_get_user_data(e));
}

/* 返回按钮 */
static void back_clicked(lv_event_t *e)
{
    (void)e;
    nav_to(VIEW_DASH);
}

/* L2 顶部返回栏：‹ BACK + 标题 */
static void detail_header(lv_obj_t *scr, const char *title)
{
    lv_obj_t *bar = lv_obj_create(scr);
    lv_obj_remove_style_all(bar);
    lv_obj_set_width(bar, lv_pct(100));
    lv_obj_set_height(bar, LV_SIZE_CONTENT);
    lv_obj_set_flex_flow(bar, LV_FLEX_FLOW_ROW);
    lv_obj_set_flex_align(bar, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);
    lv_obj_set_style_pad_column(bar, 16, 0);

    lv_obj_t *back = lv_button_create(bar);
    lv_obj_set_style_bg_color(back, NT_COL_SURFACE, 0);
    lv_obj_set_style_radius(back, 8, 0);
    lv_obj_t *bl = lv_label_create(back);
    lv_label_set_text(bl, LV_SYMBOL_LEFT " BACK");
    lv_obj_set_style_text_font(bl, g_fonts.label, 0);
    lv_obj_set_style_text_color(bl, NT_COL_TEXT, 0);
    lv_obj_add_event_cb(back, back_clicked, LV_EVENT_CLICKED, NULL);

    mklabel(bar, title, g_fonts.heading, NT_COL_TEXT);
}

/* ------------------------------------------------------------------ */
/* L1 仪表盘                                                           */
/* ------------------------------------------------------------------ */

static struct {
    lv_obj_t *uptime;
    lv_obj_t *cpu_val, *mem_val, *net_val, *sys_val;
} dash;

static lv_obj_t *dash_card(lv_obj_t *grid, const char *name, view_t target,
                           lv_obj_t **out_val)
{
    lv_obj_t *card = lv_obj_create(grid);
    lv_obj_set_size(card, lv_pct(48), 200);
    lv_obj_set_style_bg_color(card, NT_COL_SURFACE, 0);
    lv_obj_set_style_border_width(card, 0, 0);
    lv_obj_set_style_radius(card, 12, 0);
    lv_obj_set_style_pad_all(card, 18, 0);
    lv_obj_set_flex_flow(card, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_flex_align(card, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_START);
    lv_obj_add_flag(card, LV_OBJ_FLAG_CLICKABLE);
    lv_obj_add_event_cb(card, card_clicked, LV_EVENT_CLICKED, (void *)(intptr_t)target);

    mklabel(card, name, g_fonts.label, NT_COL_TEXT_SEC);
    lv_obj_t *spacer = lv_obj_create(card);
    lv_obj_remove_style_all(spacer);
    lv_obj_set_flex_grow(spacer, 1);
    lv_obj_set_width(spacer, lv_pct(100));
    *out_val = mklabel(card, "--", g_fonts.heading, NT_COL_TEXT);
    return card;
}

static void dash_update(void)
{
    char b[64];

    fmt_uptime(b, sizeof(b), s_sys.uptime_s);
    lv_label_set_text(dash.uptime, b);

    snprintf(b, sizeof(b), "%.0f%%", s_cpu.usage_total);
    lv_label_set_text(dash.cpu_val, b);

    float mem_pct = s_mem.mem_total_kb ?
        100.0f * (float)(s_mem.mem_total_kb - s_mem.mem_avail_kb) / (float)s_mem.mem_total_kb : 0;
    snprintf(b, sizeof(b), "%.0f%%", mem_pct);
    lv_label_set_text(dash.mem_val, b);

    /* 网络：首个 up 的网卡 IP，否则网卡数 */
    const char *ip = NULL;
    for (int i = 0; i < s_net.nifaces; i++)
        if (strcmp(s_net.ifaces[i].state, "up") == 0 && s_net.ifaces[i].ipv4[0] != '-') {
            ip = s_net.ifaces[i].ipv4; break;
        }
    if (ip) lv_label_set_text(dash.net_val, ip);
    else { snprintf(b, sizeof(b), "%d IF", s_net.nifaces); lv_label_set_text(dash.net_val, b); }

    snprintf(b, sizeof(b), "%d PROC", s_sys.nprocs);
    lv_label_set_text(dash.sys_val, b);
}

static void build_dash(void)
{
    lv_obj_t *scr = new_screen();
    lv_obj_set_flex_flow(scr, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_style_pad_row(scr, 18, 0);

    /* 顶栏：标题 + uptime（tertiary）*/
    lv_obj_t *top = lv_obj_create(scr);
    lv_obj_remove_style_all(top);
    lv_obj_set_width(top, lv_pct(100));
    lv_obj_set_height(top, LV_SIZE_CONTENT);
    lv_obj_set_flex_flow(top, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_style_pad_row(top, 4, 0);
    mklabel(top, "FLANGE \xC2\xB7 SYSTEM INFO", g_fonts.label, NT_COL_TEXT_SEC);
    dash.uptime = mklabel(top, "--", g_fonts.label, NT_COL_TEXT_DIS);

    /* 2×2 卡片网格 */
    lv_obj_t *grid = lv_obj_create(scr);
    lv_obj_remove_style_all(grid);
    lv_obj_set_width(grid, lv_pct(100));
    lv_obj_set_flex_grow(grid, 1);
    lv_obj_set_flex_flow(grid, LV_FLEX_FLOW_ROW_WRAP);
    lv_obj_set_flex_align(grid, LV_FLEX_ALIGN_SPACE_BETWEEN, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_START);
    lv_obj_set_style_pad_row(grid, 18, 0);
    lv_obj_set_style_pad_column(grid, 18, 0);

    dash_card(grid, "CPU",     VIEW_CPU, &dash.cpu_val);
    dash_card(grid, "MEMORY",  VIEW_MEM, &dash.mem_val);
    dash_card(grid, "NETWORK", VIEW_NET, &dash.net_val);
    dash_card(grid, "SYSTEM",  VIEW_SYS, &dash.sys_val);

    /* 设置入口（底边，tertiary，可点击） */
    lv_obj_t *set_entry = mklabel(scr, "SETTINGS " LV_SYMBOL_RIGHT, g_fonts.label, NT_COL_TEXT_DIS);
    lv_obj_add_flag(set_entry, LV_OBJ_FLAG_CLICKABLE);
    lv_obj_set_ext_click_area(set_entry, 20);
    lv_obj_add_event_cb(set_entry, card_clicked, LV_EVENT_CLICKED, (void *)(intptr_t)VIEW_SETTINGS);

    lv_screen_load_anim(scr, LV_SCR_LOAD_ANIM_MOVE_RIGHT, 150, 0, true);
    s_update = dash_update;
    dash_update();
}

/* ------------------------------------------------------------------ */
/* L2 CPU                                                              */
/* ------------------------------------------------------------------ */

static struct {
    lv_obj_t *hero;
    lv_obj_t *core_bar[SYSINFO_MAX_CORES];
    lv_obj_t *core_val[SYSINFO_MAX_CORES];
    int       ncore;
    lv_obj_t *temp, *freq, *load, *model;
} cpuv;

static void cpu_update(void)
{
    char b[64];
    snprintf(b, sizeof(b), "%.0f%%", s_cpu.usage_total);
    lv_label_set_text(cpuv.hero, b);

    for (int i = 0; i < cpuv.ncore; i++) {
        lv_bar_set_value(cpuv.core_bar[i], (int32_t)s_cpu.usage[i], LV_ANIM_OFF);
        snprintf(b, sizeof(b), "%.0f%% \xC2\xB7 %u MHz", s_cpu.usage[i], s_cpu.freq_khz[i] / 1000);
        lv_label_set_text(cpuv.core_val[i], b);
    }
    if (s_cpu.temp_c > 0) snprintf(b, sizeof(b), "%.1f \xC2\xB0""C", s_cpu.temp_c);
    else                  snprintf(b, sizeof(b), "--");
    lv_label_set_text(cpuv.temp, b);
    snprintf(b, sizeof(b), "%.2f %.2f %.2f", s_cpu.load[0], s_cpu.load[1], s_cpu.load[2]);
    lv_label_set_text(cpuv.load, b);
    lv_label_set_text(cpuv.model, s_cpu.model);
}

static void build_cpu(void)
{
    sysinfo_cpu_read(&s_cpu);
    lv_obj_t *scr = new_screen();
    lv_obj_set_flex_flow(scr, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_style_pad_row(scr, 14, 0);
    lv_obj_set_scroll_dir(scr, LV_DIR_VER);
    detail_header(scr, "CPU");

    /* hero 占用 */
    cpuv.hero = mklabel(scr, "--", g_fonts.display, NT_COL_TEXT);

    cpuv.ncore = s_cpu.ncpu;
    for (int i = 0; i < cpuv.ncore; i++) {
        lv_obj_t *row = lv_obj_create(scr);
        lv_obj_remove_style_all(row);
        lv_obj_set_width(row, lv_pct(100));
        lv_obj_set_height(row, LV_SIZE_CONTENT);
        lv_obj_set_flex_flow(row, LV_FLEX_FLOW_COLUMN);
        lv_obj_set_style_pad_row(row, 4, 0);
        char c[8]; snprintf(c, sizeof(c), "C%d", i);
        lv_obj_t *line = lv_obj_create(row);
        lv_obj_remove_style_all(line);
        lv_obj_set_width(line, lv_pct(100));
        lv_obj_set_height(line, LV_SIZE_CONTENT);
        lv_obj_set_flex_flow(line, LV_FLEX_FLOW_ROW);
        lv_obj_set_flex_align(line, LV_FLEX_ALIGN_SPACE_BETWEEN, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);
        mklabel(line, c, g_fonts.label, NT_COL_TEXT_SEC);
        cpuv.core_val[i] = mklabel(line, "--", g_fonts.label, NT_COL_TEXT);
        cpuv.core_bar[i] = flat_bar(row);
    }

    cpuv.temp  = stat_row(scr, "TEMP");
    cpuv.load  = stat_row(scr, "LOAD 1/5/15");
    cpuv.model = mklabel(scr, "--", g_fonts.label, NT_COL_TEXT_DIS);

    lv_screen_load_anim(scr, LV_SCR_LOAD_ANIM_MOVE_LEFT, 150, 0, true);
    s_update = cpu_update;
    cpu_update();
}

/* ------------------------------------------------------------------ */
/* L2 内存与存储                                                       */
/* ------------------------------------------------------------------ */

static struct {
    lv_obj_t *mem_bar, *mem_val;
    lv_obj_t *swap_bar, *swap_val;
    lv_obj_t *mnt_bar[SYSINFO_MAX_MOUNTS];
    lv_obj_t *mnt_val[SYSINFO_MAX_MOUNTS];
    int       nmnt;
} memv;

static void mem_update(void)
{
    char a[32], b[64];
    uint64_t used = s_mem.mem_total_kb - s_mem.mem_avail_kb;
    int pct = s_mem.mem_total_kb ? (int)(100 * used / s_mem.mem_total_kb) : 0;
    lv_bar_set_value(memv.mem_bar, pct, LV_ANIM_OFF);
    fmt_kb(a, sizeof(a), used); fmt_kb(b, sizeof(b), s_mem.mem_total_kb);
    char line[80]; snprintf(line, sizeof(line), "%s / %s", a, b);
    lv_label_set_text(memv.mem_val, line);

    uint64_t sused = s_mem.swap_total_kb - s_mem.swap_free_kb;
    int spct = s_mem.swap_total_kb ? (int)(100 * sused / s_mem.swap_total_kb) : 0;
    lv_bar_set_value(memv.swap_bar, spct, LV_ANIM_OFF);
    fmt_kb(a, sizeof(a), sused); fmt_kb(b, sizeof(b), s_mem.swap_total_kb);
    snprintf(line, sizeof(line), "%s / %s", a, b);
    lv_label_set_text(memv.swap_val, line);

    for (int i = 0; i < memv.nmnt; i++) {
        uint64_t u = s_mem.mounts[i].total_kb - s_mem.mounts[i].avail_kb;
        int p = s_mem.mounts[i].total_kb ? (int)(100 * u / s_mem.mounts[i].total_kb) : 0;
        lv_bar_set_value(memv.mnt_bar[i], p, LV_ANIM_OFF);
        fmt_kb(a, sizeof(a), u); fmt_kb(b, sizeof(b), s_mem.mounts[i].total_kb);
        snprintf(line, sizeof(line), "%s / %s", a, b);
        lv_label_set_text(memv.mnt_val[i], line);
    }
}

static void mem_block(lv_obj_t *scr, const char *name, lv_obj_t **bar, lv_obj_t **val)
{
    lv_obj_t *blk = lv_obj_create(scr);
    lv_obj_remove_style_all(blk);
    lv_obj_set_width(blk, lv_pct(100));
    lv_obj_set_height(blk, LV_SIZE_CONTENT);
    lv_obj_set_flex_flow(blk, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_style_pad_row(blk, 6, 0);
    lv_obj_t *line = lv_obj_create(blk);
    lv_obj_remove_style_all(line);
    lv_obj_set_width(line, lv_pct(100));
    lv_obj_set_height(line, LV_SIZE_CONTENT);
    lv_obj_set_flex_flow(line, LV_FLEX_FLOW_ROW);
    lv_obj_set_flex_align(line, LV_FLEX_ALIGN_SPACE_BETWEEN, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);
    mklabel(line, name, g_fonts.label, NT_COL_TEXT_SEC);
    *val = mklabel(line, "--", g_fonts.label, NT_COL_TEXT);
    *bar = flat_bar(blk);
}

static void build_mem(void)
{
    sysinfo_mem_read(&s_mem);
    lv_obj_t *scr = new_screen();
    lv_obj_set_flex_flow(scr, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_style_pad_row(scr, 16, 0);
    lv_obj_set_scroll_dir(scr, LV_DIR_VER);
    detail_header(scr, "MEMORY");

    mem_block(scr, "RAM", &memv.mem_bar, &memv.mem_val);
    mem_block(scr, "SWAP", &memv.swap_bar, &memv.swap_val);

    mklabel(scr, "STORAGE", g_fonts.label, NT_COL_TEXT_SEC);
    memv.nmnt = s_mem.nmounts;
    for (int i = 0; i < memv.nmnt; i++)
        mem_block(scr, s_mem.mounts[i].mount, &memv.mnt_bar[i], &memv.mnt_val[i]);

    lv_screen_load_anim(scr, LV_SCR_LOAD_ANIM_MOVE_LEFT, 150, 0, true);
    s_update = mem_update;
    mem_update();
}

/* ------------------------------------------------------------------ */
/* L2 网络                                                             */
/* ------------------------------------------------------------------ */

static struct {
    lv_obj_t *ip[SYSINFO_MAX_IFACES];
    lv_obj_t *rate[SYSINFO_MAX_IFACES];
    lv_obj_t *meta[SYSINFO_MAX_IFACES];
    int       n;
} netv;

static void net_update(void)
{
    char a[32], b[32], line[96];
    for (int i = 0; i < netv.n; i++) {
        sysinfo_iface_t *e = &s_net.ifaces[i];
        lv_label_set_text(netv.ip[i], e->ipv4[0] ? e->ipv4 : "--");
        fmt_rate(a, sizeof(a), e->rx_rate); fmt_rate(b, sizeof(b), e->tx_rate);
        snprintf(line, sizeof(line), LV_SYMBOL_DOWN " %s  " LV_SYMBOL_UP " %s", a, b);
        lv_label_set_text(netv.rate[i], line);
        if (e->is_wifi && e->wifi_signal)
            snprintf(line, sizeof(line), "%s \xC2\xB7 %s \xC2\xB7 %d dBm", e->state, e->mac, e->wifi_signal);
        else
            snprintf(line, sizeof(line), "%s \xC2\xB7 %s", e->state, e->mac);
        lv_label_set_text(netv.meta[i], line);
    }
}

static void build_net(void)
{
    sysinfo_net_read(&s_net);
    lv_obj_t *scr = new_screen();
    lv_obj_set_flex_flow(scr, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_style_pad_row(scr, 14, 0);
    lv_obj_set_scroll_dir(scr, LV_DIR_VER);
    detail_header(scr, "NETWORK");

    netv.n = s_net.nifaces;
    for (int i = 0; i < netv.n; i++) {
        lv_obj_t *card = lv_obj_create(scr);
        lv_obj_set_width(card, lv_pct(100));
        lv_obj_set_height(card, LV_SIZE_CONTENT);
        lv_obj_set_style_bg_color(card, NT_COL_SURFACE, 0);
        lv_obj_set_style_border_width(card, 0, 0);
        lv_obj_set_style_radius(card, 12, 0);
        lv_obj_set_style_pad_all(card, 16, 0);
        lv_obj_set_flex_flow(card, LV_FLEX_FLOW_COLUMN);
        lv_obj_set_style_pad_row(card, 4, 0);

        lv_obj_t *top = lv_obj_create(card);
        lv_obj_remove_style_all(top);
        lv_obj_set_width(top, lv_pct(100));
        lv_obj_set_height(top, LV_SIZE_CONTENT);
        lv_obj_set_flex_flow(top, LV_FLEX_FLOW_ROW);
        lv_obj_set_flex_align(top, LV_FLEX_ALIGN_SPACE_BETWEEN, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);
        char nm[28]; snprintf(nm, sizeof(nm), "%s%s", s_net.ifaces[i].name,
                              s_net.ifaces[i].is_wifi ? " " LV_SYMBOL_WIFI : "");
        mklabel(top, nm, g_fonts.heading, NT_COL_TEXT);
        netv.ip[i] = mklabel(top, "--", g_fonts.body, NT_COL_TEXT);

        netv.rate[i] = mklabel(card, "--", g_fonts.label, NT_COL_TEXT_SEC);
        netv.meta[i] = mklabel(card, "--", g_fonts.label, NT_COL_TEXT_DIS);
    }

    lv_screen_load_anim(scr, LV_SCR_LOAD_ANIM_MOVE_LEFT, 150, 0, true);
    s_update = net_update;
    net_update();
}

/* ------------------------------------------------------------------ */
/* L2 系统与硬件                                                       */
/* ------------------------------------------------------------------ */

static struct {
    lv_obj_t *kernel, *distro, *board, *gpu, *uptime, *nproc;
} sysv;

static void sys_update(void)
{
    char b[64];
    lv_label_set_text(sysv.kernel, s_sys.kernel);
    lv_label_set_text(sysv.distro, s_sys.distro);
    lv_label_set_text(sysv.board,  s_sys.board);
    lv_label_set_text(sysv.gpu,    s_sys.gpu);
    fmt_uptime(b, sizeof(b), s_sys.uptime_s);
    lv_label_set_text(sysv.uptime, b);
    snprintf(b, sizeof(b), "%d", s_sys.nprocs);
    lv_label_set_text(sysv.nproc, b);
}

static void build_sys(void)
{
    sysinfo_sys_read(&s_sys, s_gpu);
    lv_obj_t *scr = new_screen();
    lv_obj_set_flex_flow(scr, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_style_pad_row(scr, 14, 0);
    lv_obj_set_scroll_dir(scr, LV_DIR_VER);
    detail_header(scr, "SYSTEM");

    sysv.board  = stat_row(scr, "BOARD");
    sysv.distro = stat_row(scr, "DISTRO");
    sysv.kernel = stat_row(scr, "KERNEL");
    sysv.gpu    = stat_row(scr, "GPU");
    sysv.uptime = stat_row(scr, "UPTIME");
    sysv.nproc  = stat_row(scr, "PROCESSES");

    lv_screen_load_anim(scr, LV_SCR_LOAD_ANIM_MOVE_LEFT, 150, 0, true);
    s_update = sys_update;
    sys_update();
}

/* ------------------------------------------------------------------ */
/* 设置页                                                              */
/* ------------------------------------------------------------------ */

/* 段选按钮组：选中项深底浅字，其余浅底深字 */
static lv_obj_t *seg_btn(lv_obj_t *row, const char *text, int selected,
                         lv_event_cb_t cb, intptr_t ud)
{
    lv_obj_t *b = lv_button_create(row);
    lv_obj_set_height(b, 56);
    lv_obj_set_flex_grow(b, 1);
    lv_obj_set_style_radius(b, 8, 0);
    lv_obj_set_style_bg_color(b, selected ? NT_COL_TEXT : NT_COL_SURFACE, 0);
    lv_obj_t *l = lv_label_create(b);
    lv_label_set_text(l, text);
    lv_obj_set_style_text_font(l, g_fonts.label, 0);
    lv_obj_set_style_text_color(l, selected ? NT_COL_BG : NT_COL_TEXT, 0);
    lv_obj_center(l);
    lv_obj_add_event_cb(b, cb, LV_EVENT_CLICKED, (void *)ud);
    return b;
}

static lv_obj_t *seg_container(lv_obj_t *parent, const char *title)
{
    mklabel(parent, title, g_fonts.label, NT_COL_TEXT_SEC);
    lv_obj_t *row = lv_obj_create(parent);
    lv_obj_remove_style_all(row);
    lv_obj_set_width(row, lv_pct(100));
    lv_obj_set_height(row, LV_SIZE_CONTENT);
    lv_obj_set_flex_flow(row, LV_FLEX_FLOW_ROW);
    lv_obj_set_style_pad_column(row, 10, 0);
    return row;
}

static void orient_cb(lv_event_t *e)
{
    int deg = (int)(intptr_t)lv_event_get_user_data(e);
    s_cfg->rotation = deg;
    lvgl_port_set_orientation(s_port, deg);
    config_save(s_cfg);
    nav_to(VIEW_SETTINGS);   /* 重建以适配新分辨率并刷新高亮 */
}

static void refresh_cb(lv_event_t *e)
{
    int ms = (int)(intptr_t)lv_event_get_user_data(e);
    s_cfg->refresh_ms = ms;
    lv_timer_set_period(s_timer, (uint32_t)ms);
    config_save(s_cfg);
    nav_to(VIEW_SETTINGS);
}

static void autostart_cb(lv_event_t *e)
{
    lv_obj_t *sw = lv_event_get_target(e);
    s_cfg->autostart = lv_obj_has_state(sw, LV_STATE_CHECKED) ? 1 : 0;
    config_save(s_cfg);
}

static void bright_cb(lv_event_t *e)
{
    lv_obj_t *sl = lv_event_get_target(e);
    int v = (int)lv_slider_get_value(sl);
    backlight_set_percent(v);
    s_cfg->brightness = v;
    config_save(s_cfg);
}

static void build_settings(void)
{
    lv_obj_t *scr = new_screen();
    lv_obj_set_flex_flow(scr, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_style_pad_row(scr, 18, 0);
    lv_obj_set_scroll_dir(scr, LV_DIR_VER);
    detail_header(scr, "SETTINGS");

    /* 方向 */
    lv_obj_t *orow = seg_container(scr, "ORIENTATION");
    const int degs[4] = {0, 90, 180, 270};
    const char *dlbl[4] = {"0\xC2\xB0", "90\xC2\xB0", "180\xC2\xB0", "270\xC2\xB0"};
    for (int i = 0; i < 4; i++)
        seg_btn(orow, dlbl[i], s_cfg->rotation == degs[i], orient_cb, degs[i]);

    /* 刷新间隔 */
    lv_obj_t *rrow = seg_container(scr, "REFRESH");
    const int mss[4] = {500, 1000, 2000, 5000};
    const char *rlbl[4] = {"0.5s", "1s", "2s", "5s"};
    for (int i = 0; i < 4; i++)
        seg_btn(rrow, rlbl[i], s_cfg->refresh_ms == mss[i], refresh_cb, mss[i]);

    /* 开机自启 */
    lv_obj_t *arow = lv_obj_create(scr);
    lv_obj_remove_style_all(arow);
    lv_obj_set_width(arow, lv_pct(100));
    lv_obj_set_height(arow, LV_SIZE_CONTENT);
    lv_obj_set_flex_flow(arow, LV_FLEX_FLOW_ROW);
    lv_obj_set_flex_align(arow, LV_FLEX_ALIGN_SPACE_BETWEEN, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);
    mklabel(arow, "AUTOSTART", g_fonts.label, NT_COL_TEXT_SEC);
    lv_obj_t *sw = lv_switch_create(arow);
    lv_obj_set_style_bg_color(sw, NT_COL_TEXT, LV_PART_INDICATOR | LV_STATE_CHECKED);
    if (s_cfg->autostart)
        lv_obj_add_state(sw, LV_STATE_CHECKED);
    lv_obj_add_event_cb(sw, autostart_cb, LV_EVENT_VALUE_CHANGED, NULL);

    /* 背光亮度 */
    int bl = backlight_get_percent();
    mklabel(scr, "BRIGHTNESS", g_fonts.label, NT_COL_TEXT_SEC);
    if (bl >= 0) {
        lv_obj_t *sl = lv_slider_create(scr);
        lv_obj_set_width(sl, lv_pct(100));
        lv_slider_set_range(sl, 5, 100);
        lv_slider_set_value(sl, bl, LV_ANIM_OFF);
        lv_obj_set_style_bg_color(sl, NT_COL_SURFACE, LV_PART_MAIN);
        lv_obj_set_style_bg_color(sl, NT_COL_TEXT, LV_PART_INDICATOR);
        lv_obj_set_style_bg_color(sl, NT_COL_TEXT, LV_PART_KNOB);
        lv_obj_add_event_cb(sl, bright_cb, LV_EVENT_VALUE_CHANGED, NULL);
    } else {
        mklabel(scr, "N/A", g_fonts.label, NT_COL_TEXT_DIS);
    }

    lv_screen_load_anim(scr, LV_SCR_LOAD_ANIM_MOVE_LEFT, 150, 0, true);
    s_update = NULL;  /* 设置页无动态刷新内容 */
}

/* ------------------------------------------------------------------ */
/* 导航与刷新                                                          */
/* ------------------------------------------------------------------ */

static void nav_to(view_t v)
{
    s_update = NULL;  /* 转场期间暂停刷新 */
    s_view = v;
    switch (v) {
    case VIEW_DASH: build_dash(); break;
    case VIEW_CPU:  build_cpu();  break;
    case VIEW_MEM:  build_mem();  break;
    case VIEW_NET:  build_net();  break;
    case VIEW_SYS:  build_sys();  break;
    case VIEW_SETTINGS: build_settings(); break;
    }
}

static void refresh_timer(lv_timer_t *t)
{
    (void)t;
    /* 始终采集（差值类指标需持续采样）；只更新当前视图 */
    sysinfo_cpu_read(&s_cpu);
    sysinfo_mem_read(&s_mem);
    sysinfo_net_read(&s_net);
    sysinfo_sys_read(&s_sys, s_gpu);
    if (s_update)
        s_update();
}

void ui_create(lvgl_port_t *port, const char *gpu_renderer, app_config_t *cfg)
{
    s_port = port;
    s_cfg  = cfg;
    snprintf(s_gpu, sizeof(s_gpu), "%s", gpu_renderer ? gpu_renderer : "--");

    /* 首次采集（差值类需要一个基线） */
    sysinfo_cpu_read(&s_cpu);
    sysinfo_mem_read(&s_mem);
    sysinfo_net_read(&s_net);
    sysinfo_sys_read(&s_sys, s_gpu);

    nav_to(VIEW_DASH);
    s_timer = lv_timer_create(refresh_timer, (uint32_t)cfg->refresh_ms, NULL);
}
