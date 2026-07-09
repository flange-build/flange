/* SPDX-License-Identifier: BSD-3-Clause */
/*
 * Copyright (c) 2022 Rockchip Electronics Co., Ltd.
 */

#include "hal_base.h"

#define USR_MODE    0x00000010
#define SVC_MODE    0x00000013
#define FIQ_MODE    0x00000011
#define IRQ_MODE    0x00000012
#define MON_MODE    0x00000016
#define ABT_MODE    0x00000017
#define HYP_MODE    0x0000001a
#define UND_MODE    0x0000001b
#define SYSTEM_MODE 0x0000001f
#define MODE_MASK   0x0000001f

#ifdef HAL_AP_CORE

/*----------------------------------------------------------------------------
  Internal References
 *----------------------------------------------------------------------------*/
void Vectors                   (void) __attribute__ ((section("RESET")));
void Reset_Handler             (void);
void Default_Handler           (void);
void IRQ_Handler               (void);
void IRQ_HardIrqHandler        (void);
void IRQ_HardIrqPreemptHandler (void);
void DAbt_Handler(void);
void Dump_Regs(uint32_t *regs, uint32_t mode);

extern uint32_t Image$$SVC_STACK$$ZI$$Limit[];
extern uint32_t _etext[];
extern uint32_t _stext[];

#define Image_SVC_STACK_ZI_Limit ((uint32_t)&Image$$SVC_STACK$$ZI$$Limit)
#define ETEXT                    ((uint32_t)&_etext)
#define STEXT                    ((uint32_t)&_stext)

/*----------------------------------------------------------------------------
  Exception / Interrupt Handler
 *----------------------------------------------------------------------------*/
void Undef_Handler (void) __attribute__ ((weak, alias("Default_Handler")));
void SVC_Handler   (void) __attribute__ ((weak, alias("Default_Handler")));
void PAbt_Handler  (void) __attribute__ ((weak, alias("Default_Handler")));
void DAbt_Handler  (void) __attribute__ ((weak, alias("Default_Handler")));
void FIQ_Handler   (void) __attribute__ ((weak, alias("Default_Handler")));

#ifndef HAL_GIC_MODULE_ENABLED
void IRQ_Handler   (void) __attribute__ ((weak, alias("Default_Handler")));
#else
#ifdef HAL_GIC_PREEMPT_FEATURE_ENABLED
void IRQ_HardIrqPreemptHandler(void)
{
    uint32_t irqn;

    irqn = HAL_GIC_GetActiveIRQ();

    if ((irqn >= 1020 && irqn <= 1023))
        return;

    HAL_GIC_TouchICC();

#ifdef HAL_GPIO_IRQ_GROUP_MODULE_ENABLED
    HAL_GPIO_IRQ_GROUP_DispatchGIRQs(irqn);
#endif

    __enable_irq();

    HAL_IRQ_HANDLER_IRQHandler(irqn);

    __disable_irq();

    HAL_GIC_EndOfInterrupt(irqn);
}
#else
void IRQ_HardIrqHandler(void)
{
    uint32_t irqn;

    irqn = HAL_GIC_GetActiveIRQ();

    if (irqn >= HAL_GIC_IRQ_LINE_COUNT)
        return;

    if (irqn <= 15)
        HAL_GIC_EndOfInterrupt(irqn);

    HAL_IRQ_HANDLER_IRQHandler(irqn);

    if (irqn > 15)
        HAL_GIC_EndOfInterrupt(irqn);
}
#endif

#if defined(__GNUC__) && ! defined(__ARMCC_VERSION)
#pragma GCC push_options
#pragma GCC optimize ("-fomit-frame-pointer")
#elif defined(__ARMCC_VERSION)
#pragma push
#pragma -fomit-frame-pointer
#endif

#ifdef __aarch64__
void IRQ_Handler(void)
{
#ifdef HAL_GIC_PREEMPT_FEATURE_ENABLED
    __ASM volatile (
        "stp    x0, x1, [sp, #-16]!           \n" //save x0~x30
        "stp    x2, x3, [sp, #-16]!           \n"
        "stp    x4, x5, [sp, #-16]!           \n"
        "stp    x6, x7, [sp, #-16]!           \n"
        "stp    x8, x9, [sp, #-16]!           \n"
        "stp    x10, x11, [sp, #-16]!         \n"
        "stp    x12, x13, [sp, #-16]!         \n"
        "stp    x14, x15, [sp, #-16]!         \n"
        "stp    x16, x17, [sp, #-16]!         \n"
        "stp    x18, x19, [sp, #-16]!         \n"
        "stp    x20, x21, [sp, #-16]!         \n"
        "stp    x22, x23, [sp, #-16]!         \n"
        "stp    x24, x25, [sp, #-16]!         \n"
        "stp    x26, x27, [sp, #-16]!         \n"
        "stp    x28, x29, [sp, #-16]!         \n"
        "stp    x30, xzr, [sp, #-16]!         \n"
        "mrs    x0, elr_el1                   \n"
        "mrs    x1, spsr_el1                  \n"
        "stp    x0, x1, [sp, #-16]!           \n" //save elr_el1,spsr_el1
#if (__FPU_USED == 1)
        "mrs    x28, fpcr                     \n" //save fpu
        "mrs    x29, fpsr                     \n"
        "stp    x28, x29, [sp, #-16]!         \n"
        "str    q0, [sp, #-16]!               \n" //save q0~q15
        "str    q1, [sp, #-16]!               \n"
        "str    q2, [sp, #-16]!               \n"
        "str    q3, [sp, #-16]!               \n"
        "str    q4, [sp, #-16]!               \n"
        "str    q5, [sp, #-16]!               \n"
        "str    q6, [sp, #-16]!               \n"
        "str    q7, [sp, #-16]!               \n"
        "str    q8, [sp, #-16]!               \n"
        "str    q9, [sp, #-16]!               \n"
        "str    q10, [sp, #-16]!              \n"
        "str    q11, [sp, #-16]!              \n"
        "str    q12, [sp, #-16]!              \n"
        "str    q13, [sp, #-16]!              \n"
        "str    q14, [sp, #-16]!              \n"
        "str    q15, [sp, #-16]!              \n"
#endif
        "bl     IRQ_HardIrqPreemptHandler     \n"
#if (__FPU_USED == 1)
        "ldr    q15, [sp], #16                \n" //restore q0~q15
        "ldr    q14, [sp], #16                \n"
        "ldr    q13, [sp], #16                \n"
        "ldr    q12, [sp], #16                \n"
        "ldr    q11, [sp], #16                \n"
        "ldr    q10, [sp], #16                \n"
        "ldr    q9, [sp], #16                 \n"
        "ldr    q8, [sp], #16                 \n"
        "ldr    q7, [sp], #16                 \n"
        "ldr    q6, [sp], #16                 \n"
        "ldr    q5, [sp], #16                 \n"
        "ldr    q4, [sp], #16                 \n"
        "ldr    q3, [sp], #16                 \n"
        "ldr    q2, [sp], #16                 \n"
        "ldr    q1, [sp], #16                 \n"
        "ldr    q0, [sp], #16                 \n"
        "ldp    x28, x29, [sp], #16           \n" //restore fpu
        "msr    fpcr, x28                     \n"
        "msr    fpsr, x29                     \n"
#endif
        "ldp    x0, x1, [sp], #16             \n" //restore elr_el1,spsr_el1
        "msr    elr_el1, x0                   \n"
        "msr    spsr_el1, x1                  \n"
        "ldp    x30, xzr, [sp], #16           \n"
        "ldp    x28, x29, [sp], #16           \n"
        "ldp    x26, x27, [sp], #16           \n"
        "ldp    x24, x25, [sp], #16           \n"
        "ldp    x22, x23, [sp], #16           \n"
        "ldp    x20, x21, [sp], #16           \n"
        "ldp    x18, x19, [sp], #16           \n"
        "ldp    x16, x17, [sp], #16           \n"
        "ldp    x14, x15, [sp], #16           \n"
        "ldp    x12, x13, [sp], #16           \n"
        "ldp    x10, x11, [sp], #16           \n"
        "ldp    x8, x9, [sp], #16             \n"
        "ldp    x6, x7, [sp], #16             \n"
        "ldp    x4, x5, [sp], #16             \n"
        "ldp    x2, x3, [sp], #16             \n"
        "ldp    x0, x1, [sp], #16             \n"
        "eret                                 \n"
        );
#else
    __ASM volatile (
        "stp     x0, x1, [sp, #-16]!                      \n" // save x0~x30
        "stp     x2, x3, [sp, #-16]!                      \n"
        "stp     x4, x5, [sp, #-16]!                      \n"
        "stp     x6, x7, [sp, #-16]!                      \n"
        "stp     x8, x9, [sp, #-16]!                      \n"
        "stp     x10, x11, [sp, #-16]!                    \n"
        "stp     x12, x13, [sp, #-16]!                    \n"
        "stp     x14, x15, [sp, #-16]!                    \n"
        "stp     x16, x17, [sp, #-16]!                    \n"
        "stp     x18, x19, [sp, #-16]!                    \n"
        "stp     x20, x21, [sp, #-16]!                    \n"
        "stp     x22, x23, [sp, #-16]!                    \n"
        "stp     x24, x25, [sp, #-16]!                    \n"
        "stp     x26, x27, [sp, #-16]!                    \n"
        "stp     x28, x29, [sp, #-16]!                    \n"
        "stp     x30, xzr, [sp, #-16]!                    \n"
        "bl      IRQ_HardIrqHandler                       \n"
        "ldp     x30, xzr, [sp], #16                      \n" // restore x0~x30
        "ldp     x28, x29, [sp], #16                      \n"
        "ldp     x26, x27, [sp], #16                      \n"
        "ldp     x24, x25, [sp], #16                      \n"
        "ldp     x22, x23, [sp], #16                      \n"
        "ldp     x20, x21, [sp], #16                      \n"
        "ldp     x18, x19, [sp], #16                      \n"
        "ldp     x16, x17, [sp], #16                      \n"
        "ldp     x14, x15, [sp], #16                      \n"
        "ldp     x12, x13, [sp], #16                      \n"
        "ldp     x10, x11, [sp], #16                      \n"
        "ldp     x8, x9, [sp], #16                        \n"
        "ldp     x6, x7, [sp], #16                        \n"
        "ldp     x4, x5, [sp], #16                        \n"
        "ldp     x2, x3, [sp], #16                        \n"
        "ldp     x0, x1, [sp], #16                        \n"
        "eret                                             \n"
        );
#endif /* HAL_GIC_PREEMPT_FEATURE_ENABLED */
}
#else
HAL_VISIBLE void IRQ_Handler(void)
{
#ifdef HAL_GIC_PREEMPT_FEATURE_ENABLED
    __ASM volatile (
    "sub    lr, lr, #4                                \n"
    "stm    sp, {r0, lr}                              \n" // save r0, lr, spsr
    "mrs    lr, SPSR                                  \n"
    "str    lr, [sp, #8]                              \n"
    "mrs    r0, CPSR                                  \n"
    "eor    r0, r0, #1                                \n"
    "msr    SPSR_fsxc, r0                             \n" // set spsr to svc mode
    "mov    r0, sp                                    \n"
    "ldr    lr, =hw_irq                               \n"
    "movs   pc, lr                                    \n" // switch to svc mode
    "hw_irq:                                          \n"
    "sub    sp, sp, #72                               \n"
    "stmia  sp, {r1 - r12}                            \n" // save the cpu context
    "ldmia  r0, {r3 - r5}                             \n"
    "add    r7, sp, #48                               \n"
    "add    r2, sp, #72                               \n"
    "str    r3, [sp, #-4]!                            \n"
    "mov    r3, lr                                    \n"
    "stmia  r7, {r2 - r5}                             \n"
    "vmrs   r8, fpexc                                 \n"
    "tst    r8, #(1<<30)                              \n"
    "beq    1f                                        \n"
    "vstmdb sp!, {d0-d15}                             \n" // save fpu context
    "vstmdb sp!, {d16-d31}                            \n"
    "vmrs   r9, fpscr                                 \n"
    "stmfd  sp!, {r9}                                 \n"
    "1:                                               \n"
    "stmfd  sp!, {r8}                                 \n"
    "mov    r8,  sp                                   \n"
    "bic    sp,  sp, #(1<<2)                          \n"
    "bl     IRQ_HardIrqPreemptHandler                 \n"
    "mov    sp,  r8                                   \n"
    "ldmfd  sp!, {r8}                                 \n"
    "vmsr   fpexc, r8                                 \n"
    "tst    r8, #(1<<30)                              \n"
    "beq    1f                                        \n"
    "ldmfd  sp!, {r9}                                 \n"
    "vmsr   fpscr, r9                                 \n"
    "vldmia sp!, {d16-d31}                            \n"
    "vldmia sp!, {d0-d15}                             \n"
    "1:                                               \n"
    "cpsid  i                                         \n"
    "isb    \n"
    "IRQ_HandlerEnd:                                  \n"
    "msr    spsr_cxsf, r5                             \n" // restore the spsr
    "ldmia  sp, {r0 - pc}^                            \n" // restore the CPU context then exit irq handler
    );
#else
    __ASM volatile (
    "stmfd  sp!, {r0-r12,lr}                          \n" // save the CPU context
    "bl     IRQ_HardIrqHandler                        \n"
    "ldmfd  sp!, {r0-r12,lr}                          \n" // restore the CPU context
    "subs   pc,  lr, #4                               \n"
    );
#endif /* HAL_GIC_PREEMPT_FEATURE_ENABLED */
}
#endif
#endif /* HAL_GIC_MODULE_ENABLED */

#ifdef __aarch64__
#define vector_table_align .align 11    /* Vector tables must be placed at a 2KB-aligned address */
#define vector_entry_align .align 7     /* Each entry is 128B */

void Sync_Handler(void) __attribute__ ((weak, alias("Default_Handler")));
void SError_Handler(void) __attribute__ ((weak, alias("Default_Handler")));
/*----------------------------------------------------------------------------
  Exception / Interrupt Vector Table
 *----------------------------------------------------------------------------*/
void Vectors(void)
{
    __ASM volatile (
        ".align 11                                        \n"
        // Current EL with SP0
        ".align 7                                         \n"
        "B      Reset_Handler                             \n" // Synchronous
        ".align 7                                         \n"
        "B      IRQ_Handler                               \n" // IRQ/vIRQ
        ".align 7                                         \n"
        "B      FIQ_Handler                               \n" // FIQ/vFIQ
        ".align 7                                         \n"
        "B      SError_Handler                            \n" // SError

        // Current EL with SPx
        ".align 7                                         \n"
        "B      Sync_Handler                              \n" // Synchronous
        ".align 7                                         \n"
        "B      IRQ_Handler                               \n" // IRQ/vIRQ
        ".align 7                                         \n"
        "B      FIQ_Handler                               \n" // FIQ/vFIQ
        ".align 7                                         \n"
        "B      SError_Handler                            \n" // SError

        // Lower EL using AArch64
        ".align 7                                         \n"
        "B      .                                         \n" // Synchronous
        ".align 7                                         \n"
        "B      .                                         \n" // IRQ/vIRQ
        ".align 7                                         \n"
        "B      .                                         \n" // FIQ/vFIQ
        ".align 7                                         \n"
        "B      .                                         \n" // SError

        // Lower EL using AArch32
        ".align 7                                         \n"
        "B      .                                         \n" // Synchronous
        ".align 7                                         \n"
        "B      .                                         \n" // IRQ/vIRQ
        ".align 7                                         \n"
        "B      .                                         \n" // FIQ/vFIQ
        ".align 7                                         \n"
        "B      .                                         \n" // SError
        );
}

/*----------------------------------------------------------------------------
  Reset Handler called on controller reset
 *----------------------------------------------------------------------------*/
void Reset_Handler(void)
{
    __ASM volatile (

        // Mask interrupts
        "MSR     DAIFSet, #3                             \n"

        // Check exception level, only support EL1
        "MRS     x0, CurrentEL                           \n"
        "AND     x0, x0, #(3 << 2)                       \n"
        "CMP     x0, #(1 << 2)                           \n"
        "BNE     cpu_not_in_el1                          \n"

        //Reset SCTLR Settings
        "cpu_in_el1:                                     \n"
        "MRS     x0, SCTLR_EL1                           \n" // Read SCTLR_EL1 System Control register
        "BIC     x0, x0, #(1 << 12)                      \n" // Clear I bit 12 to disable I Cache
        "BIC     x0, x0, #(1 << 2)                       \n" // Clear C bit 2 to disable D Cache
        "BIC     x0, x0, #1                              \n" // Clear M bit 0 to disable MMU
        "BIC     x0, x0, #(1 << 11)                      \n" // Clear Z bit 11 to disable branch prediction
        "BIC     x0, x0, #(1 << 13)                      \n" // Clear V bit 13 to disable hives
        "MSR     SCTLR_EL1, x0                           \n" // Write value back to SCTLR_EL1 System Control register
        "ISB                                             \n" // Ensure changes take effect

        // Set Vector Base Address Register (VBAR) to point to this application's vector table
        "LDR     x0, =Vectors                            \n"
        "MSR     VBAR_EL1, x0                            \n"

        // Setup Stack for EL1
        "LDR     x1, =__StackTop                         \n"
        "MOV     SP, x1                                  \n"

        // Call DataInit
        "BL     DataInit                                 \n"

        // Call SystemInit
        "BL     SystemInit                               \n"

        // Unmask interrupts
        "MSR    DAIFClr, #3                              \n"

        // Call _start
        "BL     _start                                   \n"

        "cpu_not_in_el1:                                 \n"
        "CMP     x0, #(2 << 2)                           \n"
        "BEQ	 cpu_in_el2                              \n"

        // Cpu in EL3
        "mov 	x2, #(1 << 0)                            \n"
        "orr 	x2, x2, #(1 << 4)                        \n"
        "orr 	x2, x2, #(1 << 5)                        \n"
        "bic 	x2, x2, #(1 << 7)                        \n"
        "orr 	x2, x2, #(1 << 8)                        \n"
        "orr 	x2, x2, #(1 << 10)                       \n"
        "msr 	scr_el3, x2                              \n"

        "mov 	x2, #9                                   \n"
        "orr 	x2, x2, #(1 << 6)                        \n"
        "orr 	x2, x2, #(1 << 7)                        \n"
        "orr 	x2, x2, #(1 << 8)                        \n"
        "orr 	x2, x2, #(1 << 9)                        \n"
        "msr 	spsr_el3, x2                             \n"
        "adr 	x2, cpu_in_el2                           \n"
        "msr 	elr_el3, x2                              \n"
        "eret                                            \n"

        "cpu_in_el2:                                     \n"
        "mrs     x0, cnthctl_el2                         \n"
        "orr     x0, x0, #3                              \n"
        "msr     cnthctl_el2, x0                         \n"
        "msr     cntvoff_el2, xzr                        \n"

        "mov     x0, #(1 << 31)                          \n"
        "orr     x0, x0, #(1 << 1)                       \n"
        "msr     hcr_el2, x0                             \n"

        "mov     x2, #5                                  \n"
        "orr     x2, x2, #(1 << 6)                       \n"
        "orr     x2, x2, #(1 << 7)                       \n"
        "orr     x2, x2, #(1 << 8)                       \n"
        "orr     x2, x2, #(1 << 9)                       \n"
        "msr     spsr_el2, x2                            \n"
        "adr     x2, cpu_in_el1                          \n"
        "msr     elr_el2, x2                             \n"
        "eret                                            \n"
        );
}

void Default_Handler(void)
{
    while (1) {
        ;
    }
}

#else
/*----------------------------------------------------------------------------
  Exception / Interrupt Vector Table
 *----------------------------------------------------------------------------*/
void Vectors(void)
{
    __ASM volatile(
    "LDR    PC, =Reset_Handler                        \n"
    "LDR    PC, =Undef_Handler                        \n"
    "LDR    PC, =SVC_Handler                          \n"
    "LDR    PC, =PAbt_Handler                         \n"
    "LDR    PC, =DAbt_Handler                         \n"
    "NOP                                              \n"
    "LDR    PC, =IRQ_Handler                          \n"
    "LDR    PC, =FIQ_Handler                          \n"
    );
}

/*----------------------------------------------------------------------------
  Reset Handler called on controller reset
 *----------------------------------------------------------------------------*/
void Reset_Handler(void)
{
    __ASM volatile(

    // Mask interrupts
    "CPSID   if                                      \n"

    // Reset SCTLR Settings
    "MRC     p15, 0, R0, c1, c0, 0                   \n" // Read CP15 System Control register
    "BIC     R0, R0, #(0x1 << 12)                    \n" // Clear I bit 12 to disable I Cache
    "BIC     R0, R0, #(0x1 <<  2)                    \n" // Clear C bit  2 to disable D Cache
    "BIC     R0, R0, #0x1                            \n" // Clear M bit  0 to disable MMU
    "BIC     R0, R0, #(0x1 << 11)                    \n" // Clear Z bit 11 to disable branch prediction
    "BIC     R0, R0, #(0x1 << 13)                    \n" // Clear V bit 13 to disable hivecs
    "MCR     p15, 0, R0, c1, c0, 0                   \n" // Write value back to CP15 System Control register
    "ISB                                             \n"

    // Configure ACTLR
    "MRC     p15, 0, r0, c1, c0, 1                   \n" // Read CP15 Auxiliary Control Register
    "ORR     r0, r0, #(1 <<  1)                      \n" // Enable L2 prefetch hint (UNK/WI since r4p1)
    "MCR     p15, 0, r0, c1, c0, 1                   \n" // Write CP15 Auxiliary Control Register

    // Set Vector Base Address Register (VBAR) to point to this application's vector table
    "LDR    R0, =Vectors                             \n"
    "MCR    p15, 0, R0, c12, c0, 0                   \n"

    // Setup Stack for each exceptional mode
    "CPS    #0x11                                    \n" // FIQ
    "LDR    SP, =Image$$FIQ_STACK$$ZI$$Limit         \n"
    "CPS    #0x12                                    \n" // IRQ
    "LDR    SP, =Image$$IRQ_STACK$$ZI$$Limit         \n"
    "CPS    #0x13                                    \n" // SVC
    "LDR    SP, =Image$$SVC_STACK$$ZI$$Limit         \n"
    "CPS    #0x17                                    \n" // ABT
    "LDR    SP, =Image$$ABT_STACK$$ZI$$Limit         \n"
    "CPS    #0x1B                                    \n" // UND
    "LDR    SP, =Image$$UND_STACK$$ZI$$Limit         \n"
    "CPS    #0x1F                                    \n" // SYS
    "LDR    SP, =Image$$SYS_STACK$$ZI$$Limit         \n"
    "CPS    #0x13                                    \n" // SVC

    // Call DataInit
    "BL     DataInit                                 \n"

    // Call SystemInit
    "BL     SystemInit                               \n"

    // Unmask interrupts
    "CPSIE  if                                       \n"

    // Call _start
    "BL     _start                                   \n"
    );
}

void Dump_Regs(uint32_t *regs, uint32_t mode)
{
    uint32_t *buf = (uint32_t *)regs[13], stack = 0, stack_limit = Image_SVC_STACK_ZI_Limit;
    uint32_t n = 0, i = 0, j = 0;
    uint32_t call_stack[16];

    switch (mode) {
    case ABT_MODE:
        printf("abort mode:\n");
        break;
    case UND_MODE:
        printf("undefined mode:\n");
        break;
    case FIQ_MODE:
        printf("fiq mode:\n");
        break;
    default:
        printf("unknow mode:%" PRId32 "\n", mode);
    }

    printf("pc : %08" PRIx32 "  lr : %08" PRIx32 " cpsr: %08" PRIx32 "\n", regs[15], regs[14], regs[16]);
    printf("sp : %08" PRIx32 "  ip : %08" PRIx32 "  fp : %08" PRIx32 "\n", regs[13], regs[12], regs[11]);
    printf("r10: %08" PRIx32 "  r9 : %08" PRIx32 "  r8 : %08" PRIx32 "\n", regs[10], regs[9], regs[8]);
    printf("r7 : %08" PRIx32 "  r6 : %08" PRIx32 "  r5 : %08" PRIx32 "  r4 : %08" PRIx32 "\n", regs[7], regs[6], regs[5], regs[4]);
    printf("r3 : %08" PRIx32 "  r2 : %08" PRIx32 "  r1 : %08" PRIx32 "  r0 : %08" PRIx32 "\n", regs[3], regs[2], regs[1], regs[0]);

    printf("\nstack: \n");

    stack = regs[13];
    n = (stack_limit - stack) / 4;
    for (i = 0; i < n; i++) {
        if (i && i % 4 == 0) {
            printf("\n");
        }
        if (i % 4 == 0) {
            printf("0x%08" PRIx32 ": ", stack + i * 4);
        }

        printf("0x%08" PRIx32 "  ", buf[i]);
        if ((buf[i] >= STEXT && buf[i] < ETEXT) && j < 16) {
            call_stack[j++] = buf[i];
        }
    }

    printf("\n\n");
    printf("Show more call stack info by run: addr2line -e hal0.elf -a -f %08" PRIx32 " %08" PRIx32 " ", regs[15], regs[14]);
    for (i = 0; i < j; i++) {
        printf("%08" PRIx32 " ", call_stack[i]);
    }
    printf("\n");
}

/*----------------------------------------------------------------------------
  Default Handler for Exceptions / Interrupts
 *----------------------------------------------------------------------------*/
void Default_Handler(void)
{
    __ASM volatile (
        "sub    sp, #0x10                                  \n"
        "stmfd  sp!, {r0-r12}                              \n" // save the CPU context r0-r12
        "mov    r5, sp                                     \n"
        "mrs    r0, CPSR                                   \n"
        "mrs    r4, SPSR                                   \n"
        "orr    r8, r4, #0x1c0                             \n"
        "msr    CPSR_c, r8                                 \n" // switch to pre-exception mode
        "mov    r1, sp                                     \n"
        "mov    r2, lr                                     \n"
        "msr    CPSR_c, r0                                 \n" // back to current mode
        "mov    r3, lr                                     \n"
        "sub    r3, #8                                     \n"
        "add    sp, #0x44                                  \n"
        "stmfd  sp!, {r1-r4}                               \n" //save cpsr pc lr sp
        "mov    sp, r5                                     \n"
        "mov    r0, r5                                     \n"
        "mrs    r1, CPSR                                   \n"
        "and    r1, r1, #0x1f                              \n"
        "bl     Dump_Regs                                  \n"
        "b      .                                          \n"
        );
}
#endif

#if defined(__GNUC__) && ! defined(__ARMCC_VERSION)
#pragma GCC pop_options
#elif defined(__ARMCC_VERSION)
#pragma pop
#endif

#endif /* HAL_AP_CORE */
