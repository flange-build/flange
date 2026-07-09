/* SPDX-License-Identifier: BSD-3-Clause */
/*
 * Copyright (c) 2023 Rockchip Electronics Co., Ltd.
 *
 */

#ifndef __SDHCI_BLOCKDEV_H__
#define __SDHCI_BLOCKDEV_H__

#include "hal_bsp.h"
#include "hal_base.h"

typedef unsigned long	u64;
typedef unsigned char	u8;
typedef signed char		s8;
typedef unsigned short	u16;
typedef signed short	s16;
typedef unsigned int	u32;
typedef signed int		s32;
typedef unsigned char	uint8;
typedef unsigned short	uint16;
typedef unsigned int	uint32;
typedef signed char		int8;
typedef signed short	int16;
typedef signed int		int32;
#define PRINT_E			printf
#define udelay			HAL_DelayUs
#define mdelay			HAL_DelayMs
#define MAX				HAL_MAX
#define MIN				HAL_MIN
#define FALSE			HAL_FALSE
#define TRUE			HAL_TRUE

typedef uint64_t lba_t;

typedef struct BlockDevOps {
	int card_id;
} BlockDevOps;

typedef struct BlockDev {
	BlockDevOps ops;

	const char *name;
	int external_gpt;
	unsigned int block_size;
	/* If external_gpt = 0, then stream_block_count may be 0, indicating
	 * that the block_count value applies for both read/write and streams */
	lba_t block_count;	/* size addressable by read/write */
	lba_t stream_block_count;	/* size addressible by new_stream */
} BlockDev;

typedef struct BlockDevCtrlrOps {
	int (*update)(struct BlockDevCtrlrOps *me);
	/*
	 * Check if a block device is owned by the ctrlr. 1 = success, 0 =
	 * failure
	 */
	int (*is_bdev_owned)(struct BlockDevCtrlrOps *me, BlockDev *bdev);
} BlockDevCtrlrOps;

typedef struct BlockDevCtrlr {
	BlockDevCtrlrOps ops;

	int need_update;
} BlockDevCtrlr;

typedef enum {
	BLOCKDEV_FIXED,
	BLOCKDEV_REMOVABLE,
} blockdev_type_t;

#endif