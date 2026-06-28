/**
  * Copyright (c) 2023 Rockchip Electronic Co.,Ltd
  *
  * SPDX-License-Identifier: Apache-2.0
  *
  ******************************************************************************
  * @file    rkaudio.h
  * @author  Jair Wu
  * @version v0.1
  * @date    2023.3.28
  * @brief   The rkaudio demo
  ******************************************************************************
  */

#ifndef __RKAUDIO_H__
#define __RKAUDIO_H__

int rkaudio_open(char *cardname, int rate, int bits, int channels);
void rkaudio_close(void);
int rkaudio_read(char *buf, int samples);
void rkaudio_mute(int mute);

#endif

