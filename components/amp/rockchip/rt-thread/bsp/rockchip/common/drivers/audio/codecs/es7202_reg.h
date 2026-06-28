/**
  * Copyright (c) 2023 Rockchip Electronic Co.,Ltd
  *
  * SPDX-License-Identifier: Apache-2.0
  *
  ******************************************************************************
  * @file    es7202_reg.h
  * @author  Jair Wu
  * @version v0.1
  * @date    2023.3.27
  * @brief   The rt-thread codec driver for Rockchip
  ******************************************************************************
  */

#ifndef __ES7202_REG_H__
#define __ES7202_REG_H__

/* ES7202 register space */
#define ES7202_RESET_REG00          0x00
#define ES7202_SOFT_MODE_REG01      0x01
#define ES7202_CLK_DIV_REG02        0x02
#define ES7202_CLK_EN_REG03         0x03
#define ES7202_T1_VMID_REG04        0x04
#define ES7202_T2_VMID_REG05        0x05
#define ES7202_CHIP_STA_REG06       0x06
#define ES7202_PDM_INF_CTL_REG07    0x07
#define ES7202_MISC_CTL_REG08       0x08
#define ES7202_ANALOG_EN_REG10      0x10
#define ES7202_BIAS_VMID_REG11      0x11
#define ES7202_PGA1_BIAS_REG12      0x12
#define ES7202_PGA2_BIAS_REG13      0x13
#define ES7202_MOD1_BIAS_REG14      0x14
#define ES7202_MOD2_BIAS_REG15      0x15
#define ES7202_VREFP_BIAS_REG16     0x16
#define ES7202_VMMOD_BIAS_REG17     0x17
#define ES7202_MODS_BIAS_REG18      0x18
#define ES7202_ANALOG_LP1_REG19     0x19
#define ES7202_ANALOG_LP2_REG1A     0x1A
#define ES7202_ANALOG_MISC1_REG1B   0x1B
#define ES7202_ANALOG_MISC2_REG1C   0x1C
#define ES7202_PGA1_REG1D           0x1D
#define ES7202_PGA2_REG1E           0x1E

#endif
