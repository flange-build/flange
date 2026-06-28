/**
  * Copyright (c) 2019 Rockchip Electronic Co.,Ltd
  *
  * SPDX-License-Identifier: Apache-2.0
  ******************************************************************************
  * @file    start.s
  * @author  Jason Zhu
  * @version V0.1
  * @date    1-Aug-2019
  * @brief
  *
  ******************************************************************************
  */

#include "riscv_csr_encoding.h"

# define LREG lw
# define SREG sw
# define REGBYTES 4

.globl _start
.globl main
.globl trap_entry
.globl handle_trap
.globl sc_exit
.globl soft_int_entry
.globl handle_soft_int
.globl timer_int_entry
.globl handle_timer_int
.globl ext_int_entry
.globl handle_ext_int
.weak trap_entry, handle_trap, sc_exit
.weak soft_int_entry, timer_int_entry, ext_int_entry
.weak handle_soft_int, handle_timer_int, handle_ext_int
.text
/* skip supervisor & hypervisor & user vectors */
.org(64 * 7)
.align 6

machine_trap_entry:  //vec 0
j trap_entry
vec_reserved1:
j sc_exit
vec_reserved2:
j sc_exit
vec_machine_soft_int_entry://vec 3
j soft_int_entry
vec_reserved4:
j sc_exit
vec_reserved5:
j sc_exit
vec_reserved6:
j sc_exit
vec_machine_timer_int_entry://vec 7
j timer_int_entry
vec_reserved8:
j sc_exit
vec_reserved9:
j sc_exit
vec_reserved10:
j sc_exit
vec_machine_ext_int_entry://vec 11
j ext_int_entry
vec_reserved12:
j sc_exit
vec_reserved13:
j sc_exit
vec_reserved14:
j sc_exit
vec_reserved15:
j sc_exit

.align 6

_start:
# clear bss
la      a1, __BSS_START__
la      a2, __BSS_END__
j       4f
3:
sw      zero, 0(a1)
add     a1, a1, 4
4:
bne     a1, a2, 3b
auipc   gp, % hi(_gp)
addi    gp, gp, % lo(_gp)
la      sp, __C_STACK_TOP__

// Timer init
li      t0, mtime_ctrl
li      t1, (1 << SCR1_MTIME_CTRL_EN)   // enable, use internal clock
sw      t1, (t0)
li      t0, mtime_div
li      t1, (100 - 1)                   // divide by 100
sw      t1, (t0)
li      t0, mtimecmp
li      t1, -1
sw      t1, (t0)                        // max value for mtimecmp
sw      t1, 4(t0)

li      a0, 0
li      a1, 0
call    entry
j       sc_exit

trap_entry:
addi sp, sp, -32*4

SREG x1, 1*REGBYTES(sp)
SREG x2, 2*REGBYTES(sp)
SREG x3, 3*REGBYTES(sp)
SREG x4, 4*REGBYTES(sp)
SREG x5, 5*REGBYTES(sp)
SREG x6, 6*REGBYTES(sp)
SREG x7, 7*REGBYTES(sp)
SREG x8, 8*REGBYTES(sp)
SREG x9, 9*REGBYTES(sp)
SREG x11, 11*REGBYTES(sp)
SREG x12, 12*REGBYTES(sp)
SREG x13, 13*REGBYTES(sp)
SREG x14, 14*REGBYTES(sp)
SREG x15, 15*REGBYTES(sp)
#ifndef __RVE_EXT
SREG x16, 16*REGBYTES(sp)
SREG x17, 17*REGBYTES(sp)
SREG x18, 18*REGBYTES(sp)
SREG x19, 19*REGBYTES(sp)
SREG x20, 20*REGBYTES(sp)
SREG x21, 21*REGBYTES(sp)
SREG x22, 22*REGBYTES(sp)
SREG x23, 23*REGBYTES(sp)
SREG x24, 24*REGBYTES(sp)
SREG x25, 25*REGBYTES(sp)
SREG x26, 26*REGBYTES(sp)
SREG x27, 27*REGBYTES(sp)
SREG x28, 28*REGBYTES(sp)
SREG x29, 29*REGBYTES(sp)
SREG x30, 30*REGBYTES(sp)
SREG x31, 31*REGBYTES(sp)
#endif // __RVE_EXT

csrr a0, mcause
csrr a1, mepc
mv a2, sp
call handle_trap

LREG x1, 1*REGBYTES(sp)
LREG x2, 2*REGBYTES(sp)
LREG x3, 3*REGBYTES(sp)
LREG x4, 4*REGBYTES(sp)
LREG x5, 5*REGBYTES(sp)
LREG x6, 6*REGBYTES(sp)
LREG x7, 7*REGBYTES(sp)
LREG x8, 8*REGBYTES(sp)
LREG x9, 9*REGBYTES(sp)
LREG x10, 10*REGBYTES(sp)
LREG x11, 11*REGBYTES(sp)
LREG x12, 12*REGBYTES(sp)
LREG x13, 13*REGBYTES(sp)
LREG x14, 14*REGBYTES(sp)
LREG x15, 15*REGBYTES(sp)
#ifndef __RVE_EXT
LREG x16, 16*REGBYTES(sp)
LREG x17, 17*REGBYTES(sp)
LREG x18, 18*REGBYTES(sp)
LREG x19, 19*REGBYTES(sp)
LREG x20, 20*REGBYTES(sp)
LREG x21, 21*REGBYTES(sp)
LREG x22, 22*REGBYTES(sp)
LREG x23, 23*REGBYTES(sp)
LREG x24, 24*REGBYTES(sp)
LREG x25, 25*REGBYTES(sp)
LREG x26, 26*REGBYTES(sp)
LREG x27, 27*REGBYTES(sp)
LREG x28, 28*REGBYTES(sp)
LREG x29, 29*REGBYTES(sp)
LREG x30, 30*REGBYTES(sp)
LREG x31, 31*REGBYTES(sp)
#endif // __RVE_EXT

addi sp, sp, 32*4
mret

soft_int_entry:
addi sp, sp, -32*4

SREG x1, 1*REGBYTES(sp)
SREG x2, 2*REGBYTES(sp)
SREG x3, 3*REGBYTES(sp)
SREG x4, 4*REGBYTES(sp)
SREG x5, 5*REGBYTES(sp)
SREG x6, 6*REGBYTES(sp)
SREG x7, 7*REGBYTES(sp)
SREG x8, 8*REGBYTES(sp)
SREG x9, 9*REGBYTES(sp)
SREG x11, 11*REGBYTES(sp)
SREG x12, 12*REGBYTES(sp)
SREG x13, 13*REGBYTES(sp)
SREG x14, 14*REGBYTES(sp)
SREG x15, 15*REGBYTES(sp)
#ifndef __RVE_EXT
SREG x16, 16*REGBYTES(sp)
SREG x17, 17*REGBYTES(sp)
SREG x18, 18*REGBYTES(sp)
SREG x19, 19*REGBYTES(sp)
SREG x20, 20*REGBYTES(sp)
SREG x21, 21*REGBYTES(sp)
SREG x22, 22*REGBYTES(sp)
SREG x23, 23*REGBYTES(sp)
SREG x24, 24*REGBYTES(sp)
SREG x25, 25*REGBYTES(sp)
SREG x26, 26*REGBYTES(sp)
SREG x27, 27*REGBYTES(sp)
SREG x28, 28*REGBYTES(sp)
SREG x29, 29*REGBYTES(sp)
SREG x30, 30*REGBYTES(sp)
SREG x31, 31*REGBYTES(sp)
#endif // __RVE_EXT

csrr a0, mcause
csrr a1, mepc
mv a2, sp
call handle_soft_int

LREG x1, 1*REGBYTES(sp)
LREG x2, 2*REGBYTES(sp)
LREG x3, 3*REGBYTES(sp)
LREG x4, 4*REGBYTES(sp)
LREG x5, 5*REGBYTES(sp)
LREG x6, 6*REGBYTES(sp)
LREG x7, 7*REGBYTES(sp)
LREG x8, 8*REGBYTES(sp)
LREG x9, 9*REGBYTES(sp)
LREG x10, 10*REGBYTES(sp)
LREG x11, 11*REGBYTES(sp)
LREG x12, 12*REGBYTES(sp)
LREG x13, 13*REGBYTES(sp)
LREG x14, 14*REGBYTES(sp)
LREG x15, 15*REGBYTES(sp)
#ifndef __RVE_EXT
LREG x16, 16*REGBYTES(sp)
LREG x17, 17*REGBYTES(sp)
LREG x18, 18*REGBYTES(sp)
LREG x19, 19*REGBYTES(sp)
LREG x20, 20*REGBYTES(sp)
LREG x21, 21*REGBYTES(sp)
LREG x22, 22*REGBYTES(sp)
LREG x23, 23*REGBYTES(sp)
LREG x24, 24*REGBYTES(sp)
LREG x25, 25*REGBYTES(sp)
LREG x26, 26*REGBYTES(sp)
LREG x27, 27*REGBYTES(sp)
LREG x28, 28*REGBYTES(sp)
LREG x29, 29*REGBYTES(sp)
LREG x30, 30*REGBYTES(sp)
LREG x31, 31*REGBYTES(sp)
#endif // __RVE_EXT

addi sp, sp, 32*4
mret

timer_int_entry:
addi sp, sp, -32*4

SREG x1, 1*REGBYTES(sp)
SREG x2, 2*REGBYTES(sp)
SREG x3, 3*REGBYTES(sp)
SREG x4, 4*REGBYTES(sp)
SREG x5, 5*REGBYTES(sp)
SREG x6, 6*REGBYTES(sp)
SREG x7, 7*REGBYTES(sp)
SREG x8, 8*REGBYTES(sp)
SREG x9, 9*REGBYTES(sp)
SREG x11, 11*REGBYTES(sp)
SREG x12, 12*REGBYTES(sp)
SREG x13, 13*REGBYTES(sp)
SREG x14, 14*REGBYTES(sp)
SREG x15, 15*REGBYTES(sp)
#ifndef __RVE_EXT
SREG x16, 16*REGBYTES(sp)
SREG x17, 17*REGBYTES(sp)
SREG x18, 18*REGBYTES(sp)
SREG x19, 19*REGBYTES(sp)
SREG x20, 20*REGBYTES(sp)
SREG x21, 21*REGBYTES(sp)
SREG x22, 22*REGBYTES(sp)
SREG x23, 23*REGBYTES(sp)
SREG x24, 24*REGBYTES(sp)
SREG x25, 25*REGBYTES(sp)
SREG x26, 26*REGBYTES(sp)
SREG x27, 27*REGBYTES(sp)
SREG x28, 28*REGBYTES(sp)
SREG x29, 29*REGBYTES(sp)
SREG x30, 30*REGBYTES(sp)
SREG x31, 31*REGBYTES(sp)
#endif // __RVE_EXT

csrr a0, mcause
csrr a1, mepc
mv a2, sp
call handle_timer_int

LREG x1, 1*REGBYTES(sp)
LREG x2, 2*REGBYTES(sp)
LREG x3, 3*REGBYTES(sp)
LREG x4, 4*REGBYTES(sp)
LREG x5, 5*REGBYTES(sp)
LREG x6, 6*REGBYTES(sp)
LREG x7, 7*REGBYTES(sp)
LREG x8, 8*REGBYTES(sp)
LREG x9, 9*REGBYTES(sp)
LREG x10, 10*REGBYTES(sp)
LREG x11, 11*REGBYTES(sp)
LREG x12, 12*REGBYTES(sp)
LREG x13, 13*REGBYTES(sp)
LREG x14, 14*REGBYTES(sp)
LREG x15, 15*REGBYTES(sp)
#ifndef __RVE_EXT
LREG x16, 16*REGBYTES(sp)
LREG x17, 17*REGBYTES(sp)
LREG x18, 18*REGBYTES(sp)
LREG x19, 19*REGBYTES(sp)
LREG x20, 20*REGBYTES(sp)
LREG x21, 21*REGBYTES(sp)
LREG x22, 22*REGBYTES(sp)
LREG x23, 23*REGBYTES(sp)
LREG x24, 24*REGBYTES(sp)
LREG x25, 25*REGBYTES(sp)
LREG x26, 26*REGBYTES(sp)
LREG x27, 27*REGBYTES(sp)
LREG x28, 28*REGBYTES(sp)
LREG x29, 29*REGBYTES(sp)
LREG x30, 30*REGBYTES(sp)
LREG x31, 31*REGBYTES(sp)
#endif // __RVE_EXT

addi sp, sp, 32*4
mret

ext_int_entry:
addi sp, sp, -32*4

SREG x1, 1*REGBYTES(sp)
SREG x2, 2*REGBYTES(sp)
SREG x3, 3*REGBYTES(sp)
SREG x4, 4*REGBYTES(sp)
SREG x5, 5*REGBYTES(sp)
SREG x6, 6*REGBYTES(sp)
SREG x7, 7*REGBYTES(sp)
SREG x8, 8*REGBYTES(sp)
SREG x9, 9*REGBYTES(sp)
SREG x11, 11*REGBYTES(sp)
SREG x12, 12*REGBYTES(sp)
SREG x13, 13*REGBYTES(sp)
SREG x14, 14*REGBYTES(sp)
SREG x15, 15*REGBYTES(sp)
#ifndef __RVE_EXT
SREG x16, 16*REGBYTES(sp)
SREG x17, 17*REGBYTES(sp)
SREG x18, 18*REGBYTES(sp)
SREG x19, 19*REGBYTES(sp)
SREG x20, 20*REGBYTES(sp)
SREG x21, 21*REGBYTES(sp)
SREG x22, 22*REGBYTES(sp)
SREG x23, 23*REGBYTES(sp)
SREG x24, 24*REGBYTES(sp)
SREG x25, 25*REGBYTES(sp)
SREG x26, 26*REGBYTES(sp)
SREG x27, 27*REGBYTES(sp)
SREG x28, 28*REGBYTES(sp)
SREG x29, 29*REGBYTES(sp)
SREG x30, 30*REGBYTES(sp)
SREG x31, 31*REGBYTES(sp)
#endif // __RVE_EXT

csrr a0, mcause
csrr a1, mepc
mv a2, sp
call handle_ext_int

LREG x1, 1*REGBYTES(sp)
LREG x2, 2*REGBYTES(sp)
LREG x3, 3*REGBYTES(sp)
LREG x4, 4*REGBYTES(sp)
LREG x5, 5*REGBYTES(sp)
LREG x6, 6*REGBYTES(sp)
LREG x7, 7*REGBYTES(sp)
LREG x8, 8*REGBYTES(sp)
LREG x9, 9*REGBYTES(sp)
LREG x10, 10*REGBYTES(sp)
LREG x11, 11*REGBYTES(sp)
LREG x12, 12*REGBYTES(sp)
LREG x13, 13*REGBYTES(sp)
LREG x14, 14*REGBYTES(sp)
LREG x15, 15*REGBYTES(sp)
#ifndef __RVE_EXT
LREG x16, 16*REGBYTES(sp)
LREG x17, 17*REGBYTES(sp)
LREG x18, 18*REGBYTES(sp)
LREG x19, 19*REGBYTES(sp)
LREG x20, 20*REGBYTES(sp)
LREG x21, 21*REGBYTES(sp)
LREG x22, 22*REGBYTES(sp)
LREG x23, 23*REGBYTES(sp)
LREG x24, 24*REGBYTES(sp)
LREG x25, 25*REGBYTES(sp)
LREG x26, 26*REGBYTES(sp)
LREG x27, 27*REGBYTES(sp)
LREG x28, 28*REGBYTES(sp)
LREG x29, 29*REGBYTES(sp)
LREG x30, 30*REGBYTES(sp)
LREG x31, 31*REGBYTES(sp)
#endif // __RVE_EXT

addi sp, sp, 32*4
mret

.globl _wfi
.type _wfi, @function
_wfi:
wfi
ret
.globl _fence
.type _fence, @function
_fence:
fence
ret

handle_trap:
handle_soft_int:
handel_timer_int:
handle_ext_int:
sc_exit:
j sc_exit
