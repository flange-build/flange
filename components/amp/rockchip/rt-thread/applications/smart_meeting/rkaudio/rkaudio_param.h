/**
  * Copyright (c) 2023 Rockchip Electronic Co.,Ltd
  *
  * SPDX-License-Identifier: Apache-2.0
  *
  ******************************************************************************
  * @file    rkaudio_param.h
  * @author  Jair Wu
  * @version v0.1
  * @date    2023.4.20
  * @brief   The rkaudio param parser
  ******************************************************************************
  */

#ifndef __RKAUDIO_PARAM_H__
#define __RKAUDIO_PARAM_H__

struct bf_cfg_param
{
    uint32_t in_size;
    uint32_t src_chan;
    uint32_t ref_chan;
    uint32_t bits;
    uint32_t in_fs;
    uint32_t rkaudio_param;
};

void *rkaudio_param_from_file(char *file, int *size);
void rkaudio_param_free(void *alloc);

#endif

