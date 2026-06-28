/**
  * Copyright (c) 2023 Rockchip Electronics Co., Ltd
  *
  * SPDX-License-Identifier: Apache-2.0
  */

#ifndef _RKAUDIO_COMMON_H
#define _RKAUDIO_COMMON_H
#ifdef __cplusplus
extern "C" {
#endif
#define Safe_deno 1e-10

typedef struct _BlockPro
{
    int         nSamplingRate;  /* sample rate of the audio block */
    int         bitRate;    /* bit rate of the audio block */
    int         nBlockSize;     /* block size of the audio block */
    int         nReserve0;      /* reserved */
    int         nReserve1;      /* reserved */
} BlockPro;

typedef struct _Block
{
    BlockPro *pBlockProperties;
    float *pSamples;       /* pointer to the sample buffer */
} Block;

typedef struct _BlockAlgo   //BlockAlgo¹Ì¶¨·ÖÅä4*3×Ö½Ú
{
    int     nInputs;        /* number of input pins */
    int     nOutputs;       /* number of output pins */
    BlockPro *block_pro;        /* pointer to the array of block i/o mem structure */
    int     method_type;
    //int     nGrowth;        /* indicates the growth count */
    //int     nGrowthB;       /* secondary growth count */
    float *pParam;         /* pointer to the parameter memory */
    void *AlgoCore;         /* pointer to the */
    float *pState;         /* pointer to the state memory */
    //float* pScratchDM;     /* pointer to the scratch in DM memory */
    //float* pScratchPM;     /* pointer to the scratch in PM memory */
    float *pStateB;        /* pointer to the state memory B */
    float *pStateC;        /* pointer to the state memory C */
    //float* pExtPreState;   /* pointer to extended precision state memory */
    //int* pExtSymbols;    /* pointer to the symbol address table */
} BlockAlgo;

#ifdef __cplusplus
}
#endif

#endif  /* _SKV_TYPES_H */