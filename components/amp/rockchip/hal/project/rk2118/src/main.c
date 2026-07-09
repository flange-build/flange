/* SPDX-License-Identifier: BSD-3-Clause */
/*
 * Copyright (c) 2023 Rockchip Electronics Co., Ltd.
 */

#include "hal_bsp.h"
#include "hal_base.h"
//#include "unity_runner.h"

/********************* Private MACRO Definition ******************************/

/********************* Private Structure Definition **************************/

/********************* Private Variable Definition ***************************/

/********************* Private Function Definition ***************************/

/********************* Public Function Definition ****************************/

static struct UART_REG *pUart = UART0;

void _start(void);

#if defined(__GNUC__) && !defined(__ARMCC_VERSION)
int _write(int fd, char *ptr, int len);
int _write(int fd, char *ptr, int len)
{
    int i = 0;

    /*
     * write "len" of char from "ptr" to file id "fd"
     * Return number of char written.
     *
    * Only work for STDOUT, STDIN, and STDERR
     */
    if (fd > 2) {
        return -1;
    }

    while (*ptr && (i < len)) {
        if (*ptr == '\n') {
            HAL_UART_SerialOutChar(pUart, '\r');
        }
        HAL_UART_SerialOutChar(pUart, *ptr);

        i++;
        ptr++;
    }

    return i;
}
#else
int fputc(int ch, FILE *f);
int fputc(int ch, FILE *f)
{
    if (ch == '\n') {
        HAL_UART_SerialOutChar(pUart, '\r');
    }

    HAL_UART_SerialOutChar(pUart, (char)ch);

    return 0;
}
#endif

static void UART_IRQHandler(void)
{
    HAL_UART_HandleIrq(pUart);
}

#ifndef HAL_SYSTICK_MODULE_ENABLED
static void HAL_TICK_IRQHandler(void)
{
    HAL_IncTick();
    HAL_TIMER_ClrInt(TIMER4);
}
#endif

#if defined(__ARMCC_VERSION)
extern const uint32_t Image$$ER_ROM$$Base[];
extern const uint32_t Image$$ER_ROM$$Limit[];
extern const uint32_t Image$$RW_RAM$$Base[];
extern const uint32_t Image$$RW_RAM$$Limit[];
const uint32_t __flash_start__ = Image$$ER_ROM$$Base;
const uint32_t __flash_end__ = Image$$ER_ROM$$Limit;
const uint32_t __sram_start__ = Image$$RW_RAM$$Base;
const uint32_t __sram_end__ = Image$$RW_RAM$$Limit;
const uint32_t __device_start__ = 0x50000000;
const uint32_t __device_end__ = 0x50E00000 - 1;
#else
extern const uint32_t __flash_start__[];
extern const uint32_t __flash_end__[];
extern const uint32_t __sram_start__[];
extern const uint32_t __sram_end__[];
extern const uint32_t __device_start__[];
extern const uint32_t __device_end__[];
#endif
void mpu_init(void)
{
    /* text section: non shared, ro, np, exec, cachable */
    ARM_MPU_SetRegion(0, ARM_MPU_RBAR((uint32_t)__flash_start__, 0U, 0U, 1U, 0U), ARM_MPU_RLAR((uint32_t)__flash_end__, 0U));
    /* data section: non shared, rw, np, exec, cachable */
    ARM_MPU_SetRegion(1, ARM_MPU_RBAR((uint32_t)__sram_start__, 0U, 0U, 1U, 0U), ARM_MPU_RLAR((uint32_t)__sram_end__, 1U));
    /* device section: shared, rw, np, xn */
    ARM_MPU_SetRegion(2, ARM_MPU_RBAR((uint32_t)__device_start__, 1U, 0U, 1U, 1U), ARM_MPU_RLAR((uint32_t)__device_end__, 2U));

    /* cachable normal memory, ARM_MPU_ATTR_MEMORY_(NT, WB, RA, WA) */
    ARM_MPU_SetMemAttr(0, ARM_MPU_ATTR(ARM_MPU_ATTR_MEMORY_(0, 0, 1, 0), ARM_MPU_ATTR_MEMORY_(0, 0, 1, 0)));
    ARM_MPU_SetMemAttr(1, ARM_MPU_ATTR(ARM_MPU_ATTR_MEMORY_(1, 0, 1, 0), ARM_MPU_ATTR_MEMORY_(1, 0, 1, 0)));
    /* device memory */
    ARM_MPU_SetMemAttr(2, ARM_MPU_ATTR(ARM_MPU_ATTR_DEVICE, ARM_MPU_ATTR_DEVICE_nGnRnE));

    ARM_MPU_Enable(MPU_CTRL_PRIVDEFENA_Msk | MPU_CTRL_HFNMIENA_Msk);
}

struct clk_init {
    const char *name;
    uint64_t clk_id;
    uint32_t init_rate;
};

#define INIT_CLK(NAME, ID, RATE) \
    { .name = NAME, .clk_id = ID, .init_rate = RATE, }

static const struct clk_init clk_inits[] =
{
    INIT_CLK("PLL_GPLL", PLL_GPLL, 800000000),
    INIT_CLK("PLL_VPLL0", PLL_VPLL0, 983040000),
    INIT_CLK("PLL_VPLL1", PLL_VPLL1, 903168000),
    INIT_CLK("PLL_GPLL_DIV", PLL_GPLL_DIV, 200000000),
    INIT_CLK("PLL_VPLL0_DIV", PLL_VPLL0_DIV, 122880000),
    INIT_CLK("PLL_VPLL1_DIV", PLL_VPLL1_DIV, 112896000),
    INIT_CLK("CLK_DSP0_SRC", CLK_DSP0_SRC, 400000000),
    INIT_CLK("CLK_DSP0", CLK_DSP0, 700000000),
    INIT_CLK("CLK_DSP1", CLK_DSP1, 491520000),
    INIT_CLK("CLK_DSP2", CLK_DSP2, 491520000),
    INIT_CLK("ACLK_NPU", ACLK_NPU, 400000000),
    INIT_CLK("HCLK_NPU", HCLK_NPU, 150000000),
    INIT_CLK("CLK_STARSE0", CLK_STARSE0, 400000000),
    INIT_CLK("CLK_STARSE1", CLK_STARSE1, 400000000),
    INIT_CLK("ACLK_BUS", ACLK_BUS, 300000000),
    INIT_CLK("HCLK_BUS", HCLK_BUS, 150000000),
    INIT_CLK("PCLK_BUS", PCLK_BUS, 150000000),
    INIT_CLK("ACLK_HSPERI", ACLK_HSPERI, 150000000),
    INIT_CLK("ACLK_PERIB", ACLK_PERIB, 150000000),
    INIT_CLK("HCLK_PERIB", HCLK_PERIB, 150000000),
    INIT_CLK("CLK_INT_VOICE0", CLK_INT_VOICE0, 49152000),
    INIT_CLK("CLK_INT_VOICE1", CLK_INT_VOICE1, 45158400),
    INIT_CLK("CLK_INT_VOICE2", CLK_INT_VOICE2, 98304000),
    INIT_CLK("CLK_FRAC_UART0", CLK_FRAC_UART0, 128000000),
    INIT_CLK("CLK_FRAC_UART1", CLK_FRAC_UART1, 48000000),
    INIT_CLK("CLK_FRAC_VOICE0", CLK_FRAC_VOICE0, 24576000),
    INIT_CLK("CLK_FRAC_VOICE1", CLK_FRAC_VOICE1, 22579200),
    INIT_CLK("CLK_FRAC_COMMON0", CLK_FRAC_COMMON0, 12288000),
    INIT_CLK("CLK_FRAC_COMMON1", CLK_FRAC_COMMON1, 11289600),
    INIT_CLK("CLK_FRAC_COMMON2", CLK_FRAC_COMMON2, 8192000),
    INIT_CLK("PCLK_PMU", PCLK_PMU, 100000000),
    INIT_CLK("CLK_32K_FRAC", CLK_32K_FRAC, 32768),
    INIT_CLK("CLK_MAC_OUT", CLK_MAC_OUT, 50000000),
    INIT_CLK("CLK_CORE_CRYPTO", CLK_CORE_CRYPTO, 300000000),
    INIT_CLK("CLK_PKA_CRYPTO", CLK_PKA_CRYPTO, 300000000),
    /* Audio */
    INIT_CLK("MCLK_PDM", MCLK_PDM, 100000000),
    INIT_CLK("CLKOUT_PDM", CLKOUT_PDM, 3072000),
    INIT_CLK("MCLK_SPDIFTX", MCLK_SPDIFTX, 6144000),
    INIT_CLK("MCLK_OUT_SAI0", MCLK_OUT_SAI0, 12288000),
    INIT_CLK("MCLK_OUT_SAI1", MCLK_OUT_SAI1, 12288000),
    INIT_CLK("MCLK_OUT_SAI2", MCLK_OUT_SAI2, 12288000),
    INIT_CLK("MCLK_OUT_SAI3", MCLK_OUT_SAI3, 12288000),
    INIT_CLK("MCLK_OUT_SAI4", MCLK_OUT_SAI4, 12288000),
    INIT_CLK("MCLK_OUT_SAI5", MCLK_OUT_SAI5, 12288000),
    INIT_CLK("MCLK_OUT_SAI6", MCLK_OUT_SAI6, 12288000),
    INIT_CLK("MCLK_OUT_SAI7", MCLK_OUT_SAI7, 12288000),
    INIT_CLK("CLK_TSADC", CLK_TSADC, 1200000),
    INIT_CLK("CLK_TSADC_TSEN", CLK_TSADC_TSEN, 12000000),
    INIT_CLK("SCLK_SAI0", SCLK_SAI0, 12288000),
    INIT_CLK("SCLK_SAI1", SCLK_SAI1, 12288000),
    INIT_CLK("SCLK_SAI2", SCLK_SAI2, 12288000),
    INIT_CLK("SCLK_SAI3", SCLK_SAI3, 12288000),
    INIT_CLK("SCLK_SAI4", SCLK_SAI4, 12288000),
    INIT_CLK("SCLK_SAI5", SCLK_SAI5, 12288000),
    INIT_CLK("SCLK_SAI6", SCLK_SAI6, 12288000),
    INIT_CLK("SCLK_SAI7", SCLK_SAI7, 12288000),
    { /* sentinel */ },
};

void clk_init(const struct clk_init *clk_inits, bool clk_dump)
{
    const struct clk_init *clks = clk_inits;

    while (clks->name) {
        if (clks->init_rate) {
            HAL_CRU_ClkSetFreq(clks->clk_id, clks->init_rate);
        }
        if (clk_dump) {
            HAL_DBG("%s: %s = %d\n", __func__, clks->name, HAL_CRU_ClkGetFreq(clks->clk_id));
        }
        clks++;
    }
}

int main(void)
{
    struct HAL_UART_CONFIG hal_uart_config = {
        .baudRate = UART_BR_1500000,
        .dataBit = UART_DATA_8B,
        .stopBit = UART_ONE_STOPBIT,
        .parity = UART_PARITY_DISABLE,
    };

#if defined(__ARMCC_VERSION)
    if (GRF_PMU->OS_REG8 == 3) {
        g_oscRate = 24576000;
    }
#endif

    mpu_init();

    /* HAL BASE Init */
    HAL_Init();

    clk_init(clk_inits, false);

    /* System tick init */
#ifdef HAL_SYSTICK_MODULE_ENABLED
    HAL_NVIC_SetIRQHandler(SysTick_IRQn, HAL_SYSTICK_IRQHandler);
    HAL_NVIC_SetPriority(SysTick_IRQn, 0, 0);
    HAL_SetTickFreq(HAL_TICK_FREQ_1KHZ);
    HAL_SYSTICK_CLKSourceConfig(HAL_SYSTICK_CLKSRC_EXT);
    HAL_SYSTICK_Config((PLL_INPUT_OSC_RATE / 1000) - 1);
    HAL_SYSTICK_Enable();
#else
    HAL_NVIC_ConfigExtIRQ(TIMER4_IRQn, (NVIC_IRQHandler)HAL_TICK_IRQHandler, NVIC_PRIORITYGROUP_DEFAULT, NVIC_PERIPH_PRIO_DEFAULT);
    HAL_SetTickFreq(HAL_TICK_FREQ_1KHZ);
    HAL_TIMER_Init(TIMER4, TIMER_FREE_RUNNING);
    HAL_TIMER_SetCount(TIMER4, PLL_INPUT_OSC_RATE / (1000 / HAL_TICK_FREQ_1KHZ));
    HAL_TIMER_Start_IT(TIMER4);
#endif

    /* BSP Init */
    BSP_Init();

    /* UART Init */
    HAL_NVIC_SetIRQHandler(UART0_IRQn, UART_IRQHandler);
    HAL_NVIC_EnableIRQ(UART0_IRQn);

    HAL_UART_Init(&g_uart0Dev, &hal_uart_config);

    HAL_DBG("Hello RK2118: %d\n", g_oscRate);

    /* Unity Test  */
    //test_main();

    while (1) {
        ;
    }
}

void _start(void)
{
    main();
}
