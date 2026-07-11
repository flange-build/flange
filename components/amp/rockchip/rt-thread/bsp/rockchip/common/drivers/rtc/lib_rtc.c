/*
 * Copyright (c) 2024 Rockchip Electronics Co., Ltd.
 *
 * SPDX-License-Identifier: Apache-2.0
 *
*/

#include "lib_rtc.h"

#define INT_MAX         ((int)(~0U >> 1))

static const unsigned char rtc_days_in_month[] =
{
    31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31
};

static const unsigned short rtc_ydays[2][13] =
{
    /* Normal years */
    { 0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334, 365 },
    /* Leap years */
    { 0, 31, 60, 91, 121, 152, 182, 213, 244, 274, 305, 335, 366 }
};

bool is_leap_year(unsigned int year)
{
    return (!(year % 4) && (year % 100)) || !(year % 400);
}

int rtc_month_days(unsigned int month, unsigned int year)
{
    return rtc_days_in_month[month] + (is_leap_year(year) && month == 1);
}

int rtc_year_days(unsigned int day, unsigned int month, unsigned int year)
{
    return rtc_ydays[is_leap_year(year)][month] + day - 1;
}

int rtc_valid_tm(struct tm *tm)
{
    if (tm->tm_year < 70 ||
            tm->tm_year > (INT_MAX - 1900) ||
            ((unsigned int)tm->tm_mon) >= 12 ||
            tm->tm_mday < 1 ||
            tm->tm_mday > rtc_month_days(tm->tm_mon,
                                         ((unsigned int)tm->tm_year + 1900)) ||
            ((unsigned int)tm->tm_hour) >= 24 ||
            ((unsigned int)tm->tm_min) >= 60 ||
            ((unsigned int)tm->tm_sec) >= 60)
        return -RT_ERROR;

    return 0;
}

time64_t mktime64(const unsigned int year0, const unsigned int mon0,
                  const unsigned int day, const unsigned int hour,
                  const unsigned int min, const unsigned int sec)
{
    unsigned int mon = mon0, year = year0;

    /* 1..12 -> 11,12,1..10 */
    if (0 >= (int)(mon -= 2))
    {
        mon += 12;  /* Puts Feb last since it has leap day */
        year -= 1;
    }

    return ((((time64_t)
              (year / 4 - year / 100 + year / 400 + 367 * mon / 12 + day) +
              year * 365 - 719499
             ) * 24 + hour /* now have hours - midnight tomorrow handled here */
            ) * 60 + min /* now have minutes */
           ) * 60 + sec; /* finally seconds */
}


time64_t rtc_tm_to_time64(struct tm *tm)
{
    return mktime64(((unsigned int)tm->tm_year + 1900), tm->tm_mon + 1,
                    tm->tm_mday, tm->tm_hour, tm->tm_min, tm->tm_sec);
}
