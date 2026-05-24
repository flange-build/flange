/**
 * sysinfo.h — 系统信息采集（CPU / 内存与存储 / 网络 / 系统与硬件）
 *
 * 读取 /proc 与 /sys。占用率与速率类指标基于两次采样差值，故对应结构体
 * 内含上次采样状态：调用方零初始化一次后重复调用 *_read 即可。
 * 缺失数据源时对应字段保持 0 / "--"，不崩溃。
 */
#ifndef SYSINFO_H
#define SYSINFO_H

#include <stdint.h>

#define SYSINFO_MAX_CORES  16
#define SYSINFO_MAX_MOUNTS 8
#define SYSINFO_MAX_IFACES 8

/* ---------- CPU ---------- */
typedef struct {
    char     model[96];
    int      ncpu;
    uint32_t freq_khz[SYSINFO_MAX_CORES];
    float    usage[SYSINFO_MAX_CORES];   /* 各核占用 % */
    float    usage_total;                /* 总占用 % */
    float    temp_c;                     /* 最高温度 ℃，0 表示无 */
    float    load[3];                    /* 1/5/15 min */

    uint64_t _prev_idle[SYSINFO_MAX_CORES + 1];
    uint64_t _prev_total[SYSINFO_MAX_CORES + 1];
    int      _have_prev;
} sysinfo_cpu_t;

/* ---------- 内存与存储 ---------- */
typedef struct {
    char     mount[64];
    char     dev[48];
    uint64_t total_kb;
    uint64_t avail_kb;
} sysinfo_mount_t;

typedef struct {
    uint64_t mem_total_kb, mem_avail_kb, mem_free_kb;
    uint64_t swap_total_kb, swap_free_kb;
    int      nmounts;
    sysinfo_mount_t mounts[SYSINFO_MAX_MOUNTS];
} sysinfo_mem_t;

/* ---------- 网络 ---------- */
typedef struct {
    char     name[24];
    char     mac[20];
    char     ipv4[20];
    char     state[12];      /* operstate */
    int      is_wifi;
    int      wifi_signal;    /* /proc/net/wireless level（dBm），0 表示 n/a */
    uint64_t rx_bytes, tx_bytes;
    double   rx_rate, tx_rate; /* bytes/s（由上次快照差值算得）*/
} sysinfo_iface_t;

typedef struct {
    int      nifaces;
    sysinfo_iface_t ifaces[SYSINFO_MAX_IFACES];
    uint64_t _prev_ms;
    int      _have_prev;
} sysinfo_net_t;

/* ---------- 系统与硬件 ---------- */
typedef struct {
    char     kernel[64];
    char     distro[96];
    char     board[96];
    char     gpu[96];
    uint64_t uptime_s;
    int      nprocs;
} sysinfo_sys_t;

void sysinfo_cpu_read(sysinfo_cpu_t *c);
void sysinfo_mem_read(sysinfo_mem_t *m);
void sysinfo_net_read(sysinfo_net_t *n);
void sysinfo_sys_read(sysinfo_sys_t *s, const char *gpu_renderer);

#endif /* SYSINFO_H */
