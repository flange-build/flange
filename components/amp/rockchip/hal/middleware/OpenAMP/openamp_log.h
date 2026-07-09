/* SPDX-License-Identifier: BSD-3-Clause */
/*
 * Copyright (c) 2021 Rockchip Electronics Co., Ltd.
 */

#ifndef _OPENAMP_LOG_H_
#define _OPENAMP_LOG_H_

#ifdef __cplusplus
 extern "C" {
#endif

#define LOGQUIET 0
#define	LOGERR   1
#define	LOGWARN  2
#define	LOGINFO  3
#define	LOGDBG   4

#ifndef LOGLEVEL
#define LOGLEVEL LOGINFO
#endif


#if defined (__LOG_TRACE_IO_) || defined(__LOG_UART_IO_)
#if LOGLEVEL >= LOGDBG
#define log_dbg(fmt, ...)  printf("[DBG  ]" fmt, ##__VA_ARGS__)
#else
#define log_dbg(fmt, ...)
#endif
#if LOGLEVEL >= LOGINFO
#define log_info(fmt, ...) printf("[INFO ]" fmt, ##__VA_ARGS__)
#else
#define log_info(fmt, ...)
#endif
#if LOGLEVEL >= LOGWARN
#define log_warn(fmt, ...) printf("[WARN ]" fmt, ##__VA_ARGS__)
#else
#define log_warn(fmt, ...)
#endif
#if LOGLEVEL >= LOGERR
#define log_err(fmt, ...)  printf("[ERR  ]" fmt, ##__VA_ARGS__)
#else
#define log_err(fmt, ...)
#endif
#else
#define log_dbg(fmt, ...)
#define log_info(fmt, ...)
#define log_warn(fmt, ...)
#define log_err(fmt, ...)
#endif /* __LOG_TRACE_IO_ */

#ifdef __cplusplus
}
#endif

#endif
