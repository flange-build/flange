/**
  * Copyright (c) 2019 Rockchip Electronic Co.,Ltd
  *
  * SPDX-License-Identifier: Apache-2.0
  ******************************************************************************
  * @file    drv_uart.h
  * @author  Jason Zhu
  * @version V0.1
  * @date    1-Aug-2019
  * @brief
  *
  ******************************************************************************
  */

#ifndef _DRV_UART_H_
#define _DRV_UART_H_

#include <rtdevice.h>
#include "chip_register.h"

#define UART0_BASE UART_BASE

#define UART0_RBR (volatile unsigned int *)(UART0_BASE+0x00)
#define UART0_THR (volatile unsigned int *)(UART0_BASE+0x00)
#define UART0_DLL (volatile unsigned int *)(UART0_BASE+0x00)
#define UART0_DLH (volatile unsigned int *)(UART0_BASE+0x04)
#define UART0_IER (volatile unsigned int *)(UART0_BASE+0x04)
#define UART0_LCR (volatile unsigned int *)(UART0_BASE+0x0c)
#define UART0_MCR (volatile unsigned int *)(UART0_BASE+0x10)
#define UART0_USR (volatile unsigned int *)(UART0_BASE+0x7c)
#define UART0_SRR (volatile unsigned int *)(UART0_BASE+0x88)
#define UART0_SFE (volatile unsigned int *)(UART0_BASE+0x98)
#define UART0_SRT (volatile unsigned int *)(UART0_BASE+0x9c)
#define UART0_STET (volatile unsigned int *)(UART0_BASE+0xa0)

/* UART Register Structure Define */
struct UART_REG
{
    union
    {
        volatile unsigned int RBR;                             /* Address Offset: 0x0000 */
        volatile unsigned int THR;                             /* Address Offset: 0x0000 */
        volatile unsigned int DLL;                            /* Address Offset: 0x0000 */
    };

    union
    {
        volatile unsigned int DLH;                            /* Address Offset: 0x0004 */
        volatile unsigned int IER;                            /* Address Offset: 0x0004 */
    };

    union
    {
        volatile unsigned int IIR;                            /* Address Offset: 0x0008 */
        volatile unsigned int FCR;                            /* Address Offset: 0x0008 */
    };

    volatile unsigned int LCR;                                /* Address Offset: 0x000C */
    volatile unsigned int MCR;                                /* Address Offset: 0x0010 */
    volatile unsigned int LSR;                                /* Address Offset: 0x0014 */
    volatile unsigned int MSR;                                /* Address Offset: 0x0018 */
    volatile unsigned int SCR;                                /* Address Offset: 0x001C */
    volatile unsigned int RESERVED0020[4];                    /* Address Offset: 0x0020 */

    union
    {
        volatile unsigned int SRBR;                           /* Address Offset: 0x0030 */
        volatile unsigned int STHR;                           /* Address Offset: 0x0030 */
    };
    volatile unsigned int RESERVED0034[15];                   /* Address Offset: 0x0034 */

    volatile unsigned int FAR;                                /* Address Offset: 0x0070 */
    volatile unsigned int TFR;                                /* Address Offset: 0x0074 */
    volatile unsigned int RFW;                                /* Address Offset: 0x0078 */
    volatile unsigned int USR;                                /* Address Offset: 0x007C */
    volatile unsigned int TFL;                                /* Address Offset: 0x0080 */
    volatile unsigned int RFL;                                /* Address Offset: 0x0084 */
    volatile unsigned int SRR;                                /* Address Offset: 0x0088 */
    volatile unsigned int SRTS;                               /* Address Offset: 0x008C */
    volatile unsigned int SBCR;                               /* Address Offset: 0x0090 */
    volatile unsigned int SDMAM;                              /* Address Offset: 0x0094 */
    volatile unsigned int SFE;                                /* Address Offset: 0x0098 */
    volatile unsigned int SRT;                                /* Address Offset: 0x009C */
    volatile unsigned int STET;                               /* Address Offset: 0x00A0 */
    volatile unsigned int HTX;                                /* Address Offset: 0x00A4 */
    volatile unsigned int DMASA;                              /* Address Offset: 0x00A8 */
    volatile unsigned int RESERVED00AC[18];                   /* Address Offset: 0x00AC */
    volatile unsigned int CPR;                                /* Address Offset: 0x00F4 */
    volatile unsigned int UCV;                                /* Address Offset: 0x00F8 */
    volatile unsigned int CTR;                                /* Address Offset: 0x00FC */
};

void uart_base_init(void);
void uart_putc_polled(char c);
/* rt-thread uart initialize */
int rt_hw_uart_init(void);

#endif /* _DRV_UART_H_ */
