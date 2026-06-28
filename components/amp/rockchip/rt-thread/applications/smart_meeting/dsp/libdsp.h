/**
  * Copyright (c) 2023 Rockchip Electronic Co.,Ltd
  *
  * SPDX-License-Identifier: Apache-2.0
  *
  ******************************************************************************
  * @file    libdsp.h
  * @author  Jair Wu
  * @version v0.1
  * @date    2023.4.24
  * @brief   The dsp app layer
  ******************************************************************************
  */

#ifndef __LIBDSP_H__
#define __LIBDSP_H__

#include "drv_dsp.h"

#define RKAUDIO_ID      0x50000002

enum {
    RKAUDIO_CONFIG = 0x40000003,
    RKAUDIO_PROCESS,
    RKAUDIO_DESTROY,

    RKSTUDIO_EQ_CONFIG,
    RKSTUDIO_EQ_PROCESS,
    RKSTUDIO_EQ_DESTROY,
};

int libdsp_do_work(struct dsp_work *work);
void libdsp_destroy_work(struct dsp_work *work);
struct dsp_work *libdsp_create_work(uint32_t id,
                                    uint32_t algo_type,
                                    uint32_t param,
                                    uint32_t param_size);

#endif

