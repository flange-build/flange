/*
 * ATK-RK3506B CPU2 控制台配置。
 *
 * RK3506 的 RM_IO27/RM_IO28 在 HAL 中分别映射为 GPIO1_C2/GPIO1_C3。
 * 这里强覆盖 BSP 的 RT_WEAK 默认值，使 pinmux 和波特率成为 app overlay 的
 * 显式契约。数据位、停止位和校验位沿用 RT_SERIAL_CONFIG_DEFAULT，即 8N1。
 */
#include <rtthread.h>

#include "drv_uart.h"
#include "hal_base.h"
#include "iomux.h"

const struct uart_board g_uart4_board =
{
    .baud_rate = UART_BR_1500000,
    .dev_flag = ROCKCHIP_UART_SUPPORT_FLAG_DEFAULT,
    .bufer_size = RT_SERIAL_RB_BUFSZ,
    .name = "uart4",
};

void uart4_iomux_config(void)
{
    /* GPIO1_C2/C3 对应 Linux DTS 的 RM_IO27_TX/RM_IO28_RX。 */
    HAL_PINCTRL_SetRMIO(GPIO_BANK1, GPIO_PIN_C2, RMIO_UART4_TX);
    HAL_PINCTRL_SetRMIO(GPIO_BANK1, GPIO_PIN_C3, RMIO_UART4_RX);
}
