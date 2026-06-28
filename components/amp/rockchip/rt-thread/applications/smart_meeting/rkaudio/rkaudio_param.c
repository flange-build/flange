/**
  * Copyright (c) 2023 Rockchip Electronic Co.,Ltd
  *
  * SPDX-License-Identifier: Apache-2.0
  *
  ******************************************************************************
  * @file    rkaudio_param.c
  * @author  Jair Wu
  * @version v0.1
  * @date    2023.4.20
  * @brief   The rkaudio param parser
  ******************************************************************************
  */

#include <rtthread.h>
#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#include "cJSON.h"
#include "drv_dsp.h"
#include "rkaudio_param.h"
#include "rkaudio_preprocess.h"

#define ERR(fmt, ...)   printf(fmt, ##__VA_ARGS__)
#define LOG(fmt, ...)   //printf(fmt, ##__VA_ARGS__)

#define ALIGN4(x)       ((x + 3) & ~3)

int cjson_array_size(cJSON *arg);

#define BASE_STEP_ON(s, x, rjson)                   \
    s += ALIGN4(rkaudio_##x##_parameter_size(       \
                cJSON_GetObjectItem(rjson, #x)));

#define INIT_PARAM_FROM_JSON(x, rjson, flag)                            \
    void *x = rkaudio_##x##_parameter(cJSON_GetObjectItem(rjson, #x),   \
                                      base, flag);                      \
    parent->x##_param = x;                                              \
    if (!x)                                                             \
        ERR("create " #x " parameter failed\n");

#define GET_NUMBER_MEMBER_FROM_JSON(x)                                  \
    member = cJSON_GetObjectItem(arg, #x);                              \
    param->x = cJSON_GetNumberValue(member);                            \
    LOG("param->" #x " = %f\n", (float)param->x);

#define FILL_ARRAY_FROM_JSON(x, type)                                   \
{                                                                       \
    cJSON *child;                                                       \
    int child_size;                                                     \
    type *array = (type *)param->x;                                     \
    member = cJSON_GetObjectItem(arg, #x);                              \
    int size = cJSON_GetArraySize(member);                              \
    LOG("param->" #x " = [");                                           \
    for (int i = 0; i < size; i++)                                      \
    {                                                                   \
        child = cJSON_GetArrayItem(member, i);                          \
        if (!cJSON_IsArray(child))                                      \
        {                                                               \
            array[i] = cJSON_GetNumberValue(child);                     \
            LOG("%d%s", array[i], i < size - 1 ? ", " : "");            \
        }                                                               \
        else                                                            \
        {                                                               \
            child_size = cJSON_GetArraySize(child);                     \
            LOG("[");                                                   \
            for (int j = 0; j < child_size; j++)                        \
            {                                                           \
                array[i + j] = cJSON_GetNumberValue(cJSON_GetArrayItem(child, j)); \
                LOG("%d%s", array[i + j], j < child_size - 1 ? ", " : ""); \
            }                                                           \
            LOG("]%s", i < (size - 1) ? ",\n" : "");                    \
        }                                                               \
    }                                                                   \
    LOG("]\n");                                                         \
}

#define CREATE_ARRAY_FROM_JSON(x, type)                                 \
{                                                                       \
    member = cJSON_GetObjectItem(arg, #x);                              \
    int size = cJSON_GetArraySize(member);                              \
    type *array = malloc(cjson_array_size(member) * sizeof(type));      \
    LOG("param->" #x "=[");                                             \
    for (int i = 0; i < size; i++)                                      \
    {                                                                   \
        array[i] = cJSON_GetNumberValue(cJSON_GetArrayItem(member, i)); \
        LOG("%d%s", array[i], i < size - 1 ? ", " : "");                \
    }                                                                   \
    LOG("]\n");                                                         \
    param->x = array;                                                   \
}

int cjson_array_size(cJSON *arg)
{
    cJSON *child0;
    int size;

    size = cJSON_GetArraySize(arg);
    child0 = cJSON_GetArrayItem(arg, 0);
    if (!cJSON_IsArray(child0))
        return size;

    return size * cjson_array_size(child0);
}

int rkaudio_dereverb_parameter_size(cJSON *arg)
{
    return sizeof(RKAudioDereverbParam);
}

void *rkaudio_dereverb_parameter(cJSON *arg, void *alloc, uint32_t *pflag)
{
    RKAudioDereverbParam *param;
    cJSON *member;

    param = (RKAudioDereverbParam *)rkaudio_dereverb_param_init(alloc);

    if (!param || !arg)
        return NULL;

    if (cJSON_IsFalse(cJSON_GetObjectItem(arg, "enable")))
        return NULL;

    *pflag |= EN_Dereverberation;

    LOG("%s in %p\n==========\n", __func__, param);
    GET_NUMBER_MEMBER_FROM_JSON(rlsLg);
    GET_NUMBER_MEMBER_FROM_JSON(curveLg);
    GET_NUMBER_MEMBER_FROM_JSON(delay);
    GET_NUMBER_MEMBER_FROM_JSON(forgetting);
    GET_NUMBER_MEMBER_FROM_JSON(T60);
    GET_NUMBER_MEMBER_FROM_JSON(coCoeff);
    LOG("%s out\n\n", __func__);

    return (void *)param;
}

int rkaudio_aes_parameter_size(cJSON *arg)
{
    return sizeof(RKAudioAESParameter);
}

void *rkaudio_aes_parameter(cJSON *arg, void *alloc, uint32_t *pflag)
{
    RKAudioAESParameter *param;
    cJSON *member;

    param = (RKAudioAESParameter *)rkaudio_aes_param_init(alloc);

    if (!param || !arg)
        return NULL;

    if (cJSON_IsFalse(cJSON_GetObjectItem(arg, "enable")))
        return NULL;

    *pflag |= EN_AES;

    LOG("%s in %p\n==========\n", __func__, param);
    GET_NUMBER_MEMBER_FROM_JSON(Beta_Up);
    GET_NUMBER_MEMBER_FROM_JSON(Beta_Down);
    LOG("%s out\n\n", __func__);

    return (void *)param;
}

int rkaudio_nlp_parameter_size(cJSON *arg)
{
    return sizeof(SKVNLPParameter);
}

void *rkaudio_nlp_parameter(cJSON *arg, void *alloc, uint32_t *pflag)
{
    SKVNLPParameter *param;
    cJSON *member;

    param = (SKVNLPParameter *)rkaudio_nlp_param_init(alloc);

    if (!param || !arg)
        return NULL;

    if (cJSON_IsFalse(cJSON_GetObjectItem(arg, "enable")))
        return NULL;

    *pflag |= EN_Nlp;

    LOG("%s in %p\n==========\n", __func__, param);
    FILL_ARRAY_FROM_JSON(g_ashwAecBandNlpPara_16k, short int);
    LOG("%s out\n\n", __func__);

    return (void *)param;
}

int rkaudio_anr_parameter_size(cJSON *arg)
{
    return sizeof(SKVANRParam);
}

void *rkaudio_anr_parameter(cJSON *arg, void *alloc, uint32_t *pflag)
{
    SKVANRParam *param;
    cJSON *member;

    param = (SKVANRParam *)rkaudio_anr_param_init(alloc);

    if (!param || !arg)
        return NULL;

    if (cJSON_IsFalse(cJSON_GetObjectItem(arg, "enable")))
        return NULL;

    *pflag |= EN_Anr;

    LOG("%s in %p\n==========\n", __func__, param);
    GET_NUMBER_MEMBER_FROM_JSON(noiseFactor);
    GET_NUMBER_MEMBER_FROM_JSON(swU);
    GET_NUMBER_MEMBER_FROM_JSON(PsiMin);
    GET_NUMBER_MEMBER_FROM_JSON(PsiMax);
    GET_NUMBER_MEMBER_FROM_JSON(fGmin);
    LOG("%s out\n\n", __func__);

    return (void *)param;
}

int rkaudio_agc_parameter_size(cJSON *arg)
{
    return sizeof(RKAGCParam);
}

void *rkaudio_agc_parameter(cJSON *arg, void *alloc, uint32_t *pflag)
{
    RKAGCParam *param;
    cJSON *member;

    param = (RKAGCParam *)rkaudio_agc_param_init(alloc);

    if (!param || !arg)
        return NULL;

    if (cJSON_IsFalse(cJSON_GetObjectItem(arg, "enable")))
        return NULL;

    *pflag |= EN_Agc;

    LOG("%s in %p\n==========\n", __func__, param);
    GET_NUMBER_MEMBER_FROM_JSON(attack_time);
    GET_NUMBER_MEMBER_FROM_JSON(release_time);
    GET_NUMBER_MEMBER_FROM_JSON(max_gain);
    GET_NUMBER_MEMBER_FROM_JSON(max_peak);
    GET_NUMBER_MEMBER_FROM_JSON(fRth0);
    GET_NUMBER_MEMBER_FROM_JSON(fRk0);
    GET_NUMBER_MEMBER_FROM_JSON(fRth1);
    GET_NUMBER_MEMBER_FROM_JSON(fs);
    GET_NUMBER_MEMBER_FROM_JSON(frmlen);
    GET_NUMBER_MEMBER_FROM_JSON(attenuate_time);
    GET_NUMBER_MEMBER_FROM_JSON(fRth2);
    GET_NUMBER_MEMBER_FROM_JSON(fRk1);
    GET_NUMBER_MEMBER_FROM_JSON(fRk2);
    GET_NUMBER_MEMBER_FROM_JSON(fLineGainDb);
    GET_NUMBER_MEMBER_FROM_JSON(swSmL0);
    GET_NUMBER_MEMBER_FROM_JSON(swSmL1);
    GET_NUMBER_MEMBER_FROM_JSON(swSmL2);
    LOG("%s out\n\n", __func__);

    return (void *)param;
}

int rkaudio_cng_parameter_size(cJSON *arg)
{
    return sizeof(RKCNGParam);
}

void *rkaudio_cng_parameter(cJSON *arg, void *alloc, uint32_t *pflag)
{
    RKCNGParam *param;
    cJSON *member;

    param = (RKCNGParam *)rkaudio_cng_param_init(alloc);

    if (!param || !arg)
        return NULL;

    if (cJSON_IsFalse(cJSON_GetObjectItem(arg, "enable")))
        return NULL;

    *pflag |= EN_CNG;

    LOG("%s in %p\n==========\n", __func__, param);
    GET_NUMBER_MEMBER_FROM_JSON(fGain);
    GET_NUMBER_MEMBER_FROM_JSON(fMpy);
    GET_NUMBER_MEMBER_FROM_JSON(fSmoothAlpha);
    GET_NUMBER_MEMBER_FROM_JSON(fSpeechGain);
    LOG("%s out\n\n", __func__);

    return (void *)param;
}

int rkaudio_dtd_parameter_size(cJSON *arg)
{
    return sizeof(RKDTDParam);
}

void *rkaudio_dtd_parameter(cJSON *arg, void *alloc, uint32_t *pflag)
{
    RKDTDParam *param;
    cJSON *member;

    param = (RKDTDParam *)rkaudio_dtd_param_init(alloc);

    if (!param || !arg)
        return NULL;

    if (cJSON_IsFalse(cJSON_GetObjectItem(arg, "enable")))
        return NULL;

    *pflag |= EN_STDT;

    LOG("%s in %p\n==========\n", __func__, param);
    GET_NUMBER_MEMBER_FROM_JSON(ksiThd_high);
    GET_NUMBER_MEMBER_FROM_JSON(ksiThd_low);
    LOG("%s out\n\n", __func__);

    return (void *)param;
}

int rkaudio_eq_parameter_size(cJSON *arg)
{
    return sizeof(RKaudioEqParam);
}

void *rkaudio_eq_parameter(cJSON *arg, void *alloc, uint32_t *pflag)
{
    RKaudioEqParam *param;
    cJSON *member;

    param = (RKaudioEqParam *)rkaudio_eq_param_init(alloc);

    if (!param || !arg)
        return NULL;

    if (cJSON_IsFalse(cJSON_GetObjectItem(arg, "enable")))
        return NULL;

    *pflag |= EN_EQ;

    LOG("%s in %p\n==========\n", __func__, param);
    GET_NUMBER_MEMBER_FROM_JSON(shwParaLen);
    FILL_ARRAY_FROM_JSON(pfCoeff, short);
    LOG("%s out\n\n", __func__);

    return (void *)param;
}

int rkaudio_aec_parameter_size(cJSON *arg)
{
    int size = cJSON_GetArraySize(cJSON_GetObjectItem(arg, "Array_list"));
    return ALIGN4(sizeof(SKVAECParameter)) + size * sizeof(short int);
}

void *rkaudio_aec_parameter(cJSON *arg, void *alloc, uint32_t *pflag)
{
    SKVAECParameter *param;
    cJSON *member;

    param = (SKVAECParameter *)rkaudio_aec_param_init(alloc);

    if (!param || !arg)
        return NULL;

    if (cJSON_IsFalse(cJSON_GetObjectItem(arg, "enable")))
        return NULL;

    *pflag |= RKAUDIO_EN_AEC;

    LOG("%s in %p\n==========\n", __func__, param);
    GET_NUMBER_MEMBER_FROM_JSON(pos);
    GET_NUMBER_MEMBER_FROM_JSON(drop_ref_channel);
    GET_NUMBER_MEMBER_FROM_JSON(model_aec_en);
    GET_NUMBER_MEMBER_FROM_JSON(delay_len);
    GET_NUMBER_MEMBER_FROM_JSON(look_ahead);
    FILL_ARRAY_FROM_JSON(Array_list, short int)
//    CREATE_ARRAY_FROM_JSON(Array_list, short int)
    LOG("%s out\n\n", __func__);

    return (void *)param;
}

int rkaudio_rx_parameter_size(cJSON *arg)
{
    return sizeof(RkaudioRxParam);
}

void *rkaudio_rx_parameter(cJSON *arg, void *alloc, uint32_t *pflag)
{
    char *base = alloc;
    RkaudioRxParam *parent = alloc;
    uint32_t flag = 0;

    if (!alloc || !arg)
        return NULL;

    if (cJSON_IsFalse(cJSON_GetObjectItem(arg, "enable")))
        return NULL;

    *pflag |= RKAUDIO_EN_RX;

    LOG("%s in %p\n==========\n", __func__, parent);
    base += ALIGN4(sizeof(RkaudioRxParam));
    INIT_PARAM_FROM_JSON(anr, arg, &flag);
    parent->model_rx_en = flag;
    printf("RkaudioRxParam     en:%lx\n", flag);
    LOG("%s out\n\n", __func__);

    return (void *)parent;
}

int rkaudio_bf_parameter_size(cJSON *arg)
{
    int size;

    size = ALIGN4(sizeof(SKVPreprocessParam));
    BASE_STEP_ON(size, dereverb, arg);
    BASE_STEP_ON(size, aes, arg);
    BASE_STEP_ON(size, nlp, arg);
    BASE_STEP_ON(size, anr, arg);
    BASE_STEP_ON(size, agc, arg);
    BASE_STEP_ON(size, cng, arg);
    BASE_STEP_ON(size, dtd, arg);
    BASE_STEP_ON(size, eq, arg);

    return size;
}

void *rkaudio_bf_parameter(cJSON *arg, void *alloc, uint32_t *pflag)
{
    char *base = alloc;
    SKVPreprocessParam *parent;
    SKVPreprocessParam *param;
    cJSON *member;
    uint32_t flag = 0;

    if (cJSON_IsFalse(cJSON_GetObjectItem(arg, "enable")))
        return NULL;

    *pflag |= RKAUDIO_EN_BF;

    param = parent = rkaudio_preprocess_param_init(alloc);

    LOG("%s in %p\n==========\n", __func__, param);
    GET_NUMBER_MEMBER_FROM_JSON(Targ);
    GET_NUMBER_MEMBER_FROM_JSON(ref_pos);
    GET_NUMBER_MEMBER_FROM_JSON(num_ref_channel);
    GET_NUMBER_MEMBER_FROM_JSON(drop_ref_channel);

    if (cJSON_IsTrue(cJSON_GetObjectItem(arg, "fastaec")))
        flag |= EN_Fastaec;
    if (cJSON_IsTrue(cJSON_GetObjectItem(arg, "wakeup")))
        flag |= EN_Wakeup;
    if (cJSON_IsTrue(cJSON_GetObjectItem(arg, "gsc")))
        flag |= EN_GSC;
    if (cJSON_IsTrue(cJSON_GetObjectItem(arg, "gsc_method")))
        flag |= GSC_Method;
    if (cJSON_IsTrue(cJSON_GetObjectItem(arg, "fix")))
        flag |= EN_Fix;
    if (cJSON_IsTrue(cJSON_GetObjectItem(arg, "chn_select")))
        flag |= EN_CHN_SELECT;

    base += ALIGN4(sizeof(SKVPreprocessParam));
    INIT_PARAM_FROM_JSON(dereverb, arg, &flag);
    BASE_STEP_ON(base, dereverb, arg);
    INIT_PARAM_FROM_JSON(aes, arg, &flag);
    BASE_STEP_ON(base, aes, arg);
    INIT_PARAM_FROM_JSON(nlp, arg, &flag);
    BASE_STEP_ON(base, nlp, arg);
    INIT_PARAM_FROM_JSON(anr, arg, &flag);
    BASE_STEP_ON(base, anr, arg);
    INIT_PARAM_FROM_JSON(agc, arg, &flag);
    BASE_STEP_ON(base, agc, arg);
    INIT_PARAM_FROM_JSON(cng, arg, &flag);
    BASE_STEP_ON(base, cng, arg);
    INIT_PARAM_FROM_JSON(dtd, arg, &flag);
    BASE_STEP_ON(base, dtd, arg);
    INIT_PARAM_FROM_JSON(eq, arg, &flag);

    parent->model_bf_en = flag;
    printf("SKVPreprocessParam en:%lx\n", flag);
    LOG("%s out\n\n", __func__);

    return (void *)parent;
}

int rkaudio_param_size_old(void)
{
    return ALIGN4(sizeof(struct bf_cfg_param)) +
           ALIGN4(sizeof(RKAUDIOParam)) +
           ALIGN4(sizeof(SKVAECParameter)) +
           ALIGN4(sizeof(RkaudioRxParam)) +
           ALIGN4(sizeof(SKVPreprocessParam)) +
           ALIGN4(sizeof(RKAudioDereverbParam)) +
           ALIGN4(sizeof(RKAudioAESParameter)) +
           ALIGN4(sizeof(SKVNLPParameter)) +
           ALIGN4(sizeof(SKVANRParam)) +
           ALIGN4(sizeof(RKAGCParam)) +
           ALIGN4(sizeof(RKCNGParam)) +
           ALIGN4(sizeof(RKDTDParam)) +
           ALIGN4(sizeof(RKaudioEqParam));
}

int rkaudio_param_size(cJSON *arg)
{
    int size;

    size = ALIGN4(sizeof(struct bf_cfg_param)) +
           ALIGN4(sizeof(RKAUDIOParam));

    BASE_STEP_ON(size, aec, arg);
    BASE_STEP_ON(size, rx, arg);
    BASE_STEP_ON(size, bf, arg);

    return size;
}

void rkaudio_param_free(void *alloc)
{
    rkdsp_free(alloc);
}

void *rkaudio_param_from_file(char *file, int *size)
{
    struct bf_cfg_param *bf_cfg;
    FILE *fd = fopen(file, "rb");
    char *buf;
    char *base;
    size_t fsize;
    RKAUDIOParam *parent;
    uint32_t flag = 0;

    cJSON *root = NULL;

    if (!fd) {
        ERR("Open %s failed\n", file);
        goto err1;
    }

    fseek(fd, 0, SEEK_END);
    fsize = ftell(fd);
    fseek(fd, 0, SEEK_SET);
    buf = malloc(fsize);
    if (!buf) {
        ERR("Malloc %d failed\n", fsize);
        fclose(fd);
        goto err1;
    }

    fread(buf, 1, fsize, fd);
    fclose(fd);

    root = cJSON_Parse(buf);
    if (!root) {
        ERR("Parse json failed\n");
        goto err2;
    }
    if (!root->string && cJSON_IsObject(root) && root->child) {
        root = root->child;
        printf("switch to child: %s\n", root->string);
    }

    *size = rkaudio_param_size(root);
    bf_cfg = (struct bf_cfg_param *)rkdsp_malloc(*size);
    if (!bf_cfg) {
        ERR("malloc %d failed\n", *size);
        goto err3;
    }
    LOG("param size = %d, bf_cfg = %p\n", *size, bf_cfg);

    parent = (RKAUDIOParam *)((char *)bf_cfg + ALIGN4(sizeof(struct bf_cfg_param)));
    base = (char *)parent + ALIGN4(sizeof(RKAUDIOParam));

    INIT_PARAM_FROM_JSON(aec, root, &flag);
    BASE_STEP_ON(base, aec, root);
    INIT_PARAM_FROM_JSON(rx, root, &flag);
    BASE_STEP_ON(base, rx, root);
    INIT_PARAM_FROM_JSON(bf, root, &flag);

    parent->model_en = flag;
    printf("RKAUDIOParam       en:%lx %p\n", flag, parent);
    bf_cfg->rkaudio_param = (uint32_t) parent;

    cJSON_Delete(root);

    free(buf);

    return bf_cfg;
err3:
    cJSON_Delete(root);
err2:
    free(buf);
err1:
    *size = sizeof(struct bf_cfg_param);
    bf_cfg = rkdsp_malloc(*size);
    if (bf_cfg)
        memset(bf_cfg, 0, *size);

    return bf_cfg;
}

