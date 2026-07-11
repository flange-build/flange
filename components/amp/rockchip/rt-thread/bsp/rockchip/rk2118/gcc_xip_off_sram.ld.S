/* SPDX-License-Identifier: BSD-3-Clause */
/*
 * Copyright (c) 2022 Rockchip Electronics Co., Ltd.
 */

#include "rtconfig.h"

#ifdef HIFI4_PROJECT_MEM_LAYOUT_FILE
#include HIFI4_PROJECT_MEM_LAYOUT_FILE
#else
#include "default_mem_layout.h"
#endif

/*--------------------- Stack / Heap Configuration ----------------------------
  <h> Stack / Heap Configuration
    <o0> Stack Size (in Bytes) <0x0-0xFFFFFFFF:8>
  </h>
  -----------------------------------------------------------------------------*/
__STACK_SIZE = 0x00000400;

/* ARMv8-M stack sealing:
   to use ARMv8-M stack sealing set __STACKSEAL_SIZE to 8 otherwise keep 0
 */
__STACKSEAL_SIZE = 0;

/* NPU memory manage by CPU0 */
MEMORY
{
#if defined(ARCH_ARM_CORTEX_SECURE)
  SRAM (rwx) : ORIGIN = 0x00200000,  LENGTH = 0x100000
#ifdef RT_USING_DDR
  DDR (rwx) : ORIGIN = 0x60000000,  LENGTH = 0x4000000
#endif
#else
#if defined(RK2118_CPU_CORE0)
  SRAM (rwx) : ORIGIN = SRAM_CPU0_RTT_BASE,  LENGTH = SRAM_CPU0_RTT_SIZE
#ifdef RT_USING_DDR
  DDR (rwx) : ORIGIN = DRAM_CPU0_RTT_BASE,  LENGTH = DRAM_CPU0_RTT_SIZE + DRAM_NPU_SIZE
#endif
#else
  #error "must select core0 or core1 in menuconfig"
#endif
#ifdef RT_USING_UNCACHE_HEAP
  MEM_U (rw) : ORIGIN = UNCACHE_HEAP_BASE, LENGTH = UNCACHE_HEAP_SIZE
#endif
#endif /* ARCH_ARM_CORTEX_SECURE */
}

SECTIONS
{
    _scode = ORIGIN(SRAM);
    .vectors :
    {
        . = ALIGN(4);
        PROVIDE(__vector_remap__ = .);
        __ISR_Vector_start__ = .;
        KEEP(*(.vectors))               /* vector table */
        __ISR_Vector_end__ = .;
        *startup_rk2118.o (.text .text.*)
        . = ALIGN(4);
    } > SRAM

    .text :
    {
        . = ALIGN(4);
        PROVIDE(_stext = .);
        KEEP(*(.text.entrypoint))       /* The entry point */
        *(SORT(.text))                        /* remaining code */
        *(SORT(.text.*))                      /* remaining code */

        *(SORT(.rodata))                      /* read-only data (constants) */
        *(SORT(.rodata*))
        *(.glue_7)
        *(.glue_7t)
        *(.gnu.linkonce.t*)

        *(COMMON)

        /* section information for finsh shell */
        . = ALIGN(16);
        __fsymtab_start = .;
        KEEP(*(FSymTab))
        __fsymtab_end = .;
        . = ALIGN(16);
        __vsymtab_start = .;
        KEEP(*(VSymTab))
        __vsymtab_end = .;
        . = ALIGN(16);

        /* section information for initial. */
        . = ALIGN(16);
        __rt_init_start = .;
        KEEP(*(SORT(.rti_fn*)))
        __rt_init_end = .;
        . = ALIGN(16);

        . = ALIGN(32);
        PROVIDE(_etext = .);
    } > SRAM

    __exidx_start = .;
    .ARM.exidx   :
    {
        *(.ARM.exidx* .gnu.linkonce.armexidx.*)

        /* This is used by the startup in order to initialize the .data secion */
        _sidata = .;
    } > SRAM
    __exidx_end = .;

    __rodata_start = .;
    .rodata   :
    {
        *(.rodata) *(.rodata.*)
    } > SRAM
    __rodata_end = .;

    .zero.table :
    {
        . = ALIGN(4);
        __zero_table_start__ = .;
        LONG (ADDR(.bss))
        LONG (SIZEOF(.bss) / 4)
        __zero_table_end__ = .;
    } > SRAM

    .copy.table :
    {
        . = ALIGN(4);
        __copy_table_start__ = .;
        LONG (LOADADDR(.data))
        LONG (ADDR(.data))
        LONG (SIZEOF(.data) / 4)
        __copy_table_end__ = .;
    } > SRAM

    .xip_flag :
    {
        . = ALIGN(4);
        __xip_flag_start__ = .;
    #if defined(RT_USING_XIP)
        LONG (0x55aaaa55)
    #else
        LONG (0x00000000)
    #endif
        __xip_flag_end__ = .;
    } > SRAM

    . = ALIGN(16);

    .ctors :
    {
        PROVIDE(__ctors_start__ = .);
        KEEP(*(SORT(.ctors.*)))
        KEEP(*(.ctors))
        /* new GCC version uses .init_array */
        KEEP (*(SORT(.init_array.*)))
        KEEP (*(.init_array))
        PROVIDE(__ctors_end__ = .);
    } > SRAM

    .dtors :
    {
        PROVIDE(__dtors_start__ = .);
        KEEP(*(SORT(.dtors.*)))
        KEEP(*(.dtors))
        PROVIDE(__dtors_end__ = .);
    } > SRAM

    . = ALIGN(32);
     _ecode = .;

    .data :
    {
        *(SORT(.data))
        *(SORT(.data.*))

        . = ALIGN(16);
    } > SRAM

    . = ALIGN(16);

    .bss (NOLOAD) :
    {
        PROVIDE(__bss_start__ = .);
        *(.bss)
        *(.bss.*)
        *(.dynbss)
        *(COMMON)
        . = ALIGN(16);
        PROVIDE(__bss_end__ = .);
    } > SRAM

#ifdef RK2118_CPU_CORE0
    .sram.heap (NOLOAD) :
    {
        . = ALIGN(32);
        PROVIDE(__sram_heap_start__ = .);
        . = ORIGIN(SRAM) + LENGTH(SRAM) - __STACK_SIZE - __STACKSEAL_SIZE;
        PROVIDE(__sram_heap_end__ = .);
        . = ALIGN(32);
    } > SRAM
#endif

   .stack (ORIGIN(SRAM) + LENGTH(SRAM) - __STACK_SIZE - __STACKSEAL_SIZE) (COPY) :
   {
        . = ALIGN(32);
        __StackLimit = .;
        . = . + __STACK_SIZE;
        __StackTop = .;
        . = ALIGN(32);
        PROVIDE(__stack = __StackTop);
        PROVIDE(_sstack = __StackLimit);
        PROVIDE(_estack = __StackTop);
    } > SRAM

#ifdef RT_USING_UNCACHE_HEAP
    .uncache.heap (NOLOAD) :
    {
        . = ALIGN(UNCACHE_HEAP_SIZE);
        PROVIDE(__uncache_heap_start__ = .);
        . = . + UNCACHE_HEAP_SIZE;
        PROVIDE(__uncache_heap_end__ = .);
        . = ALIGN(UNCACHE_HEAP_SIZE);
    } > MEM_U
#endif

#ifdef RT_USING_DDR
    .ddr.heap :
    {
        . = ALIGN(32);
        PROVIDE(__ddr_heap_start__ = .);
        . = ORIGIN(DDR) + LENGTH(DDR);
        PROVIDE(__ddr_heap_end__ = .);
        . = ALIGN(32);
    } > DDR
#else
    PROVIDE(__ddr_heap_start__ = 0);
    PROVIDE(__ddr_heap_end__ = 0);
#endif

   PROVIDE(__code_start__ = XIP_CPU0_RTT_BASE);
   PROVIDE(__code_end__ = XIP_USER_DATA_BASE - 1);
   PROVIDE(__data_start__ = ORIGIN(SRAM));
   PROVIDE(__data_end__ = ORIGIN(SRAM) + LENGTH(SRAM) - 1);
#if defined(ARCH_ARM_CORTEX_SECURE)
   PROVIDE(__device_start__ = 0x40000000);
   PROVIDE(__device_end__ = 0x40E00000 - 1);
#else
   PROVIDE(__device_start__ = 0x50000000);
   PROVIDE(__device_end__ = 0x50E00000 - 1);
#endif
#if defined(RK2118_CPU_CORE0) && defined(RT_USING_DDR)
   PROVIDE(__ext_mem_start__ = ORIGIN(DDR));
   PROVIDE(__ext_mem_end__ = ORIGIN(DDR) + LENGTH(DDR) - 1);
#endif
   PROVIDE(__large_heap_start__ = DRAM_NPU_BASE);
   PROVIDE(__large_heap_end__ = DRAM_NPU_BASE + DRAM_NPU_SIZE - 1);
#ifdef RK2118_CPU_CORE0
   PROVIDE(__spi2apb_buffer_start__ = SRAM_SPI2APB_BASE);
   PROVIDE(__spi2apb_buffer_end__ = SRAM_SPI2APB_BASE + SRAM_SPI2APB_SIZE - 1);
#endif
}
