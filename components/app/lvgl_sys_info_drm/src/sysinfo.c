/**
 * sysinfo.c — 见 sysinfo.h
 */
#include "sysinfo.h"

#include <ctype.h>
#include <dirent.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <time.h>
#include <sys/statvfs.h>
#include <ifaddrs.h>
#include <netinet/in.h>
#include <arpa/inet.h>
#include <sys/utsname.h>

/* ------------------------------------------------------------------ */
/* 通用小工具                                                          */
/* ------------------------------------------------------------------ */

/* 读取文件首行（去尾换行）；失败置空串返回 -1 */
static int read_line(const char *path, char *buf, size_t n)
{
    buf[0] = '\0';
    FILE *f = fopen(path, "r");
    if (!f)
        return -1;
    if (!fgets(buf, (int)n, f)) {
        fclose(f);
        return -1;
    }
    fclose(f);
    buf[strcspn(buf, "\n")] = '\0';
    return 0;
}

/* 读取文件中的一个无符号整数；失败返回 0 */
static uint64_t read_u64(const char *path)
{
    char buf[64];
    if (read_line(path, buf, sizeof(buf)) != 0)
        return 0;
    return strtoull(buf, NULL, 10);
}

static uint64_t now_ms(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint64_t)ts.tv_sec * 1000u + ts.tv_nsec / 1000000u;
}

/* ------------------------------------------------------------------ */
/* CPU                                                                 */
/* ------------------------------------------------------------------ */

static void cpu_read_model(char *out, size_t n)
{
    out[0] = '\0';
    FILE *f = fopen("/proc/cpuinfo", "r");
    if (!f) {
        snprintf(out, n, "--");
        return;
    }
    char line[256];
    char hardware[96] = "";
    while (fgets(line, sizeof(line), f)) {
        const char *key = NULL;
        if (strncmp(line, "model name", 10) == 0) key = line;
        else if (strncmp(line, "Hardware", 8) == 0) { strncpy(hardware, line, sizeof(hardware) - 1); continue; }
        if (key) {
            char *c = strchr(line, ':');
            if (c) {
                c++;
                while (*c == ' ') c++;
                c[strcspn(c, "\n")] = '\0';
                snprintf(out, n, "%s", c);
                fclose(f);
                return;
            }
        }
    }
    fclose(f);
    if (hardware[0]) {
        char *c = strchr(hardware, ':');
        if (c) { c++; while (*c == ' ') c++; c[strcspn(c, "\n")] = '\0'; snprintf(out, n, "%s", c); return; }
    }
    snprintf(out, n, "ARM aarch64");
}

void sysinfo_cpu_read(sysinfo_cpu_t *c)
{
    /* 占用率：/proc/stat 差值 */
    FILE *f = fopen("/proc/stat", "r");
    if (f) {
        char line[256];
        while (fgets(line, sizeof(line), f)) {
            if (strncmp(line, "cpu", 3) != 0)
                break; /* cpu* 行在文件开头连续排列 */
            unsigned long long u, ni, s, id, io = 0, irq = 0, sirq = 0, st = 0;
            int slot = -1, n = 0;
            if (line[3] == ' ') {
                sscanf(line, "cpu %llu %llu %llu %llu %llu %llu %llu %llu",
                       &u, &ni, &s, &id, &io, &irq, &sirq, &st);
                slot = 0;
            } else if (isdigit((unsigned char)line[3])) {
                sscanf(line, "cpu%d %llu %llu %llu %llu %llu %llu %llu %llu",
                       &n, &u, &ni, &s, &id, &io, &irq, &sirq, &st);
                if (n < SYSINFO_MAX_CORES) slot = n + 1;
            }
            if (slot < 0)
                continue;
            uint64_t total = u + ni + s + id + io + irq + sirq + st;
            uint64_t idle = id + io;
            if (c->_have_prev) {
                uint64_t dt = total - c->_prev_total[slot];
                uint64_t di = idle - c->_prev_idle[slot];
                float usage = dt ? 100.0f * (float)(dt - di) / (float)dt : 0.0f;
                if (slot == 0) c->usage_total = usage;
                else c->usage[slot - 1] = usage;
            }
            c->_prev_total[slot] = total;
            c->_prev_idle[slot] = idle;
        }
        fclose(f);
        c->_have_prev = 1;
    }

    cpu_read_model(c->model, sizeof(c->model));

    long nproc = sysconf(_SC_NPROCESSORS_ONLN);
    if (nproc < 1) nproc = 1;
    if (nproc > SYSINFO_MAX_CORES) nproc = SYSINFO_MAX_CORES;
    c->ncpu = (int)nproc;

    for (int i = 0; i < c->ncpu; i++) {
        char p[96];
        snprintf(p, sizeof(p), "/sys/devices/system/cpu/cpu%d/cpufreq/scaling_cur_freq", i);
        c->freq_khz[i] = (uint32_t)read_u64(p);
    }

    /* 温度：最高 thermal_zone */
    c->temp_c = 0;
    for (int z = 0; z < 20; z++) {
        char p[64];
        snprintf(p, sizeof(p), "/sys/class/thermal/thermal_zone%d/temp", z);
        if (access(p, R_OK) != 0)
            continue;
        float t = (float)read_u64(p) / 1000.0f;
        if (t > c->temp_c) c->temp_c = t;
    }

    char buf[64];
    if (read_line("/proc/loadavg", buf, sizeof(buf)) == 0)
        sscanf(buf, "%f %f %f", &c->load[0], &c->load[1], &c->load[2]);
}

/* ------------------------------------------------------------------ */
/* 内存与存储                                                          */
/* ------------------------------------------------------------------ */

void sysinfo_mem_read(sysinfo_mem_t *m)
{
    FILE *f = fopen("/proc/meminfo", "r");
    if (f) {
        char line[128];
        while (fgets(line, sizeof(line), f)) {
            uint64_t v;
            if (sscanf(line, "MemTotal: %lu kB", &v) == 1) m->mem_total_kb = v;
            else if (sscanf(line, "MemAvailable: %lu kB", &v) == 1) m->mem_avail_kb = v;
            else if (sscanf(line, "MemFree: %lu kB", &v) == 1) m->mem_free_kb = v;
            else if (sscanf(line, "SwapTotal: %lu kB", &v) == 1) m->swap_total_kb = v;
            else if (sscanf(line, "SwapFree: %lu kB", &v) == 1) m->swap_free_kb = v;
        }
        fclose(f);
    }

    /* 存储：/proc/mounts 中真实块设备挂载点 */
    m->nmounts = 0;
    f = fopen("/proc/mounts", "r");
    if (f) {
        char dev[64], mnt[128], fstype[32];
        while (m->nmounts < SYSINFO_MAX_MOUNTS &&
               fscanf(f, "%63s %127s %31s %*[^\n]\n", dev, mnt, fstype) == 3) {
            if (strncmp(dev, "/dev/", 5) != 0)
                continue;
            struct statvfs vfs;
            if (statvfs(mnt, &vfs) != 0)
                continue;
            sysinfo_mount_t *e = &m->mounts[m->nmounts];
            snprintf(e->mount, sizeof(e->mount), "%s", mnt);
            snprintf(e->dev, sizeof(e->dev), "%s", dev);
            e->total_kb = (uint64_t)vfs.f_blocks * vfs.f_frsize / 1024;
            e->avail_kb = (uint64_t)vfs.f_bavail * vfs.f_frsize / 1024;
            m->nmounts++;
        }
        fclose(f);
    }
}

/* ------------------------------------------------------------------ */
/* 网络                                                                */
/* ------------------------------------------------------------------ */

/* 从 /proc/net/wireless 取某 iface 的 level（dBm）；无则 0 */
static int wifi_level(const char *iface)
{
    FILE *f = fopen("/proc/net/wireless", "r");
    if (!f)
        return 0;
    char line[256];
    int level = 0;
    while (fgets(line, sizeof(line), f)) {
        char name[24];
        float q, l;
        if (sscanf(line, " %23[^:]: %*f %f %f", name, &q, &l) >= 3) {
            if (strcmp(name, iface) == 0) { level = (int)l; break; }
        }
    }
    fclose(f);
    return level;
}

/* 取 iface 的 IPv4（getifaddrs 已传入）*/
static void fill_ipv4(struct ifaddrs *ifa_list, const char *name, char *out, size_t n)
{
    snprintf(out, n, "--");
    for (struct ifaddrs *ifa = ifa_list; ifa; ifa = ifa->ifa_next) {
        if (ifa->ifa_addr && ifa->ifa_addr->sa_family == AF_INET &&
            strcmp(ifa->ifa_name, name) == 0) {
            struct sockaddr_in *sa = (struct sockaddr_in *)ifa->ifa_addr;
            inet_ntop(AF_INET, &sa->sin_addr, out, (socklen_t)n);
            return;
        }
    }
}

void sysinfo_net_read(sysinfo_net_t *n)
{
    sysinfo_iface_t old[SYSINFO_MAX_IFACES];
    int nold = n->nifaces;
    memcpy(old, n->ifaces, sizeof(old));
    uint64_t prev_ms = n->_prev_ms;
    int have_prev = n->_have_prev;

    n->nifaces = 0;

    struct ifaddrs *ifa_list = NULL;
    getifaddrs(&ifa_list);

    DIR *d = opendir("/sys/class/net");
    if (d) {
        struct dirent *de;
        while ((de = readdir(d)) && n->nifaces < SYSINFO_MAX_IFACES) {
            if (de->d_name[0] == '.' || strcmp(de->d_name, "lo") == 0)
                continue;
            sysinfo_iface_t *e = &n->ifaces[n->nifaces];
            memset(e, 0, sizeof(*e));
            snprintf(e->name, sizeof(e->name), "%s", de->d_name);

            char p[300];
            snprintf(p, sizeof(p), "/sys/class/net/%s/operstate", de->d_name);
            read_line(p, e->state, sizeof(e->state));
            snprintf(p, sizeof(p), "/sys/class/net/%s/address", de->d_name);
            read_line(p, e->mac, sizeof(e->mac));
            snprintf(p, sizeof(p), "/sys/class/net/%s/statistics/rx_bytes", de->d_name);
            e->rx_bytes = read_u64(p);
            snprintf(p, sizeof(p), "/sys/class/net/%s/statistics/tx_bytes", de->d_name);
            e->tx_bytes = read_u64(p);

            snprintf(p, sizeof(p), "/sys/class/net/%s/wireless", de->d_name);
            e->is_wifi = (access(p, F_OK) == 0);
            if (e->is_wifi)
                e->wifi_signal = wifi_level(de->d_name);

            fill_ipv4(ifa_list, de->d_name, e->ipv4, sizeof(e->ipv4));
            n->nifaces++;
        }
        closedir(d);
    }
    if (ifa_list)
        freeifaddrs(ifa_list);

    /* 速率：与上次快照按 name 匹配差值 */
    uint64_t cur_ms = now_ms();
    if (have_prev && cur_ms > prev_ms) {
        double dt = (double)(cur_ms - prev_ms) / 1000.0;
        for (int i = 0; i < n->nifaces; i++) {
            for (int j = 0; j < nold; j++) {
                if (strcmp(n->ifaces[i].name, old[j].name) == 0) {
                    if (n->ifaces[i].rx_bytes >= old[j].rx_bytes)
                        n->ifaces[i].rx_rate = (double)(n->ifaces[i].rx_bytes - old[j].rx_bytes) / dt;
                    if (n->ifaces[i].tx_bytes >= old[j].tx_bytes)
                        n->ifaces[i].tx_rate = (double)(n->ifaces[i].tx_bytes - old[j].tx_bytes) / dt;
                    break;
                }
            }
        }
    }
    n->_prev_ms = cur_ms;
    n->_have_prev = 1;
}

/* ------------------------------------------------------------------ */
/* 系统与硬件                                                          */
/* ------------------------------------------------------------------ */

void sysinfo_sys_read(sysinfo_sys_t *s, const char *gpu_renderer)
{
    struct utsname uts;
    if (uname(&uts) == 0)
        snprintf(s->kernel, sizeof(s->kernel), "%s %s", uts.release, uts.machine);
    else
        snprintf(s->kernel, sizeof(s->kernel), "--");

    /* 发行版：/etc/os-release PRETTY_NAME */
    snprintf(s->distro, sizeof(s->distro), "--");
    FILE *f = fopen("/etc/os-release", "r");
    if (f) {
        char line[160];
        while (fgets(line, sizeof(line), f)) {
            if (strncmp(line, "PRETTY_NAME=", 12) == 0) {
                char *v = line + 12;
                if (*v == '"') v++;
                v[strcspn(v, "\"\n")] = '\0';
                snprintf(s->distro, sizeof(s->distro), "%s", v);
                break;
            }
        }
        fclose(f);
    }

    /* board：device-tree model */
    if (read_line("/proc/device-tree/model", s->board, sizeof(s->board)) != 0 &&
        read_line("/sys/firmware/devicetree/base/model", s->board, sizeof(s->board)) != 0)
        snprintf(s->board, sizeof(s->board), "--");

    s->uptime_s = 0;
    char buf[64];
    if (read_line("/proc/uptime", buf, sizeof(buf)) == 0) {
        double up = 0;
        sscanf(buf, "%lf", &up);
        s->uptime_s = (uint64_t)up;
    }

    /* 进程数：/proc 下纯数字目录计数 */
    s->nprocs = 0;
    DIR *d = opendir("/proc");
    if (d) {
        struct dirent *de;
        while ((de = readdir(d))) {
            const char *p = de->d_name;
            int digit = 1;
            for (; *p; p++) if (!isdigit((unsigned char)*p)) { digit = 0; break; }
            if (digit && de->d_name[0]) s->nprocs++;
        }
        closedir(d);
    }

    snprintf(s->gpu, sizeof(s->gpu), "%s", (gpu_renderer && *gpu_renderer) ? gpu_renderer : "--");
}
