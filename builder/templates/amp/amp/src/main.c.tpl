/* ${description}
 *
 * AMP 协处理器应用（裸机 HAL）。本文件由 amp 组件在 `flange build` 时 stage
 * 进 SDK 应用槽位（components/amp/rockchip/hal/project/<soc>/src/），覆盖示例
 * main.c，连同 Rockchip HAL 一起编进从核固件 amp.img。
 *
 * - 目标核：一个 Cortex-A55 切到 AArch32（如 tspi-rk3566 的 cpu3）。
 * - 从核 console：默认 UART4（与 rk3568-amp.dtsi / Linux 侧 reserved 对齐）。
 * - 与 Linux 通信：rpmsg-lite（components/amp/rockchip/hal/middleware/rpmsg-lite），
 *   共享内存 SHMEM/LINUX_RPMSG 地址由 board 配置 amp.memory 注入、三方对齐。
 * - 可用 HAL API：components/amp/rockchip/hal/lib/hal/inc。
 *
 * 提示：本文件覆盖 SDK 示例 main.c，须提供 SDK 启动流程跳转的入口 main()。
 */

#include "hal_conf.h"
#include "hal_base.h"

/* ${name} 主循环。 */
int main(void)
{
    /* TODO: 初始化外设 / rpmsg 端点。 */

    while (1) {
        /* TODO: 协处理器实时任务。 */
        HAL_CPUDelayUs(1000);
    }

    return 0;
}
