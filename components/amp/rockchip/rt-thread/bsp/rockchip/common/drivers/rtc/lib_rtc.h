/*
 * Copyright (c) 2024 Rockchip Electronics Co., Ltd.
 *
 * SPDX-License-Identifier: Apache-2.0
 *
*/

#ifndef __LIB_RTC_H_
#define __LIB_RTC_H_

#include <time.h>
#include "hal_base.h"

typedef int64_t time64_t;

bool is_leap_year(unsigned int year);
int rtc_month_days(unsigned int month, unsigned int year);
int rtc_year_days(unsigned int day, unsigned int month, unsigned int year);
int rtc_valid_tm(struct tm *tm);
time64_t rtc_tm_to_time64(struct tm *tm);

#endif
