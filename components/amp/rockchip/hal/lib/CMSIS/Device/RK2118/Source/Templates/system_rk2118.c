/* SPDX-License-Identifier: BSD-3-Clause */
/*
 * Copyright (c) 2020-2023 Rockchip Electronics Co., Ltd.
 */

#include "soc.h"
#include "hal_base.h"

uint32_t g_oscRate = 24000000;            /* OSC Frequency */

#if defined(HAL_MCU_CORE)

#if defined(__ARM_FEATURE_CMSE) && (__ARM_FEATURE_CMSE == 3U)
#include "partition_rk2118.h"
#endif

/*----------------------------------------------------------------------------
  Define clocks
 *----------------------------------------------------------------------------*/
#define  SYSTEM_CLOCK (40000000UL)

/*----------------------------------------------------------------------------
  Exception / Interrupt Vector table
 *----------------------------------------------------------------------------*/
void VectorRemap(void);
#if defined(__ARMCC_VERSION)
/* externals from startup_rk2118.S */
extern uint32_t __Vectors[];              /* vector table ROM  */

#define VECTORTABLE_SIZE        (256)     /* size rk2118 vector table      */
#define VECTORTABLE_ALIGNMENT   (0x400ul) /* 16 Cortex + 240 Periph = 256 words */
                                          /* next power of 2 = 1024            */

/* new vector table in RAM */
__attribute__((section(".vtbl"))) uint32_t vectorTable_RAM[VECTORTABLE_SIZE] __attribute__(( aligned (VECTORTABLE_ALIGNMENT) ));

void VectorRemap(void)
{
    uint32_t i;

    for (i = 0; i < VECTORTABLE_SIZE; i++) {
        vectorTable_RAM[i] = __Vectors[i];            /* copy vector table to RAM */
    }

    SCB->VTOR = (uint32_t)&vectorTable_RAM;
}
#else
extern const uint32_t __vector_remap__[];

void VectorRemap(void)
{
    SCB->VTOR = (uint32_t)__vector_remap__;
}
#endif

/*----------------------------------------------------------------------------
  System Core Clock Variable
 *----------------------------------------------------------------------------*/
uint32_t SystemCoreClock = SYSTEM_CLOCK;  /* System Core Clock Frequency */

void CacheInit(void)
{
#if defined(HAL_ICACHE_MODULE_ENABLED)
    SCB_EnableICache();
#endif

#if defined(HAL_DCACHE_MODULE_ENABLED)
    SCB_EnableDCache();
#endif
}

/*----------------------------------------------------------------------------
  System Core Clock update function
 *----------------------------------------------------------------------------*/
void SystemCoreClockUpdate(void)
{
#if defined(RK2118_CPU_CORE0)
    SystemCoreClock = HAL_CRU_ClkGetFreq(CLK_STARSE0);
#elif defined(RK2118_CPU_CORE1)
    SystemCoreClock = HAL_CRU_ClkGetFreq(CLK_STARSE1);
#endif
}

/*----------------------------------------------------------------------------
  System initialization function
 *----------------------------------------------------------------------------*/
void SystemInit(void)
{
#if defined(HAL_DCACHE_MODULE_ENABLED)
    SCB_CleanDCache();
#endif

    if (GRF_PMU->OS_REG8 == 3)
        g_oscRate = 24576000;

#if defined(__VTOR_PRESENT) && (__VTOR_PRESENT == 1U)
    VectorRemap();
#endif

#if defined(__FPU_USED) && (__FPU_USED == 1U)
    SCB->CPACR |= ((3U << 10U * 2U) |       /* enable CP10 Full Access */
                   (3U << 11U * 2U));       /* enable CP11 Full Access */
#endif

#ifdef UNALIGNED_SUPPORT_DISABLE
    SCB->CCR |= SCB_CCR_UNALIGN_TRP_Msk;
#endif

#if defined(__ARM_FEATURE_CMSE) && (__ARM_FEATURE_CMSE == 3U)
    TZ_SAU_Setup();
#endif

    SystemCoreClock = SYSTEM_CLOCK;
}

#elif defined(HAL_DSP_CORE)
/*----------------------------------------------------------------------------
  Define clocks
 *----------------------------------------------------------------------------*/
#if defined(RK2118_DSP_CORE0)
#define  SYSTEM_CLOCK (600000000UL)
#else
#define  SYSTEM_CLOCK (500000000UL)
#endif

/*----------------------------------------------------------------------------
  System Core Clock Variable
 *----------------------------------------------------------------------------*/
uint32_t SystemCoreClock = SYSTEM_CLOCK;  /* System Core Clock Frequency */

/*----------------------------------------------------------------------------
  System Core Clock update function
 *----------------------------------------------------------------------------*/
void SystemCoreClockUpdate(void)
{
    SystemCoreClock = SYSTEM_CLOCK;
}

void SystemInit(void)
{
    if (GRF_PMU->OS_REG8 == 3)
        g_oscRate = 24576000;
}
#endif
