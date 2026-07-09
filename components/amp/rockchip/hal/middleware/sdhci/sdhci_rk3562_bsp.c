/* SPDX-License-Identifier: BSD-3-Clause */
/*
 * Copyright (c) 2023 Rockchip Electronics Co., Ltd.
 *
 */
#include "blockdev.h"
#include "sdhci.h"

#if defined( DRIVERS_SDHCI ) && defined (SOC_RK3562)
#define EMMC_BASE_ADDR host->ioaddr
#define DWCMSHC_HOST_CTRL3	(EMMC_BASE_ADDR + 0x508)
#define EMMC_EMMC_CTRL		(EMMC_BASE_ADDR + 0x52C)
#define EMMCPHY_BASE		(EMMC_BASE_ADDR)
#define EMMC_DLL_CTRL		(EMMCPHY_BASE + 0x800)
#define EMMC_DLL_RXCLK		(EMMCPHY_BASE + 0x804)
#define EMMC_DLL_TXCLK		(EMMCPHY_BASE + 0x808)
#define EMMC_DLL_STRBIN		(EMMCPHY_BASE + 0x80C)
#define EMMC_DLL_CMDOUT		(EMMCPHY_BASE + 0x810)
#define EMMC_DLL_STATUS0	(EMMCPHY_BASE + 0x840)
#define EMMC_DLL_STATUS1	(EMMCPHY_BASE + 0x844)

void dump_emmc_phy(SdhciHost *host)
{
	PRINT_E("HOST_CONTROL2:  0x%x\n", word32(EMMC_BASE_ADDR + 0x3C));
	PRINT_E("EMMC_CTRL:   0x%x\n", word32(EMMC_EMMC_CTRL));
	PRINT_E("EMMC_0x540:  0x%x\n", word32(EMMC_BASE_ADDR + 0x540));
	PRINT_E("DLL_CTRL:    0x%x\n", word32(EMMC_DLL_CTRL));
	PRINT_E("DLL_RXCLK:   0x%x\n", word32(EMMC_DLL_RXCLK));
	PRINT_E("DLL_TXCLK:   0x%x\n", word32(EMMC_DLL_TXCLK));
	PRINT_E("DLL_STRBIN:  0x%x\n", word32(EMMC_DLL_STRBIN));
	PRINT_E("DLL_CMDOUT:  0x%x\n", word32(EMMC_DLL_CMDOUT));
	PRINT_E("DLL_STATUS0: 0x%x\n", word32(EMMC_DLL_STATUS0));
	PRINT_E("DLL_STATUS1: 0x%x\n", word32(EMMC_DLL_STATUS1));
}

int ConfigMMCPHY(SdhciHost *host,uint32 clock, uint32 timing)
{
	uint32 status, tmp;
	int ret, timeout;
	u8 tap_value;

	word32(EMMC_EMMC_CTRL) |= (1 << 0); /* Host Controller is an eMMC card */
	word32(EMMC_BASE_ADDR + 0x540) = 0x1f << 16;

	if (clock < MMC_CLOCK_100MHZ) {
		word32(EMMC_DLL_CTRL) = 0;
		word32(EMMC_DLL_RXCLK) = (1 << 31);
		word32(EMMC_DLL_TXCLK) = 0;
		word32(EMMC_DLL_CMDOUT) = 0;
		word32(EMMC_EMMC_CTRL) &= ~(1 << 8);
		//word32(EMMC_DLL_CTRL) | = (1<<24);
		goto exit;
	}

	PRINT_E("MMC PHY CLK: %d, timing: %d\n", clock, timing);
	{
		/*Reset DLL*/
		word32(EMMC_DLL_CTRL) = (0x1 << 1);
		udelay(2);
		word32(EMMC_DLL_CTRL)  = 0;
		/*Init DLL*/
		word32(EMMC_DLL_CTRL) = (5 << 16) | (2 << 8) | 0x1;

		/* Wait max 10 ms */
		timeout = 10000;

		while (1) {
			status = word32(EMMC_DLL_STATUS0);
			tmp = (status >> 8) & 0x3;

			if (0x1 == tmp) {
				ret = 0;
				break;
			} else if (0x2 == tmp) {
				ret = -1;
			}

			if (timeout-- <= 0) {
				ret = -2;
			}

			udelay(1);
		}

		if (ret < 0) {
			PRINT_E("Emmc DLL Lock fail %d, 0x%x\n", ret, status);
			return ret;
		}
	}

	tap_value = ((word32(EMMC_DLL_STATUS0) & 0xFF)*2) & 0xFF;
	if (MMC_TIMING_MMC_HS400 == timing) {
		//word32(EMMC_EMMC_CTRL) |= (1 << 8); /* CMD line is sampled using data strobe for HS400 mode */
		word32(EMMC_DLL_TXCLK) = (1 << 29) | (1 << 27) | (1 << 24) | 6;
		word32(EMMC_DLL_RXCLK) = (1 << 31) | (1 << 27);
		word32(EMMC_DLL_STRBIN) = (1 << 27) | (1 << 24) | 0x4;
		word32(EMMC_DLL_CMDOUT) = (2 << 29) |(1 << 28) |(1 << 27)| (1 << 24) | 6;

		word32(EMMC_DLL_RXCLK) |= ((1 << 25) | (tap_value << 8));
		word32(EMMC_DLL_TXCLK) |= ((1 << 25) | (tap_value << 8));
		word32(EMMC_DLL_STRBIN) |= ((1 << 25) | (tap_value << 8));
		word32(EMMC_DLL_CMDOUT) |= ((1 << 25) | (tap_value << 8));
	} else { /* for MMC_TIMING_MMC_HS200*/
		word32(EMMC_DLL_TXCLK) = (1 << 29) | (1 << 27) | (1 << 24) | 10;
		//word32(EMMC_DLL_RXCLK) = (1 << 31) | (1 << 29) |(1 << 27);
		word32(EMMC_DLL_RXCLK) = (1 << 31) |(1 << 27);

		word32(EMMC_DLL_RXCLK) |= ((1 << 25) | (tap_value << 8));
		word32(EMMC_DLL_TXCLK) |= ((1 << 25) | (tap_value << 8));
	}

exit:
	//dump_emmc_phy(host);
	return 0;
}

#define PERI_CRU_BASE           0xFF130000
#define PERICRU_CLKSEL_CON18    0x148
unsigned int SetEmmcClk(unsigned int clock)
{
	unsigned int  clk_sel, div;

	/*GPLL:1188MHz
	2'b00: clk_gpll_mux
	2'b10: xin_osc0_func*/
	if (clock == 0)
		return 0;

	if (clock >= 200000000) {
		clk_sel = 0;
		div = 6;
	} else if (clock >= 150000000) {
		clk_sel = 0;
		div = 8;
	} else if (clock >= 100000000) {
		clk_sel = 0;
		div = 12;
	} else if (clock >= 50000000) {
		clk_sel = 0;
		div = 24;
	} else if (clock >= 24000000) {
		clk_sel = 2;
		div = 1;
	} else {/* 375KHZ*/
		clk_sel = 2;
		div = 64;
	}

	PRINT_E("SetEmmcClk: %d, %d, %d\n", clock, clk_sel, div);
	word32(PERI_CRU_BASE + PERICRU_CLKSEL_CON18) = (((0x3ul<<14)|(0xff<<0))<<16)|(clk_sel<<14)|((div-1)<<0);

	return clock;
}

#endif