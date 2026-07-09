/* SPDX-License-Identifier: BSD-3-Clause */
/*
 * Copyright (c) 2022 Rockchip Electronics Co., Ltd.
 */
#ifndef TINYMEMBENCH_CONFIG_H_
#define TINYMEMBENCH_CONFIG_H_

/* Configuration for ARM Cortex-A55 */
#define TINYMEMBENCH_SIZE (4 * 1024 * 1024)
#define ALIGN_PADDING 0x100000
#define CACHE_LINE_SIZE 64

/* Configuration for MCU */
//#define TINYMEMBENCH_SIZE (64 * 1024)
//#define ALIGN_PADDING 0x1000
//#define CACHE_LINE_SIZE 32

#define TINYMEMBENCH_CLOCKS_PER_SEC 1000

#endif /* TINYMEMBENCH_CONFIG_H_ */
