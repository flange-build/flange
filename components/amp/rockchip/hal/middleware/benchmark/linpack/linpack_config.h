/* SPDX-License-Identifier: BSD-3-Clause */
/*
 * Copyright (c) 2022 Rockchip Electronics Co., Ltd.
 */
#ifndef LINPACK_CONFIG_H_
#define LINPACK_CONFIG_H_

/*
 * SP for Single-precision floating-point
 * DP for Double-precision floating-point
 * LINPACK_ARSIZE: Default 200, at least 10.
 */

/* Configuration for ARM Cortex-A55 */
#define DP
#define LINPACK_ARSIZE 200

/* Configuration for ARM Cortex-M0 */
//#define SP
//#define LINPACK_ARSIZE 50

#define LINPACK_CLOCKS_PER_SEC 1000

#endif /* LINPACK_CONFIG_H_ */
