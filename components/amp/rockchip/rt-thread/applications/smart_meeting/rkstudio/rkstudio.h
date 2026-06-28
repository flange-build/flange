/**
  * Copyright (c) 2023 Rockchip Electronic Co.,Ltd
  *
  * SPDX-License-Identifier: Apache-2.0
  *
  ******************************************************************************
  * @file    rkstudio.h
  * @author  Jair Wu
  * @version v0.1
  * @date    2023.3.28
  * @brief   The rkstudio demo
  ******************************************************************************
  */

#ifndef __RKSTUDIO_H__
#define __RKSTUDIO_H__

int rkstudio_open(char *cardname, int rate, int bits,
                  int channels);
void rkstudio_close(void);
int rkstudio_write(char *buf, int samples);
int rkstudio_get_volume(void);
int rkstudio_set_volume(int percent);
int rkstudio_set_mute(int mute);

#endif

