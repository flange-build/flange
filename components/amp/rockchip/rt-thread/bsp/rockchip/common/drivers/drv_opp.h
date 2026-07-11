/**
  * Copyright (c) 2024 Fuzhou Rockchip Electronics Co., Ltd
  *
  * SPDX-License-Identifier: Apache-2.0
  ******************************************************************************
  * @file    drv_opp.h
  * @version V0.1
  * @brief   otp interface
  *
  * Change Logs:
  * Date           Author          Notes
  * 2024-06-25     Finley.Xiao     first implementation
  *
  ******************************************************************************
  */

#ifndef _DRV_OPP_H_
#define _DRV_OPP_H_

#include <hal_base.h>
#include "hal_otp.h"

#define UINT_MAX (~0U)

struct rk_pvtm_config
{
    uint32_t base;
    uint32_t offset;
    uint64_t freq;
    uint32_t volt;
    uint32_t len_step;
    uint32_t volt_step;
    uint32_t tsadc_ch;
    int ref_temp;
    int temp_prop[2];
};

struct rk_pvtm_table
{
    uint32_t value;
    uint32_t sel;
};

struct rk_opp
{
    uint64_t rate;
    uint32_t volt;
    uint32_t volt_min;
    uint32_t len;
};

struct rk_otp_opp_info
{
    uint16_t min_freq;
    uint16_t max_freq;
    uint8_t volt;
    uint8_t length;
} __packed;

struct rk_opp_otp
{
    uint32_t pvt_len_offset;
    uint32_t opp_info_offset;
};

struct rk_opp_table
{
    char *name;
    struct rk_opp *opps;
    const struct rk_pvtm_config *pvtm_cfg;
    const struct rk_pvtm_table *pvtm_tbl;
    const struct rk_opp_otp *otp;
    struct rk_otp_opp_info *otp_opp_info;
    struct regulator_desc *reg_desc;
    struct rt_mutex lock;
    struct rt_device parent;
    uint32_t num_opps;
    int low_temp;
    uint32_t low_temp_min_volt;
    uint32_t pvtm_sel;
    uint32_t typical_sel;
    uint64_t init_freq;
    uint64_t cur_freq;
    uint32_t cur_volt;
    uint32_t volt_delta_len;
    eCLOCK_Name clk_id;
    ePWR_ID pwr_id;
    bool is_low_temp;
    bool is_suspended;
    rt_err_t (*set_reg_volt)(struct rk_opp_table *opp_table, uint32_t volt);
};

extern struct rk_opp_table g_opp_table[];

void opp_adjust_by_temp(int temp);
rt_err_t opp_set_rate(struct rk_opp_table *opp_table, uint64_t target_freq);
struct rk_opp_table *opp_get_opp_table(eCLOCK_Name clk_id);

#endif // _DRV_OPP_H_
