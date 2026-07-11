/* SPDX-License-Identifier: BSD-3-Clause */
/*
 * Copyright (c) 2025 Fuzhou Rockchip Electronics Co., Ltd
 */
#include "rtdevice.h"
#include "rtthread.h"
#include "hal_base.h"

#if defined(RT_USING_COMMON_STRESS_TEST)

#include <stdlib.h>
#include <stdio.h>
#include <unistd.h>
#include <fcntl.h>
#include <errno.h>
#include "dfs_file.h"
#include "coremark.h"
#include "memtester.h"

#define ST_REBOOT_FILE                  "/data/st_reboot"
#define ST_FLASH_FILE                   "/data/st_flash"
#define ST_FLASH_BUFFER_SIZE            (5 * 1024 * 1024)
#define ST_FLASH_POWER_LOST_SIZE        (1024 * 5)
#define ST_FLASH_REBOOT_FILE            "/data/st_flash_reboot"

static char *lost_file[4] = {"/data/flash_lost_power_0", "/data/flash_lost_power_1",
                             "/data/flash_lost_power_2", "/data/flash_lost_power_3"
                            };

extern void rt_hw_cpu_reset(void);

static void usage()
{
    rt_kprintf("stress test suite\n");
    rt_kprintf("stress_test case_name\n\n");
    rt_kprintf("example:\n");
    rt_kprintf("stress_test coremark\n");
    rt_kprintf("stress_test reboot\n");
    rt_kprintf("stress_test memtest 1024 1\n");
    rt_kprintf("    malloc 1024 Bytes ram to test 1 time\n");
    rt_kprintf("stress_test flash 10000\n");
    rt_kprintf("    flash write/read test 10000 times\n");
    rt_kprintf("stress_test flash_power_lost\n");
    rt_kprintf("stress_test cpuusage 900000\n");
    rt_kprintf("    cpu_usage runs at 900000us per second\n");
}

void handle_reboot()
{
    struct stat st;
    int cnt;
    int fd;

    if (dfs_file_stat(ST_REBOOT_FILE, &st))
        return;

    fd = open(ST_REBOOT_FILE, O_RDWR);
    if (fd < 0)
    {
        rt_kprintf("can not open %s\n", ST_REBOOT_FILE);
        return;
    }

    read(fd, &cnt, sizeof(cnt));
    cnt++;
    lseek(fd, 0, SEEK_SET);
    write(fd, &cnt, sizeof(cnt));
    fsync(fd);
    close(fd);

    rt_kprintf("find %s, the dev will reboot %d times after 10 seconds\n", ST_REBOOT_FILE, cnt);
    rt_kprintf("if you want to stop test, using: rm %s\n", ST_REBOOT_FILE);
    rt_thread_delay(rt_tick_from_millisecond(10000));
    rt_hw_cpu_reset();
}

int reboot_thread_init()
{
    static rt_thread_t reboot_thread = RT_NULL;
    reboot_thread = rt_thread_create("reboot", handle_reboot, RT_NULL, 2048, 10, 20);
    RT_ASSERT(reboot_thread);
    rt_thread_startup(reboot_thread);

    return RT_EOK;
}

void st_coremark()
{
    uint32_t count = 0;

    do
    {
        rt_kprintf("run %d: \n\n", ++count);
        coremark_main();
    }
    while (1);
}

void st_reboot()
{
    int fd;
    struct statfs st;
    int cnt = 0;

    if (dfs_statfs("/data", &st))
    {
        rt_kprintf("not find filesystem\n");
        return;
    }

    fd = open(ST_REBOOT_FILE, O_CREAT | O_RDWR);
    if (fd < 0)
    {
        rt_kprintf("can not create %s\n", ST_REBOOT_FILE);
        return;
    }

    write(fd, &cnt, sizeof(cnt));
    close(fd);

    rt_kprintf("the dev will reboot after 10 seconds\n");
    rt_thread_delay(rt_tick_from_millisecond(10000));
    rt_hw_cpu_reset();
}

void st_memtest(int ram_size, int loop)
{
    rt_uint8_t *ram_addr = RT_NULL;
    rt_uint8_t size_str[16];
    rt_uint8_t addr_str[64];
    rt_uint8_t loop_str[20];
    ram_addr = (rt_uint8_t *)rt_malloc_align(RT_ALIGN(ram_size, 16), 16);

    if (!ram_addr)
    {
        rt_kprintf("%s malloc fail\n", __FUNCTION__);
        return;
    }

    sprintf(addr_str, "%p", ram_addr);
    sprintf(size_str, "0x%x", ram_size);
    sprintf(loop_str, "%d", loop);
    char *cmd[4] = {"memtester", addr_str, size_str, loop_str};

    memtester(4, cmd);
    rt_free_align(ram_addr);
}

void st_flash(int count)
{
    char *write_data;
    char *read_data;
    int max_size;
    int active_size;
    int fd;
    int ret;

    max_size = ST_FLASH_BUFFER_SIZE;

    write_data = rt_malloc(max_size);
    if (write_data == NULL)
    {
        rt_kprintf("malloc write_data fail\n");
        return;
    }

    read_data = rt_malloc(max_size);
    if (read_data == NULL)
    {
        rt_kprintf("malloc read_data fail\n");
        rt_free(write_data);
        return;
    }

    active_size = 1;
    for (int i = 0; i < count; i++)
    {
        rt_kprintf("flash test count :%d\n", i);
        fd = open(ST_FLASH_FILE, O_RDWR | O_CREAT, 0);
        if (fd < 0)
        {
            rt_kprintf("open %s fail\n", ST_FLASH_FILE);
            rt_free(write_data);
            rt_free(read_data);
            return;
        }

        memset(write_data, 0, max_size);
        memset(read_data, 0, max_size);

        if (active_size > max_size)
            active_size = 1;

        for (int j = 0; j < active_size; j++)
        {
            srand(rt_tick_get());
            write_data[j] = random();
        }

        lseek(fd, 0, SEEK_SET);
        write(fd, write_data, active_size);
        fsync(fd);

        lseek(fd, 0, SEEK_SET);
        read(fd, read_data, active_size);

        if (rt_memcmp(write_data, read_data, active_size) != RT_EOK)
            rt_kprintf("flash test fail, file size %d\n", active_size);

        rt_kprintf("flash test file size %d bytes successful\n", active_size);
        close(fd);
        remove(ST_FLASH_FILE);

        active_size += 100;
    }

    rt_kprintf("flash test finish\n");
    rt_free(write_data);
    rt_free(read_data);
}

void st_flash_power_lost_thread(void *parameter)
{
    int fd;
    struct stat st;
    char *base_data = RT_NULL;
    char *read_data = RT_NULL;
    int lost_fd[4] = {0};
    int missing = 0;
    int i;

    if (dfs_file_stat(ST_FLASH_REBOOT_FILE, &st))
        return;

    if (dfs_file_stat(ST_REBOOT_FILE, &st))
        return;

    base_data = rt_malloc(ST_FLASH_POWER_LOST_SIZE);
    if (base_data == RT_NULL)
    {
        rt_kprintf("%s malloc fail\n", __FUNCTION__);
        return;
    }

    read_data = rt_malloc(ST_FLASH_POWER_LOST_SIZE);
    if (read_data == RT_NULL)
    {
        rt_kprintf("malloc read_data fail\n");
        rt_free(base_data);
        return;
    }

    fd = open(ST_FLASH_REBOOT_FILE, O_RDWR);
    if (fd < 0)
    {
        rt_kprintf("can not open %s\n", ST_FLASH_REBOOT_FILE);
        rt_free(base_data);
        rt_free(read_data);
        return;
    }

    lseek(fd, 0, SEEK_SET);
    read(fd, base_data, ST_FLASH_POWER_LOST_SIZE);
    close(fd);

    for (i = 0; i < 4; i++)
    {
        lost_fd[i] = open(lost_file[i], O_RDWR);
        if (lost_fd[i] < 0)
        {
            rt_kprintf("line %d can not open %s, test fail\n", __LINE__, lost_file[i]);
            missing++;
            continue;
        }

        read(lost_fd[i], read_data, ST_FLASH_POWER_LOST_SIZE);

        if (rt_memcmp(base_data, read_data, ST_FLASH_POWER_LOST_SIZE) != RT_EOK)
        {
            rt_kprintf("%s is error\n", lost_file[i]);
            missing++;
        }

        close(lost_fd[i]);

        if (missing > 1)
        {
            rt_kprintf("flash power lost fail, error file %s", lost_file[i]);
        }
    }

    while (1)
    {
        for (i = 0; i < 4; i++)
        {
            rt_kprintf("write file %s start\n", lost_file[i]);
            remove(lost_file[i]);
            lost_fd[i] = open(lost_file[i], O_CREAT | O_RDWR);
            if (lost_fd[i] < 0)
            {
                rt_kprintf("line %d can not open %s, test fail\n", __LINE__, lost_file[i]);
                continue;
            }

            write(lost_fd[i], base_data, ST_FLASH_POWER_LOST_SIZE);

            close(lost_fd[i]);

            rt_kprintf("write file %s end\n", lost_file[i]);
        }
    }
}

int flash_power_lost_thread_init()
{
    static rt_thread_t flash_power_lost_thread = RT_NULL;
    flash_power_lost_thread = rt_thread_create("flash_power_lost", st_flash_power_lost_thread, RT_NULL, 4096, 10, 20);
    RT_ASSERT(flash_power_lost_thread);
    rt_thread_startup(flash_power_lost_thread);

    return RT_EOK;
}

int st_flash_power_lost(void)
{
    int fd;
    int file_fd[4] = {0};
    struct statfs st;
    char *buf = RT_NULL;
    int i;
    int ret;

    if (dfs_statfs("/data", &st))
    {
        rt_kprintf("not find filesystem\n");
        return -1;
    }

    buf = rt_malloc(ST_FLASH_POWER_LOST_SIZE);
    if (!buf)
    {
        rt_kprintf("%s malloc fail\n", __FUNCTION__);
        return -1;
    }

    fd = open(ST_FLASH_REBOOT_FILE, O_CREAT | O_RDWR);
    if (fd < 0)
    {
        rt_kprintf("can not create %s\n", ST_FLASH_REBOOT_FILE);
        rt_free(buf);
        return -1;
    }

    for (i = 0; i < ST_FLASH_POWER_LOST_SIZE; i++)
    {
        srand(rt_tick_get());
        buf[i] = random();
    }

    write(fd, buf, ST_FLASH_POWER_LOST_SIZE);
    close(fd);

    for (i = 0; i < 4; i++)
    {
        file_fd[i] = open(lost_file[i], O_CREAT | O_RDWR);
        if (file_fd[i] < 0)
        {
            rt_kprintf("can not create %s\n", lost_file[i]);
            rt_free(buf);
            return -1;
        }

        ret = write(file_fd[i], buf, ST_FLASH_POWER_LOST_SIZE);
        close(file_fd[i]);
        if (ret < 0)
        {
            rt_kprintf("%s write fail, ret %d\n", __FUNCTION__, ret);
            rt_free(buf);
            return -1;
        }
    }

    rt_free(buf);
    return 0;
}

static void st_cpuusage_entry(void *parameter)
{
    rt_uint32_t active_us, sleep_tick;

    active_us = (rt_uint32_t)parameter;
    while (1)
    {
        HAL_CPUDelayUs(active_us);
        sleep_tick = ((1000000 - active_us) * RT_TICK_PER_SECOND) / 1000000;
        rt_thread_delay(sleep_tick);
    }
}

void st_cpuusage(rt_tick_t time)
{
    int i;
    rt_thread_t st_usage_thread;

#ifdef RT_USING_SMP
    rt_uint32_t cpu_mask;
    for (i = 0; i < RT_CPUS_NR; i++)
    {
        st_usage_thread = rt_thread_create("st_usage_test", st_cpuusage_entry, (void *)time, 1024, 20, 10);
        if (st_usage_thread != RT_NULL)
        {
            cpu_mask = i;
            rt_thread_control(st_usage_thread, RT_THREAD_CTRL_BIND_CPU, (void *)cpu_mask);
            rt_thread_startup(st_usage_thread);
        }
    }
#else
    st_usage_thread = rt_thread_create("st_usage_test", st_cpuusage_entry, (void *)time, 1024, 20, 10);
    if (st_usage_thread != RT_NULL)
        rt_thread_startup(st_usage_thread);
#endif
}

void stress_test(int argc, char **argv)
{
    if (argc < 2)
    {
        usage();
        return;
    }

    if (!strcmp(argv[1], "coremark"))
    {
        st_coremark();
    }
    else if (!strcmp(argv[1], "reboot"))
    {
        st_reboot();
    }
    else if (!strcmp(argv[1], "memtest") && argc == 4)
    {
        rt_uint32_t ram_size = atoi(argv[2]);
        rt_uint32_t loop = atoi(argv[3]);
        st_memtest(ram_size, loop);
    }
    else if (!strcmp(argv[1], "flash") && argc == 3)
    {
        int count = atoi(argv[2]);
        st_flash(count);
    }
    else if (!strcmp(argv[1], "flash_power_lost"))
    {
        if (st_flash_power_lost())
            return;

        st_reboot();

    }
    else if (!strcmp(argv[1], "cpuusage"))
    {
        int time = atoi(argv[2]);
        st_cpuusage(time);
    }
    else
    {
        usage();
    }

}

#ifdef RT_USING_FINSH
#include <finsh.h>
MSH_CMD_EXPORT(stress_test, stress test);
#endif

INIT_APP_EXPORT(reboot_thread_init);
INIT_APP_EXPORT(flash_power_lost_thread_init);

#endif
