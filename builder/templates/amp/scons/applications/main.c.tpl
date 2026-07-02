/*
 * ${name} —— RT-Thread AMP 从核应用（叠到 RT-Thread BSP 模板的 overlay）。
 *
 * 本文件覆盖 BSP 模板的 applications/main.c。内存布局（从核链接地址、SHMEM、
 * LINUX_RPMSG）由 flange 的 config.amp.memory 经环境变量注入，勿在此硬编。
 *
 * 若需与 Linux 通信（rpmsg）：在本 app 目录放一份 .config 片段（只列要改的
 * Kconfig，构建时合并进 BSP 的 .config 再重生成 rtconfig.h）。最省的完整 echo =
 * 打开 CONFIG_RT_USING_COMMON_TEST=y + CONFIG_RT_USING_COMMON_TEST_LINUX_RPMSG_LITE=y，
 * SDK 的 common/tests/rpmsg_test.c 会自动跑起厂商双向 echo，且该开关自带
 * MBOX0_CH3(222)→本核路由。三约束（amp-irqs 222→本核 / gicInit=0 / link-id
 * 0x10）由 BSP board/common 默认满足，无需改。
 */
#include <rtthread.h>
#include <rtdevice.h>
#include "hal_base.h"

int main(int argc, char **argv)
{
    rt_uint32_t cpu_id = HAL_CPU_TOPOLOGY_GetCurrentCpuId();

    rt_kprintf("Hello ${name} (RT-Thread AMP)! CPU_ID(%d)\n", cpu_id);

    return RT_EOK;
}
