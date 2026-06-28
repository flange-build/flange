/**
  * Copyright (c) 2019 Rockchip Electronic Co.,Ltd
  *
  * SPDX-License-Identifier: Apache-2.0
  ******************************************************************************
  * @file    drv_uart.c
  * @author  Jason Zhu
  * @version V0.1
  * @date    1-Aug-2019
  * @brief
  *
  ******************************************************************************
  */

#include "drv_uart.h"

struct device_uart
{
    rt_uint8_t irqno;
    struct UART_REG *hw_base;
    char name[6];           /* sizeof("uartx") == 6  */
};

/* UART0 device driver structure */
static struct device_uart g_uart0_priv =
{
    .irqno          = 0,
    .name           = "uart0",
};

/* set the uart configture */
void uart_base_init(void)
{
    unsigned int temp;
    unsigned int baudrate;

    *UART0_SRR = 0x07;  //UART reset , rx fifo & tx fifo reset
    *UART0_IER = 0x00;  //interrupt disable
    *UART0_MCR = 0x0 << 6; //SIR disable
    *UART0_LCR = (*UART0_LCR) & (~0xf) | 0x3; // one stop bit , 8 data bit ,no parity
    *UART0_LCR = *UART0_LCR | (1 << 7);
    baudrate = 9600;
    temp = 10000 * 1000 / 16 / baudrate;
    *UART0_DLL = temp & 0xff;
    *UART0_DLH = (temp >> 8) & 0xff;
    *UART0_LCR = *UART0_LCR & ~(1 << 7);
    *UART0_SFE = 0x1;   //shadow FIFO enable;
    *UART0_SRT = 0x3;   // fifo 2 less than
    *UART0_STET = 0x1;  //2 char in tx fifo
}

void uart_putc_polled(char c)
{
    unsigned int uartTimeout;
    uartTimeout = 0xffff;
    while (!(*UART0_USR & (1 << 1))) //TX FIFO not full
    {
        uartTimeout --;
        if (uartTimeout == 0)
            return ;
    }
    *UART0_THR = c;

}

char uart_getchar_polled(void)
{
    unsigned int uartTimeout;
    uartTimeout = 0xffff;

    while (!(*UART0_USR & (1 << 3))) //RX FIFO not empty;
    {
        uartTimeout --;
        if (uartTimeout == 0)
            return 0;
    }
    return *UART0_RBR;
}

static void usart_handler(int vector, void *param)
{
    rt_hw_serial_isr((struct rt_serial_device *)param, RT_SERIAL_EVENT_RX_IND);
}


/* set the uart configture by frame */
static rt_err_t usart_configure(struct rt_serial_device *serial,
                                struct serial_configure *cfg)
{
    RT_ASSERT(serial != RT_NULL);
    RT_ASSERT(cfg != RT_NULL);

    uart_base_init();

    return RT_EOK;
}

static rt_err_t usart_control(struct rt_serial_device *serial,
                              int cmd, void *arg)
{
    RT_ASSERT(serial != RT_NULL);

    switch (cmd)
    {
    case RT_DEVICE_CTRL_CLR_INT:
        break;
    case RT_DEVICE_CTRL_SET_INT:
        break;
    }

    return RT_EOK;
}

static int usart_putc(struct rt_serial_device *serial, char c)
{
    uart_putc_polled(c);

    return 0;
}

static int usart_getc(struct rt_serial_device *serial)
{
    uart_putc_polled('p');
    return (rt_uint8_t)uart_getchar_polled();
}

static struct rt_uart_ops ops =
{
    usart_configure,
    usart_control,
    usart_putc,
    usart_getc,
};

static struct rt_serial_device serial =
{
    .ops = &ops,
    .config.baud_rate = BAUD_RATE_9600,
    .config.bit_order = BIT_ORDER_LSB,
    .config.data_bits = DATA_BITS_8,
    .config.parity    = PARITY_NONE,
    .config.stop_bits = STOP_BITS_1,
    .config.invert    = NRZ_NORMAL,
    .config.bufsz     = RT_SERIAL_RB_BUFSZ,
};

int rt_hw_uart_init(void)
{
    struct device_uart *uart  = &g_uart0_priv;
    uart->hw_base = (struct UART_REG *)UART0_BASE;
    uart_base_init();
    rt_hw_serial_register(
        &serial,
        uart->name,
        RT_DEVICE_FLAG_RDWR | RT_DEVICE_FLAG_INT_RX, uart);
    rt_console_set_device(RT_CONSOLE_DEVICE_NAME);

    return 0;
}

