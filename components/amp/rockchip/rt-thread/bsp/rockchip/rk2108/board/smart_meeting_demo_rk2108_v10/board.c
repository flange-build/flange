/**
  * Copyright (c) 2023 Rockchip Electronics Co., Ltd
  *
  * SPDX-License-Identifier: Apache-2.0
 */

#include <rthw.h>
#include <rtthread.h>
#include "drv_regulator.h"
#include "board.h"
#include "board_wifibt.h"

#ifdef RT_USING_CRU
#include "drv_clock.h"
#endif

#ifdef RT_USING_CODEC
#include "drv_codecs.h"
#endif

#ifdef RT_USING_AUDIO
#include "rk_audio.h"
#endif

#ifdef RT_USING_PMIC
#include "drv_pmic.h"
#endif

#ifdef RT_USING_UART
#include "drv_uart.h"
#endif

#ifdef RT_USING_PM_DVFS
#include "drv_dvfs.h"
#endif

#ifdef RT_USING_CRU
const struct clk_init clk_inits[] =
{
    INIT_CLK("SCLK_SHRM", SCLK_SHRM, 10 * MHZ),
    INIT_CLK("PCLK_SHRM", PCLK_SHRM, 10 * MHZ),
    INIT_CLK("PCLK_ALIVE", PCLK_ALIVE, 10 * MHZ),
    INIT_CLK("HCLK_ALIVE", HCLK_ALIVE, 10 * MHZ),
    INIT_CLK("HCLK_M4", HCLK_M4, 10 * MHZ),
    INIT_CLK("ACLK_LOGIC", ACLK_LOGIC, 10 * MHZ),
    INIT_CLK("HCLK_LOGIC", HCLK_LOGIC, 10 * MHZ),
    INIT_CLK("PCLK_LOGIC", PCLK_LOGIC, 10 * MHZ),
    INIT_CLK("SCLK_SFC_SRC", SCLK_SFC_SRC, 5 * MHZ),
    INIT_CLK("SCLK_SFC1_SRC", SCLK_SFC1_SRC, 5 * MHZ),
    INIT_CLK("PLL_GPLL", PLL_GPLL, 1188 * MHZ),
    INIT_CLK("PLL_CPLL", PLL_CPLL, 245760000),
    INIT_CLK("SCLK_SFC_SRC", SCLK_SFC_SRC, 50 * MHZ),
    INIT_CLK("HCLK_M4", HCLK_M4, 300 * MHZ),
    INIT_CLK("ACLK_DSP", ACLK_DSP, 400 * MHZ),
    INIT_CLK("ACLK_LOGIC", ACLK_LOGIC, 300 * MHZ),
    INIT_CLK("HCLK_LOGIC", HCLK_LOGIC, 150 * MHZ),
    INIT_CLK("PCLK_LOGIC", PCLK_LOGIC, 150 * MHZ),
    INIT_CLK("SCLK_SHRM", SCLK_SHRM, 300 * MHZ),
    INIT_CLK("PCLK_SHRM", PCLK_SHRM, 100 * MHZ),
    INIT_CLK("PCLK_ALIVE", PCLK_ALIVE, 100 * MHZ),
    INIT_CLK("HCLK_ALIVE", HCLK_ALIVE, 100 * MHZ),
    { /* sentinel */ },
};
#endif

#ifdef RT_USING_CODEC_ES7202
const struct codec_desc codec_es7202 =
{
    .if_type = IF_TYPE_I2C,
    .name = "es7202",
    .i2c_bus = "i2c2",
    .i2c_addr = 0x30,
};
#endif

#ifdef RT_USING_CODEC_ES8156
const struct codec_desc codec_es8156 =
{
    .if_type = IF_TYPE_I2C,
    .name = "es8156",
    .i2c_bus = "i2c2",
    .i2c_addr = 0x08,
    .mclk_gate = CLK_I2S1_8CH_GATE,
    .mclk_always_on = true,
};
#endif

#ifdef RT_USING_MULTI_CODECS
const struct audio_mcodecs_desc rk_mcodecs =
{
    .codecs = { (void *) &codec_es7202, ACDCDIG },
    .capture_mapping = { 4, 2 },
    .playback_mapping = { 0, 0 },
};
#endif

#ifdef RT_USING_AUDIO
const struct audio_card_desc rk_board_audio_cards[] =
{
#ifdef RT_USING_AUDIO_CARD_ACDCDIG
    {
        .name = "adc",
#ifdef RT_USING_ACDCDIG_I2STDM0
        .dai = I2STDM0,
#elif  defined(RT_USING_ACDCDIG_I2STDM1)
        .dai = I2STDM1,
        .rxMap = 0x3012, /* re-mapping sdi2 to path0 */
#elif  defined(RT_USING_ACDCDIG_PDM0) || defined(RT_USING_ACDCDIG_PDM0_SDI2)
        .dai = PDM0,
#endif
#ifdef RT_USING_VAD
        .vad = VAD,
#endif
        .codec = ACDCDIG,
        .capture = true,
        .mclkfs = 2048,
#if defined(RT_USING_ACDCDIG_PDM0) || defined(RT_USING_ACDCDIG_PDM0_SDI2)
        .format = AUDIO_FMT_PDM,
        .pdm_mode = PDM_HIGH_MODE,
#else
        .format = AUDIO_FMT_I2S,
#endif
    },
#endif
#ifdef RT_USING_AUDIO_CARD_ES7202
    {
        .name = "es7202",
        .dai = PDM0,
        .codec = (void *) &codec_es7202,
        .capture = true,
        .format = AUDIO_FMT_PDM,
    },
#endif
#ifdef RT_USING_AUDIO_CARD_ES8156
    {
        .name = "es8156",
        .dai = I2STDM1,
        .codec = (void *) &codec_es8156,
        .playback = true,
        .mclkfs = 256,
        .format = AUDIO_FMT_I2S,
    },
#endif
#ifdef RT_USING_AUDIO_CARD_ES7202_ACDCDIG_COMBINE
    {
        .name = "comb",
        .dai = PDM0,
        .codec = (void *) &rk_mcodecs,
        .capture = true,
        .pdm_mode = PDM_HIGH_MODE,
        .format = AUDIO_FMT_PDM,
    },
#endif
    { /* sentinel */ }
};

#if defined(RT_USING_UART0)
const struct uart_board g_uart0_board =
{
    .baud_rate = UART_BR_1500000,
    .dev_flag = ROCKCHIP_UART_SUPPORT_FLAG_DEFAULT,
    .bufer_size = RT_SERIAL_RB_BUFSZ,
    .name = "uart0",
};
#endif /* RT_USING_UART0 */
#endif

#ifdef RT_USING_PWM_REGULATOR
struct pwr_pwm_info_desc pwr_pwm =
{
    .name = "pwm0",
    .chanel = 1,
    .invert = true,
};
#endif

struct regulator_desc regulators[] =
{
#ifdef RT_USING_PMIC_RK816
    /* BUCK4 */
    {
        .flag = REGULATOR_FLG_I2C8 | REGULATOR_FLG_LOCK,
        .desc.i2c_desc = RK816_BUCK4(RK816_ID_DCDC4, PWR_ID_VCCIO_3V3),
        .desc.i2c_desc.i2c = &pmic_pwr_i2c_desc,
    },
    /* LDO1 */
    {
        .flag = REGULATOR_FLG_I2C8 | REGULATOR_FLG_LOCK,
        .desc.i2c_desc = RK816_LDO1_4(RK816_ID_LDO1, PWR_ID_VCC_3V0_BL),
        .desc.i2c_desc.i2c = &pmic_pwr_i2c_desc,
    },
    /* LDO2 */
    {
        .flag = REGULATOR_FLG_I2C8 | REGULATOR_FLG_LOCK,
        .desc.i2c_desc = RK816_LDO1_4(RK816_ID_LDO2, PWR_ID_VCC_1V8_LDO),
        .desc.i2c_desc.i2c = &pmic_pwr_i2c_desc,
    },
    /* LDO4 */
    {
        .flag = REGULATOR_FLG_I2C8 | REGULATOR_FLG_LOCK,
        .desc.i2c_desc = RK816_LDO1_4(RK816_ID_LDO4, PWR_ID_VCC33_CODEC),
        .desc.i2c_desc.i2c = &pmic_pwr_i2c_desc,
    },
    /* LDO5 */
    {
        .flag = REGULATOR_FLG_I2C8 | REGULATOR_FLG_LOCK,
        .desc.i2c_desc = RK816_LDO5_6(RK816_ID_LDO5, PWR_ID_VCC33_AUDIO),
        .desc.i2c_desc.i2c = &pmic_pwr_i2c_desc,
    },
#endif
    /* RK2108 Internal LDO3 */
    {
        .flag = REGULATOR_FLG_INTREG,
        .desc.intreg_desc = {
            .flag = DESC_FLAG_LINEAR(PWR_FLG_PWR_EN),
            .info = {
                .pwrId = PWR_ID_VCC_AUDIO,
            },
            PWR_INTREG_SHIFT_RUN(&PMU->LDO_CON[0], PMU_LDO_CON0_LDO_AUDIO_SFT_SHIFT),
            PWR_INTREG_SHIFT_EN(&PMU->LDO_CON[0], PMU_LDO_CON0_LDO_AUDIO_EN_SHIFT),
            .voltMask = PMU_LDO_CON0_LDO_AUDIO_SFT_MASK >> PMU_LDO_CON0_LDO_AUDIO_SFT_SHIFT,
                    PWR_DESC_LINEAR_VOLT(1500000, 1650000, 50000),
        },
    },
#ifdef RT_USING_PWM_REGULATOR
    /* CORE PWM */
    {
        .flag = REGULATOR_FLG_PWM,
        .desc.pwm_desc = {
            .pwrId = PWR_ID_CORE,
            .period = 3000,
            .minVolt = 678000,
            .maxVlot = 991000,
            .voltage = 0,
            .pwm = &pwr_pwm,
        },
    },
#endif
    { /* sentinel */ },
};

#ifdef RT_USING_PM_DVFS
extern const struct dvfs_table dvfs_core_table[];
extern const struct dvfs_table dvfs_shrm_table[];
extern const struct dvfs_table dvfs_dsp_table[];
struct rk_dvfs_desc dvfs_data[] =
{
    {
        .clk_id = SCLK_SHRM,
        .pwr_id = PWR_ID_CORE,
        .tbl_idx = 0,
        .table = &dvfs_shrm_table[0],
    },
    {
        .clk_id = HCLK_M4,
        .pwr_id = PWR_ID_CORE,
        .tbl_idx = 0,
        .table = &dvfs_core_table[0],
    },
    {
        .clk_id = ACLK_DSP,
        .pwr_id = PWR_ID_CORE,
        .tbl_idx = 0,
        .table = &dvfs_dsp_table[0],
    },
    { /* sentinel */ },
};
#endif

const struct regulator_init regulator_inits[] =
{
#ifdef RT_USING_PMIC_RK816
    /*
     * Since the feedback of dcdc2 is divided into 60%, so in order to
     * get 1.8v, here it must be set to 1.1v.
     */
    REGULATOR_INIT("dcdc4", PWR_ID_VCCIO_3V3,    3300000, 1, 3300000, 1),
    REGULATOR_INIT("ldo1",  PWR_ID_VCC_3V0_BL,    1800000, 0, 1800000, 0),
    REGULATOR_INIT("ldo2",  PWR_ID_VCC_1V8_LDO,  1800000, 1, 1800000, 0),
    REGULATOR_INIT("ldo4",  PWR_ID_VCC33_CODEC,  3300000, 1, 3300000, 0),
    REGULATOR_INIT("ldo5",  PWR_ID_VCC33_AUDIO,  3300000, 1, 3300000, 0),
#endif
#ifdef RT_USING_PWM_REGULATOR
    REGULATOR_INIT("core_pwm", PWR_ID_CORE,    800000, 1,  800000, 1),
#endif
    REGULATOR_INIT("vcc_audio", PWR_ID_VCC_AUDIO,      0, 0,       0, 0),
    { /* sentinel */ },
};
