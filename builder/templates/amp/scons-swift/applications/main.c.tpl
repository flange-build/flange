/*
 * ${name} —— RT-Thread AMP 从核应用（Embedded Swift 功能逻辑）。
 *
 * C 侧保留 RT-Thread 入口与硬件 glue，Swift 只通过 C ABI 处理业务回复。
 */
#include <stdint.h>
#include <rtthread.h>
#include <rtdevice.h>
#include "hal_base.h"
#include "swift_bridge.h"

int main(int argc, char **argv)
{
    uint8_t reply[32];
    uint32_t reply_len;
    rt_uint32_t cpu_id = HAL_CPU_TOPOLOGY_GetCurrentCpuId();

    reply_len = swift_handle_message(RT_NULL, 0, reply, sizeof(reply));
    rt_kprintf("Hello ${name} (RT-Thread AMP + Swift)! CPU_ID(%d), swift_len=%u\n",
               cpu_id, reply_len);

    return RT_EOK;
}
