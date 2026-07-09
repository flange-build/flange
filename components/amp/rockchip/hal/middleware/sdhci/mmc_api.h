/* SPDX-License-Identifier: BSD-3-Clause */
/*
 * Copyright (c) 2023 Rockchip Electronics Co., Ltd.
 *
 */

#ifndef _SDM_API_
#define _SDM_API_

/* SDM return value */
#define SDM_SUCCESS              (0)
#define SDM_FALSE                (0x1 << 0)
#define SDM_CARD_NOTPRESENT      (0x1 << 1)
#define SDM_PARAM_ERROR          (0x1 << 2)
#define SDM_RESP_ERROR           (0x1 << 3)
#define SDM_RESP_CRC_ERROR       (0x1 << 4)
#define SDM_RESP_TIMEOUT         (0x1 << 5)
#define SDM_DATA_CRC_ERROR       (0x1 << 6)
#define SDM_DATA_READ_TIMEOUT    (0x1 << 7)
#define SDM_END_BIT_ERROR        (0x1 << 8)
#define SDM_START_BIT_ERROR      (0x1 << 9)
#define SDM_BUSY_TIMEOUT         (0x1 << 10)
#define SDM_DMA_BUSY             (0x1 << 11)
#define SDM_ERROR                (0x1 << 12)
#define SDM_VOLTAGE_NOT_SUPPORT  (0x1 << 13)
#define SDM_FUNC_NOT_SUPPORT     (0x1 << 14)
#define SDM_UNKNOWABLECARD       (0x1 << 15)
#define SDM_CARD_WRITE_PROT      (0x1 << 16)
#define SDM_CARD_LOCKED          (0x1 << 17)
#define SDM_CARD_CLOSED          (0x1 << 18)
#define SD_CADR_AVAILABLE        (0x1 << 19)

/* SDM IOCTRL cmd */
#define SDM_IOCTRL_REGISTER_CARD         (0x0)
#define SDM_IOCTRL_UNREGISTER_CARD       (0x1)
#define SDM_IOCTRL_SET_PASSWORD          (0x2)
#define SDM_IOCTRL_CLEAR_PASSWORD        (0x3)
#define SDM_IOCTRL_FORCE_ERASE_PASSWORD  (0x4)
#define SDM_IOCTRL_LOCK_CARD             (0x5)
#define SDM_IOCTRL_UNLOCK_CARD           (0x6)
#define SDM_IOCTR_GET_CAPABILITY         (0x7)
#define SDM_IOCTR_GET_PSN                (0x8)
#define SDM_IOCTR_IS_CARD_READY          (0x9)
#define SDM_IOCTR_FLUSH                  (0xA)
#define SDM_IOCTR_GET_BOOT_CAPABILITY    (0xB)
#define SDM_IOCTR_INIT_BOOT_PARTITION    (0xC)
#define SDM_IOCTR_DEINIT_BOOT_PARTITION  (0xD)
#define SDM_IOCTR_ACCESS_BOOT_PARTITION  (0xE)
#define SDM_IOCTR_SET_BOOT_BUSWIDTH      (0xF)
#define SDM_IOCTR_SET_BOOT_PART_SIZE     (0x10)

void sdmmc_init(void *base_reg);
int32_t sdmmc_ioctrl(uint32_t cmd, void *param);
int32_t sdmmc_write(uint32_t start, uint32_t count, const void *buffer);
int32_t sdmmc_read(uint32_t start, uint32_t count, void *buffer);
int32_t sdmmc_open(void);

#endif
