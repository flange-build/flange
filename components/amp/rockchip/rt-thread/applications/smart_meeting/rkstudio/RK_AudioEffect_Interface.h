/**
  * Copyright (c) 2023 Rockchip Electronic Co.,Ltd
  *
  * SPDX-License-Identifier: Apache-2.0
  *
  ******************************************************************************
  * @file    RK_AudioEffect_Interface.h
  * @author  Jair Wu
  * @version v0.1
  * @date    2023.4.20
  * @brief   The audio effect
  ******************************************************************************
  */

#ifndef RK_AUDIOEFFECT_INTERFACE_H
#define RK_AUDIOEFFECT_INTERFACE_H

#ifdef __cplusplus
extern "C" {
#endif

extern void *AudioPost_Init(float *pfPara, int swFrmLen);

extern void AudioPost_Process(void *st_ptr_, short int *pfIn, short int *pfOut, short int shwChannelNum, int swFrmLen);

extern void AudioPost_Destroy(void *st_ptr_);

extern void AudioPost_SetPara(void *st_ptr_, float *pfPara, int swFrmLen);

extern void AudioPost_GetPara(void *st_ptr_, float *pfPara);


void *AudioPost_GainSlew_Init(int fs, int chan, int block_size);
int AudioPost_GainSlew_Destroy(void *st_);
int AudioPost_GainSlew_Process(void *st_, short *in, short *out);
int AudioPost_GainSlew_SetParam(void *st_, float *param);

#ifdef __cplusplus
}
#endif

#endif
