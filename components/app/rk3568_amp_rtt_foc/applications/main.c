/*
 * rk3568_amp_rtt_foc —— RT-Thread AMP 从核 FOC 电机驱动（叠到 BSP 模板的 overlay）。
 *
 * 里程碑 1：开环 SVPWM 把三相无刷电机拖起来（不读编码器、不闭环）。电机驱动逻辑
 * 全在 foc.c；本文件只做 banner + 拉起驱动。用 finsh `foc` 命令在板上调参
 * （en/dis/uq/speed/dir/status）。
 *
 * 内存布局（从核链接地址、SHMEM、LINUX_RPMSG）由 flange 的 config.amp.memory 经
 * 环境变量注入，勿在此硬编。
 */
#include <rtthread.h>
#include "hal_base.h"
#include "foc.h"

int main(int argc, char **argv)
{
    rt_kprintf("rk3568_amp_rtt_foc: cpu%d up (RT-Thread AMP, open-loop SVPWM)\n",
               HAL_CPU_TOPOLOGY_GetCurrentCpuId());

    foc_start();

    return RT_EOK;
}
