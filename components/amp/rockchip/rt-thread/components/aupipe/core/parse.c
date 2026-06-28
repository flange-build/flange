/**
  * Copyright (c) 2023 Rockchip Electronics Co., Ltd
  *
  * SPDX-License-Identifier: Apache-2.0
  */

#include "aupipe.h"

int parse_string_parameter(char *string, float *array, char *delim)
{
    int i = 0;

    if (string == NULL)
    {
        LOG_E("the input string is empty");
        return -RT_ERROR;
    }
    if (array == NULL)
    {
        LOG_E("the input array is not allocated space");
        return -RT_ERROR;
    }

    char *token = strtok(string, delim);
    while (token != NULL)
    {
        array[i] = atof(token);
        token = strtok(NULL, delim);
        i++;
    }

    return RT_EOK;
}