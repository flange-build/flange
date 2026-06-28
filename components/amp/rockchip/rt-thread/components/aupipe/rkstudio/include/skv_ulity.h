/**
  * Copyright (c) 2023 Rockchip Electronics Co., Ltd
  *
  * SPDX-License-Identifier: Apache-2.0
  */

#ifndef SKV_ULITY_H
#define SKV_ULITY_H
#include <time.h>
#include <stdio.h>
#include <stdlib.h>

#ifdef __cplusplus
extern "C" {
#endif
typedef unsigned char       SKV_BYTE;
int skv_bigorsmall();
int skv_bytes2floats(SKV_BYTE *in, float *out, int in_size, int bSamples, int bs);
int skv_bytes2floats_datastream(SKV_BYTE *in, float *out, int chan, int in_size, int bSamples);//默认小端

int skv_floats2bytes(float *in, SKV_BYTE *out, int in_size, int bSamples, int bs);
int skv_floats2bytes_datastream(float *in, SKV_BYTE *out, int chan, int in_size, int bSamples);//默认小端

int skv_bytes2shorts(SKV_BYTE *in, short *out, int in_size, int bSamples, int bs);
int skv_shorts2bytes(short *in, SKV_BYTE *out, int in_size, int bSamples, int bs);
int skv_bytes2ints(SKV_BYTE *in, int *out, int in_size, int bSamples, int bs);
int skv_ints2bytes(int *in, SKV_BYTE *out, int in_size, int bSamples, int bs);
int skv_ints2bytes_ch(int **in, SKV_BYTE *out, int in_size, int bSamples, int bs, int ch);

time_t skv_datestr2sec(char *pszDate);
char *skv_strlwr(char *s);
void skv_itoa(int data, char *buffer);

#ifdef __cplusplus
}
#endif

/** @}*/
#endif
