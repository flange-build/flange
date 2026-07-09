/* SPDX-License-Identifier: BSD-3-Clause */
/*
 * Copyright (c) 2023 Rockchip Electronics Co., Ltd.
 *
 */

#include "blockdev.h"
#include "sdhci.h"

#ifdef DRIVERS_SDHCI

#define SDHCI_ARASAN_VENDOR_REGISTER	0x78
#define VENDOR_ENHANCED_STROBE		BIT(0)
#define EMMC_EMMC_CTRL				0x52C

extern inline SdhciHost *mmc_get_host(void);
extern int ConfigMMCPHY(SdhciHost *host,uint32 clock, uint32 timing);

#define MAX_TUNING_LOOP 40
#define SDHCI_MAX_NUM_DESCS     2048
#define SDHCI_BYTES_PER_DESC    12
#define SDHCI_DESCS_BUF_SIZE    (SDHCI_MAX_NUM_DESCS*SDHCI_BYTES_PER_DESC)

uint32_t sdhci_adma_descs[SDHCI_DESCS_BUF_SIZE / 4];

static inline void mmc_retune_needed(SdhciHost *host)
{
	if (host->mmc_ctrlr.can_retune)
		host->mmc_ctrlr.need_retune = 1;

	mmc_debug("can_retune:%d, need_retune:%d\n", host->mmc_ctrlr.can_retune, host->mmc_ctrlr.need_retune);
}

void sdhci_reset(SdhciHost *host, u8 mask)
{
	unsigned long timeout;

	/* Wait max 100 ms */
	timeout = 100000;
	sdhci_writeb(host, mask, SDHCI_SOFTWARE_RESET);

	while (sdhci_readb(host, SDHCI_SOFTWARE_RESET) & mask) {
		if (timeout == 0) {
			mmc_error("Reset 0x%x never completed.\n", (int)mask);
			return;
		}

		timeout--;
		udelay(1);
	}
}

int sdhci_enable_clock(int en)
{
	unsigned int div, clk, timeout;
	SdhciHost *host = mmc_get_host();

	clk = sdhci_readw(host, SDHCI_CLOCK_CONTROL);
	//PRINT_E("sdhci_enable_clock2:%d, 0x%x\n", en, clk);

	if (0 == en) {
		sdhci_writew(host, 0, SDHCI_CLOCK_CONTROL);
		return 0;
	}

	clk = SDHCI_CLOCK_INT_EN;
	sdhci_writew(host, clk, SDHCI_CLOCK_CONTROL);

	/* Wait max 20 ms */
	timeout = 20000;
	while (!((clk = sdhci_readw(host, SDHCI_CLOCK_CONTROL))
		 & SDHCI_CLOCK_INT_STABLE)) {
		if (timeout == 0) {
			PRINT_E("Internal clock never stabilised.\n", "");
			return -1;
		}

		timeout--;
		udelay(1);
	}

	clk |= SDHCI_CLOCK_CARD_EN;
	sdhci_writew(host, clk, SDHCI_CLOCK_CONTROL);

	return 0;
}

static void sdhci_cmd_done(SdhciHost *host, MmcCommand *cmd)
{
	int i;

	if (cmd->resp_type & MMC_RSP_136) {
		/* CRC is stripped so we need to do some shifting. */
		for (i = 0; i < 4; i++) {
			cmd->response[i] = sdhci_readl(host,
						       SDHCI_RESPONSE + (3 - i) * 4) << 8;

			if (i != 3)
				cmd->response[i] |= sdhci_readb(host,
								SDHCI_RESPONSE + (3 - i) * 4 - 1);
		}
	} else {
		cmd->response[0] = sdhci_readl(host, SDHCI_RESPONSE);
	}
}

static void sdhci_transfer_pio(SdhciHost *host, MmcData *data)
{
	int i;
	char *offs;

	for (i = 0; i < data->blocksize; i += 4) {
		offs = data->dest + i;

		if (data->flags == MMC_DATA_READ)
			*(u32 *)offs = sdhci_readl(host, SDHCI_BUFFER);
		else
			sdhci_writel(host, *(u32 *)offs, SDHCI_BUFFER);
	}
}

static int sdhci_transfer_data(SdhciHost *host, MmcData *data,
			       unsigned int start_addr)
{
	unsigned int stat, rdy, mask, timeout, block = 0;
	bool transfer_done = false;

#ifdef CONFIG_MMC_SDHCI_SDMA
	unsigned char ctrl;
	ctrl = sdhci_readb(host, SDHCI_HOST_CONTROL);
	ctrl &= ~SDHCI_CTRL_DMA_MASK;
	sdhci_writeb(host, ctrl, SDHCI_HOST_CONTROL);
#endif

	timeout = 1000000;
	rdy = SDHCI_INT_SPACE_AVAIL | SDHCI_INT_DATA_AVAIL;
	mask = SDHCI_DATA_AVAILABLE | SDHCI_SPACE_AVAILABLE;

	do {
		stat = sdhci_readl(host, SDHCI_INT_STATUS);

		if (stat & SDHCI_INT_ERROR) {
			mmc_error("Error detected in status(0x%X)!\n", stat);
			return -1;
		}

		if (!transfer_done && (stat & rdy)) {
			if (!(sdhci_readl(host, SDHCI_PRESENT_STATE) & mask))
				continue;

			sdhci_writel(host, rdy, SDHCI_INT_STATUS);

			if (stat & SDHCI_INT_DATA_AVAIL) {
				u32 command;

				command = SDHCI_GET_CMD(sdhci_readw(host, SDHCI_COMMAND));
				if (command == MMC_SEND_TUNING_BLOCK_HS200) {
					host->tuning_done = 1;
					mmc_debug("auto_tuning_done stat:0x%x\n", stat);
					//wake_up(&host->buf_ready_int);
					return 0;
				}
			}

			sdhci_transfer_pio(host, data);
			data->dest += data->blocksize;
			if (++block >= data->blocks) {
				transfer_done = true;
				break;
			}
		}

#ifdef CONFIG_MMC_SDHCI_SDMA
		if (!transfer_done && (stat & SDHCI_INT_DMA_END)) {
			sdhci_writel(host, SDHCI_INT_DMA_END, SDHCI_INT_STATUS);
			start_addr &= ~(SDHCI_DEFAULT_BOUNDARY_SIZE - 1);
			start_addr += SDHCI_DEFAULT_BOUNDARY_SIZE;
			sdhci_writel(host, start_addr, SDHCI_DMA_ADDRESS);
		}
#endif

		if (timeout-- > 0)
			udelay(10);
		else {
			mmc_error("SDHCI:Transfer data timeout status(0x%X)\n", sdhci_readl(host, SDHCI_INT_STATUS));
			return -1;
		}
	} while (!(stat & SDHCI_INT_DATA_END));

	return 0;
}

static void sdhci_alloc_adma_descs(SdhciHost *host, u32 need_descriptors)
{
#if 0

	if (host->adma_descs) {
		if (host->adma_desc_count < need_descriptors) {
			/* Previously allocated array is too small */
			free(host->adma_descs);
			host->adma_desc_count = 0;
			host->adma_descs = NULL;
		}
	}

	if (!host->adma_descs) {
		host->adma_descs = xmalloc(need_descriptors *
					   sizeof(*host->adma_descs));
		host->adma_desc_count = need_descriptors;
	}

#endif

	if (need_descriptors > SDHCI_MAX_NUM_DESCS)
		mmc_error("shci dma desc overflow\n", "");

	host->adma_descs = (SdhciAdma *)sdhci_adma_descs;
	host->adma_desc_count = need_descriptors;

	memset(host->adma_descs, 0, sizeof(*host->adma_descs) *
	       need_descriptors);
}

static void sdhci_alloc_adma64_descs(SdhciHost *host, u32 need_descriptors)
{
#if 0

	if (host->adma64_descs) {
		if (host->adma_desc_count < need_descriptors) {
			/* Previously allocated array is too small */
			free(host->adma64_descs);
			host->adma_desc_count = 0;
			host->adma64_descs = NULL;
		}
	}

	if (!host->adma64_descs) {
		host->adma64_descs = xmalloc(need_descriptors *
					     sizeof(*host->adma64_descs));
		host->adma_desc_count = need_descriptors;
	}

#endif

	if (need_descriptors > SDHCI_MAX_NUM_DESCS)
		mmc_error("shci dma desc overflow\n", "");

	host->adma64_descs = (SdhciAdma64 *)sdhci_adma_descs;
	host->adma_desc_count = need_descriptors;

	memset(host->adma64_descs, 0, sizeof(*host->adma64_descs) *
	       need_descriptors);
}

static int sdhci_setup_adma(SdhciHost *host, MmcData *data)
{
	int i, togo, need_descriptors;
	char *buffer_data;
	u16 attributes;

	togo = data->blocks * data->blocksize;

	if (!togo) {
		mmc_error("%s: MmcData corrupted: %d blocks of %d bytes\n",
			  __func__, data->blocks, data->blocksize);
		return -1;
	}

	need_descriptors = 1 +  togo / SDHCI_MAX_PER_DESCRIPTOR;

	if (host->dma64)
		sdhci_alloc_adma64_descs(host, need_descriptors);
	else
		sdhci_alloc_adma_descs(host, need_descriptors);

	buffer_data = data->dest;

	/* Now set up the descriptor chain. */
	for (i = 0; togo; i++) {
		unsigned desc_length;

		if (togo < SDHCI_MAX_PER_DESCRIPTOR)
			desc_length = togo;
		else
			desc_length = SDHCI_MAX_PER_DESCRIPTOR;

		togo -= desc_length;

		attributes = SDHCI_ADMA_VALID | SDHCI_ACT_TRAN;

		if (togo == 0)
			attributes |= SDHCI_ADMA_END;

		if (host->dma64) {
			host->adma64_descs[i].addr = (uintptr_t) buffer_data;
			host->adma64_descs[i].addr_hi = 0;
			host->adma64_descs[i].length = desc_length;
			host->adma64_descs[i].attributes = attributes;

		} else {
			host->adma_descs[i].addr = (uintptr_t) buffer_data;
			host->adma_descs[i].length = desc_length;
			host->adma_descs[i].attributes = attributes;
		}

		buffer_data += desc_length;
	}

	HAL_DCACHE_CleanInvalidateByRange(data->dest,
				       data->blocks * data->blocksize);

	if (host->dma64) {
		HAL_DCACHE_CleanInvalidateByRange(host->adma64_descs,
					       host->adma_desc_count *
					       sizeof(*host->adma64_descs));
		sdhci_writel(host, (uintptr_t) host->adma64_descs,
			     SDHCI_ADMA_ADDRESS);
	} else {
		HAL_DCACHE_CleanInvalidateByRange(host->adma_descs,
					       host->adma_desc_count *
					       sizeof(*host->adma_descs));
		sdhci_writel(host, (uintptr_t) host->adma_descs,
			     SDHCI_ADMA_ADDRESS);
	}

	return 0;
}

#define DWCMSHC_HOST_CTRL3	0x508
#define EMMC_DLL_CTRL		0x800
#define EMMC_DLL_RXCLK		0x804
#define EMMC_DLL_TXCLK		0x808
#define EMMC_DLL_STRBIN		0x80C
#define EMMC_DLL_STATUS0	0x840
#define EMMC_DLL_STATUS1	0x844

static int sdhci_complete_adma(SdhciHost *host, MmcCommand *cmd, MmcData *data)
{
	int retry;
	u32 stat = 0, mask;
	unsigned long data_len = data->blocks * data->blocksize;

	mask = SDHCI_INT_RESPONSE | SDHCI_INT_ERROR;

	retry = 100000; /* Command should be done in way less than 10 ms. */

	while (--retry) {
		stat = sdhci_readl(host, SDHCI_INT_STATUS);

		if (stat & mask)
			break;

		udelay(1);
	}

	sdhci_writel(host, SDHCI_INT_RESPONSE, SDHCI_INT_STATUS);

	if  (retry <= 0) {
		mmc_error("%s: cmd timeout! stat 0x%x, cmd 0x%x\n",
			  __func__, stat, sdhci_readw(host, SDHCI_COMMAND));
	}

	if (retry && !(stat & SDHCI_INT_ERROR)) {
		/* Command OK, let's wait for data transfer completion. */
		mask = SDHCI_INT_DATA_END |
		       SDHCI_INT_ERROR | SDHCI_INT_ADMA_ERROR;

		/* Transfer should take 10 seconds tops. */
		retry = 5 * 1000 * 1000;

		while (--retry) {
			stat = sdhci_readl(host, SDHCI_INT_STATUS);

			if (stat & mask)
				break;

			udelay(1);
		}

		sdhci_writel(host, stat, SDHCI_INT_STATUS);

		if (retry && !(stat & SDHCI_INT_ERROR)) {
			sdhci_cmd_done(host, cmd);
			if (data->flags & MMC_DATA_READ)
				HAL_DCACHE_InvalidateByRange(data->dest, data_len);
			return 0;
		}
	}

	mmc_retune_needed(host);
	mmc_error("%s: transfer error, stat %#x, adma error %#x, retry %d, cmd 0x%x\n",
		  __func__, stat, sdhci_readl(host, SDHCI_ADMA_ERROR), retry,
		  sdhci_readw(host, SDHCI_COMMAND));

	sdhci_reset(host, SDHCI_RESET_CMD);
	sdhci_reset(host, SDHCI_RESET_DATA);

	if (stat & SDHCI_INT_TIMEOUT)
		return MMC_TIMEOUT;
	else if (stat & SDHCI_INT_DATA_TIMEOUT)
		return MMC_DATA_TOUT_ERR;
	else
		return MMC_COMM_ERR;
}

static int sdhci_send_command(MmcCtrlr *mmc_ctrl, MmcCommand *cmd,
			      MmcData *data)
{
	unsigned int stat = 0;
	int ret = 0;
	u32 mask, flags;
	unsigned int timeout, start_addr = 0;
	uint64_t start;
	//SdhciHost *host = container_of(mmc_ctrl, SdhciHost, mmc_ctrlr);
	SdhciHost *host = mmc_get_host();

	//mmc_error("cmd%d\n", cmd->cmdidx);
	/* Wait max 1 s */
	timeout = 1000;
	mask = SDHCI_CMD_INHIBIT;

	if (data)
		mask |= SDHCI_DATA_INHIBIT;

	/* We shouldn't wait for data inihibit for stop commands, even
	   though they might use busy signaling */
	if (cmd->cmdidx == MMC_CMD_STOP_TRANSMISSION)
		mask &= ~SDHCI_DATA_INHIBIT;

	while (sdhci_readl(host, SDHCI_PRESENT_STATE) & mask) {
		if (timeout == 0) {
			mmc_error("Controller never released inhibit bit(s), "
				  "present state %#8.8x.\n",
				  sdhci_readl(host, SDHCI_PRESENT_STATE));
			return MMC_COMM_ERR;
		}

		timeout--;
		udelay(1000);
	}

	sdhci_writel(host, SDHCI_INT_ALL_MASK, SDHCI_INT_STATUS);

	mask = SDHCI_INT_RESPONSE;

	if (!(cmd->resp_type & MMC_RSP_PRESENT))
		flags = SDHCI_CMD_RESP_NONE;
	else if (cmd->resp_type & MMC_RSP_136)
		flags = SDHCI_CMD_RESP_LONG;
	else if (cmd->resp_type & MMC_RSP_BUSY) {
		flags = SDHCI_CMD_RESP_SHORT_BUSY;

		if (data)
			mask |= SDHCI_INT_DATA_END;
	} else
		flags = SDHCI_CMD_RESP_SHORT;

	if (cmd->resp_type & MMC_RSP_CRC)
		flags |= SDHCI_CMD_CRC;

	if (cmd->resp_type & MMC_RSP_OPCODE)
		flags |= SDHCI_CMD_INDEX;

	if (data)
		flags |= SDHCI_CMD_DATA;

	if (cmd->cmdidx == MMC_SEND_TUNING_BLOCK ||
	    cmd->cmdidx == MMC_SEND_TUNING_BLOCK_HS200) {
		mask &= ~SDHCI_INT_RESPONSE;
		mask |= SDHCI_INT_DATA_AVAIL;
		flags |= SDHCI_CMD_DATA;
	}

	/* Set Transfer mode regarding to data flag */
	if (data) {
		u16 mode = 0;

		sdhci_writeb(host, 0xe, SDHCI_TIMEOUT_CONTROL);
		sdhci_writew(host, SDHCI_MAKE_BLKSZ(SDHCI_DEFAULT_BOUNDARY_ARG,
						    data->blocksize),
			     SDHCI_BLOCK_SIZE);

		mode = SDHCI_TRNS_BLK_CNT_EN;
		if (data->flags == MMC_DATA_READ)
			mode |= SDHCI_TRNS_READ;

		if (data->blocks > 1)
			mode |= (SDHCI_TRNS_ACMD12 | SDHCI_TRNS_MULTI);

		sdhci_writew(host, data->blocks, SDHCI_BLOCK_COUNT);

		if (host->host_caps & MMC_AUTO_CMD12) {
#ifdef CONFIG_MMC_SDHCI_SDMA
			start_addr = (unsigned long)data->dest;
			if ((start_addr & 0x7) != 0x0) {
				return MMC_INVALID_ERR;
			}
			sdhci_writel(host, start_addr, SDHCI_DMA_ADDRESS);
#else
			if (sdhci_setup_adma(host, data))
				return -1;
#endif
			mode |= SDHCI_TRNS_DMA;
		}

		sdhci_writew(host, mode, SDHCI_TRANSFER_MODE);
	} else if (cmd->resp_type & MMC_RSP_BUSY) {
		sdhci_writeb(host, 0xe, SDHCI_TIMEOUT_CONTROL);
	}

	sdhci_writel(host, cmd->cmdarg, SDHCI_ARGUMENT);
	sdhci_writew(host, SDHCI_MAKE_CMD(cmd->cmdidx, flags), SDHCI_COMMAND);

#ifndef CONFIG_MMC_SDHCI_SDMA
	if (data && (host->host_caps & MMC_AUTO_CMD12)) {
		return sdhci_complete_adma(host, cmd, data);
	}
#endif

	start = 0;

	do {
		stat = sdhci_readl(host, SDHCI_INT_STATUS);

		if (stat & SDHCI_INT_ERROR)
			break;

		/* Apply max timeout for R1b-type CMD defined in eMMC ext_csd
		   except for erase ones */
		udelay(100);
		start += 100;
		if (start > 2550000) {
			if (host->quirks & SDHCI_QUIRK_BROKEN_R1B)
				return 0;
			else {
				mmc_error("SDHCI:Timeout for status update! cmd%d:0x%x, stat:0x%x, mask:0x%x\n",
					  cmd->cmdidx, sdhci_readw(host, SDHCI_COMMAND), stat, mask);
				return MMC_TIMEOUT;
			}
		}
	} while ((stat & mask) != mask);

	if ((stat & (SDHCI_INT_ERROR | mask)) == mask) {
		sdhci_cmd_done(host, cmd);
		sdhci_writel(host, mask, SDHCI_INT_STATUS);
	} else
		ret = -1;

	if (!ret && data)
		ret = sdhci_transfer_data(host, data, start_addr);

	if (host->quirks & SDHCI_QUIRK_WAIT_SEND_CMD)
		udelay(1000);

	stat = sdhci_readl(host, SDHCI_INT_STATUS);
	sdhci_writel(host, SDHCI_INT_ALL_MASK, SDHCI_INT_STATUS);

	if (!ret)
		return 0;

	sdhci_reset(host, SDHCI_RESET_CMD);
	sdhci_reset(host, SDHCI_RESET_DATA);

	mmc_error("SDHCI ERR:cmd:0x%x,stat:0x%x\n", sdhci_readw(host, SDHCI_COMMAND), stat);

	if (stat & SDHCI_INT_TIMEOUT)
		return MMC_TIMEOUT;
	else
		return MMC_COMM_ERR;
}

void sdhci_set_uhs_signaling(SdhciHost *host, unsigned int timing)
{
	u16 ctrl_2;

	mmc_debug("set timing: %d\n", timing);

	ctrl_2 = sdhci_readw(host, SDHCI_HOST_CONTROL2);
	/* Select Bus Speed Mode for host */
	ctrl_2 &= ~SDHCI_CTRL_UHS_MASK;

	if ((timing == MMC_TIMING_MMC_HS200) ||
	    (timing == MMC_TIMING_UHS_SDR104))
		ctrl_2 |= SDHCI_CTRL_UHS_SDR104;
	else if ((timing == MMC_TIMING_UHS_SDR12) ||
		 (timing == MMC_TIMING_LEGACY))
		ctrl_2 |= SDHCI_CTRL_UHS_SDR12;
	else if ((timing == MMC_TIMING_UHS_SDR25) ||
		 (timing == MMC_TIMING_MMC_HS)) {
		ctrl_2 |= SDHCI_CTRL_UHS_SDR25;
	} else if (timing == MMC_TIMING_UHS_SDR50) {
		ctrl_2 |= SDHCI_CTRL_UHS_SDR50;
	} else if ((timing == MMC_TIMING_UHS_DDR50) ||
		   (timing == MMC_TIMING_MMC_DDR52))
		ctrl_2 |= SDHCI_CTRL_UHS_DDR50;
	else if (timing == MMC_TIMING_MMC_HS400) {
		ctrl_2 |= SDHCI_CTRL_HS400; /* Non-standard */
	}

	sdhci_writew(host, ctrl_2 | SDHCI_CTRL_VDD_180 | SDHCI_CTRL_DRV_TYPE_A, SDHCI_HOST_CONTROL2);
	mmc_debug("host ctrl_2:0x%x\n", sdhci_readw(host, SDHCI_HOST_CONTROL2));

}

static int sdhci_set_clock(SdhciHost *host, unsigned int clock)
{
	unsigned int div, clk, timeout;

	if (clock == 0)
		return 0;

	sdhci_writew(host, 0, SDHCI_CLOCK_CONTROL);

	if (host->set_clock) {
		unsigned int clock_base = host->set_clock(clock);
		mmc_debug("sdhci_set_clock clock:%d, clock_base:%d\n", clock, clock_base);

		if (clock_base)
			host->clock_base = clock_base;
	}

	if ((host->version & SDHCI_SPEC_VER_MASK) >= SDHCI_SPEC_300) {
		/* Version 3.00 divisors must be a multiple of 2. */
		if (host->clock_base <= clock)
			div = 1;
		else {
			for (div = 2; div < SDHCI_MAX_DIV_SPEC_300; div += 2) {
				if ((host->clock_base / div) <= clock)
					break;
			}
		}
	} else {
		/* Version 2.00 divisors must be a power of 2. */
		for (div = 1; div < SDHCI_MAX_DIV_SPEC_200; div *= 2) {
			if ((host->clock_base / div) <= clock)
				break;
		}
	}

	div >>= 1;
#if 0

	if (clock > MMC_CLOCK_52MHZ ) {
		if (host->mmc_ctrlr.can_retune) {
			u16 ctrl_2 = sdhci_readw(host, SDHCI_HOST_CONTROL2);

			if (!(ctrl_2 & SDHCI_CTRL_TUNED_CLK)) {
				ctrl_2 |= SDHCI_CTRL_TUNED_CLK;
				sdhci_writew(host, ctrl_2, SDHCI_HOST_CONTROL2);
				mmc_debug("+++ctrl_2:0x%x\n", sdhci_readw(host, SDHCI_HOST_CONTROL2));
			}
		}
	} else {
		u16 ctrl_2 = sdhci_readw(host, SDHCI_HOST_CONTROL2);

		if (ctrl_2 & SDHCI_CTRL_TUNED_CLK) {
			ctrl_2 &= ~SDHCI_CTRL_TUNED_CLK;
			sdhci_writew(host, ctrl_2, SDHCI_HOST_CONTROL2);
			mmc_debug("ctrl_2:0x%x\n", sdhci_readw(host, SDHCI_HOST_CONTROL2));
		}
	}

#endif

	clk = (div & SDHCI_DIV_MASK) << SDHCI_DIVIDER_SHIFT;
	clk |= ((div & SDHCI_DIV_HI_MASK) >> SDHCI_DIV_MASK_LEN)
	       << SDHCI_DIVIDER_HI_SHIFT;
	clk |= SDHCI_CLOCK_INT_EN;
	sdhci_writew(host, clk, SDHCI_CLOCK_CONTROL);

	/* Wait max 20 ms */
	timeout = 20000;

	while (!((clk = sdhci_readw(host, SDHCI_CLOCK_CONTROL))
		 & SDHCI_CLOCK_INT_STABLE)) {
		if (timeout == 0) {
			mmc_error("Internal clock never stabilised.\n", "");
			return -1;
		}

		timeout--;
		udelay(1);
	}

	ConfigMMCPHY(host, clock, host->timing);

	clk |= SDHCI_CLOCK_CARD_EN;
	sdhci_writew(host, clk, SDHCI_CLOCK_CONTROL);
	return 0;
}

/* Find leftmost set bit in a 32 bit integer */
static int sdhci_fls(u32 x)
{
	int r = 32;

	if (!x)
		return 0;

	if (!(x & 0xffff0000u)) {
		x <<= 16;
		r -= 16;
	}

	if (!(x & 0xff000000u)) {
		x <<= 8;
		r -= 8;
	}

	if (!(x & 0xf0000000u)) {
		x <<= 4;
		r -= 4;
	}

	if (!(x & 0xc0000000u)) {
		x <<= 2;
		r -= 2;
	}

	if (!(x & 0x80000000u)) {
		x <<= 1;
		r -= 1;
	}

	return r;
}

static void sdhci_set_power(SdhciHost *host, unsigned short power)
{
	u8 pwr = 0;

	if (power != (unsigned short) -1) {
		switch (1 << power) {
			case MMC_VDD_165_195:
				pwr = SDHCI_POWER_180;
				break;

			case MMC_VDD_29_30:
			case MMC_VDD_30_31:
				pwr = SDHCI_POWER_300;
				break;

			case MMC_VDD_32_33:
			case MMC_VDD_33_34:
				pwr = SDHCI_POWER_330;
				break;
		}
	}

	if (pwr == 0) {
		sdhci_writeb(host, 0, SDHCI_POWER_CONTROL);
		return;
	}

	if (host->quirks & SDHCI_QUIRK_NO_SIMULT_VDD_AND_POWER)
		sdhci_writeb(host, pwr, SDHCI_POWER_CONTROL);

	pwr |= SDHCI_POWER_ON;

	sdhci_writeb(host, pwr, SDHCI_POWER_CONTROL);
}

static void sdhci_enhanced_strobe(MmcCtrlr *mmc_ctrlr, u32 enhanced_strobe)
{
	u32 vendor;
	SdhciHost *host = (SdhciHost *)mmc_get_host();

#ifdef DRIVERS_SDHCI_ARASAN
	vendor = sdhci_readl(host, SDHCI_ARASAN_VENDOR_REGISTER);
	if (enhanced_strobe)
		vendor |= VENDOR_ENHANCED_STROBE;
	else
		vendor &= (~VENDOR_ENHANCED_STROBE);

	sdhci_writel(host, vendor, SDHCI_ARASAN_VENDOR_REGISTER);
#else
	vendor = sdhci_readl(host, EMMC_EMMC_CTRL);
	if (enhanced_strobe)
		vendor |= BIT(8);
	else
		vendor &= ~(BIT(8));

	sdhci_writel(host, vendor, EMMC_EMMC_CTRL);
	//DRVDelayUs(100);
#endif
}


static int sdhci_send_tuning(MmcCtrlr *mmc_ctrlr, u32 opcode)
{
	MmcCommand cmd;
	SdhciHost *host = (SdhciHost *)mmc_get_host();

	cmd.cmdidx = opcode;
	cmd.resp_type = MMC_RSP_R1;
	cmd.cmdarg = 0;
	cmd.flags = 0;//MMC_CMD_ADTC;

	/*
	 * In response to CMD19, the card sends 64 bytes of tuning
	 * block to the Host Controller. So we set the block size
	 * to 64 here.
	 */
	if (opcode == MMC_SEND_TUNING_BLOCK_HS200 && mmc_ctrlr->bus_width == 8)
		sdhci_writew(host, SDHCI_MAKE_BLKSZ(7, 128),
			     SDHCI_BLOCK_SIZE);
	else if (mmc_ctrlr->bus_width == 4)
		sdhci_writew(host, SDHCI_MAKE_BLKSZ(7, 64),
			     SDHCI_BLOCK_SIZE);

	/*
	 * The tuning block is sent by the card to the host controller.
	 * So we set the TRNS_READ bit in the Transfer Mode register.
	 * This also takes care of setting DMA Enable and Multi Block
	 * Select in the same register to 0.
	 */
	sdhci_writew(host, SDHCI_TRNS_READ, SDHCI_TRANSFER_MODE);

	return sdhci_send_command(mmc_ctrlr, &cmd, NULL);
}

static int sdhci_execute_tuning(MmcCtrlr *mmc_ctrlr, u32 opcode)
{
	u16 ctrl;
	int i;
	int ret;

	int tuning_loop_counter = MAX_TUNING_LOOP;

	SdhciHost *host = (SdhciHost *)mmc_get_host();

	ctrl = sdhci_readw(host, SDHCI_HOST_CONTROL2);

	if (ctrl & SDHCI_CTRL_TUNED_CLK) { //reset tuning
		ctrl &= ~SDHCI_CTRL_TUNED_CLK;
		ctrl &= ~SDHCI_CTRL_EXEC_TUNING;
		sdhci_writew(host, ctrl, SDHCI_HOST_CONTROL2);
		//PRINT_E("reset tuning\n", "");
	}

	ctrl |= SDHCI_CTRL_EXEC_TUNING;
	//ctrl |= SDHCI_CTRL_TUNED_CLK;

	sdhci_writew(host, ctrl, SDHCI_HOST_CONTROL2);

	/*
	 * Issue opcode repeatedly till Execute Tuning is set to 0 or the number
	 * of loops reaches 40 times.
	 */
	for (i = 0; i < MAX_TUNING_LOOP; i++) {
		ret = sdhci_send_tuning(mmc_ctrlr, opcode);

		if (ret) {
			mmc_error("sdhci_send_tuning failed %d\n", ret);
			return ret;
		}

		ctrl = sdhci_readw(host, SDHCI_HOST_CONTROL2);

		if (!(ctrl & SDHCI_CTRL_EXEC_TUNING)) {
			if (ctrl & SDHCI_CTRL_TUNED_CLK)
				/* Tuning successfully */
				return 0;

			break;
		}
	}

	mmc_error("Tuning procedure failed.\n", "");
	return -1;
}


static void sdhci_set_ios(MmcCtrlr *mmc_ctrlr)
{
	u32 ctrl;
	//SdhciHost *host = container_of(mmc_ctrlr,
	//			       SdhciHost, mmc_ctrlr);
	SdhciHost *host = (SdhciHost *)mmc_get_host();

	if (host->set_control_reg)
		host->set_control_reg(host);

	if (mmc_ctrlr->bus_hz != host->clock) {
		sdhci_set_clock(host, mmc_ctrlr->bus_hz);
		host->clock = mmc_ctrlr->bus_hz;
	}

	/* Switch to 1.8 volt for HS200 */
	if (mmc_ctrlr->caps & MMC_MODE_1V8_VDD)
		if (mmc_ctrlr->bus_hz == MMC_CLOCK_200MHZ)
			sdhci_set_power(host, MMC_VDD_165_195_SHIFT);

	/* Set bus width */
	ctrl = sdhci_readb(host, SDHCI_HOST_CONTROL);

	if (mmc_ctrlr->bus_width == 8) {
		ctrl &= ~SDHCI_CTRL_4BITBUS;

		if ((host->version & SDHCI_SPEC_VER_MASK) >= SDHCI_SPEC_300)
			ctrl |= SDHCI_CTRL_8BITBUS;
	} else {
		if ((host->version & SDHCI_SPEC_VER_MASK) >= SDHCI_SPEC_300)
			ctrl &= ~SDHCI_CTRL_8BITBUS;

		if (mmc_ctrlr->bus_width == 4)
			ctrl |= SDHCI_CTRL_4BITBUS;
		else
			ctrl &= ~SDHCI_CTRL_4BITBUS;
	}

	if (mmc_ctrlr->timing == MMC_TIMING_SD_HS ||
	    mmc_ctrlr->timing == MMC_TIMING_MMC_HS ||
	    mmc_ctrlr->bus_hz > 26000000)
		ctrl |= SDHCI_CTRL_HISPD;
	else
		ctrl &= ~SDHCI_CTRL_HISPD;

	if (host->quirks & SDHCI_QUIRK_NO_HISPD_BIT)
		ctrl &= ~SDHCI_CTRL_HISPD;

	/* In case of UHS-I modes, set High Speed Enable */
	if ((mmc_ctrlr->timing == MMC_TIMING_MMC_HS400) ||
	    (mmc_ctrlr->timing == MMC_TIMING_MMC_HS200) ||
	    (mmc_ctrlr->timing == MMC_TIMING_MMC_DDR52) ||
	    (mmc_ctrlr->timing == MMC_TIMING_MMC_HS)    ||
	    (mmc_ctrlr->timing == MMC_TIMING_UHS_SDR50) ||
	    (mmc_ctrlr->timing == MMC_TIMING_UHS_SDR104) ||
	    (mmc_ctrlr->timing == MMC_TIMING_UHS_DDR50) ||
	    (mmc_ctrlr->timing == MMC_TIMING_UHS_SDR25))
		ctrl |= SDHCI_CTRL_HISPD;

	if (host->host_caps & MMC_AUTO_CMD12) {
		ctrl &= ~SDHCI_CTRL_DMA_MASK;

#ifndef CONFIG_MMC_SDHCI_SDMA
		if (host->dma64)
			ctrl |= SDHCI_CTRL_ADMA64;
		else
			ctrl |= SDHCI_CTRL_ADMA32;
#endif
	}

	mmc_debug("host ctrl:0x%x\n", ctrl);
	sdhci_writeb(host, ctrl, SDHCI_HOST_CONTROL);

	if (mmc_ctrlr->timing != host->timing) {
		u16 clk;
		/* Reset SD Clock Enable */
		clk = sdhci_readw(host, SDHCI_CLOCK_CONTROL);
		clk &= ~SDHCI_CLOCK_CARD_EN;
		sdhci_writew(host, clk, SDHCI_CLOCK_CONTROL);

		sdhci_set_uhs_signaling(host, mmc_ctrlr->timing);
		host->timing = mmc_ctrlr->timing;

		/* Re-enable SD Clock */
		sdhci_set_clock(host, mmc_ctrlr->bus_hz);
	}
}

/* Prepare SDHCI controller to be initialized */
static int sdhci_pre_init(SdhciHost *host)
{
	unsigned int caps;

	if (host->attach) {
		int rv = host->attach(host);

		if (rv)
			return rv;
	}

	host->version = sdhci_readw(host, SDHCI_HOST_VERSION) & 0xff;
	mmc_debug("host->version:0x%x\n", host->version);

	caps = sdhci_readl(host, SDHCI_CAPABILITIES);
	mmc_debug("host caps:0x%x\n", caps);
	mmc_debug("host caps1:0x%x\n", sdhci_readl(host, SDHCI_CAPABILITIES_1));

	if (caps & SDHCI_CAN_DO_ADMA2)
		host->host_caps |= MMC_AUTO_CMD12;

	/* get base clock frequency from CAP register */
	if (!(host->quirks & SDHCI_QUIRK_CAP_CLOCK_BASE_BROKEN)) {
		if ((host->version & SDHCI_SPEC_VER_MASK) >= SDHCI_SPEC_300)
			host->clock_base = (caps & SDHCI_CLOCK_V3_BASE_MASK)
					   >> SDHCI_CLOCK_BASE_SHIFT;
		else
			host->clock_base = (caps & SDHCI_CLOCK_BASE_MASK)
					   >> SDHCI_CLOCK_BASE_SHIFT;

		if (host->clock_base == 0) {
			mmc_error("Hardware doesn't specify base clock frequency\n", "");
			return -1;
		}
	}

	host->clock_base *= 1000000;

	if (host->clock_f_max)
		host->mmc_ctrlr.f_max = host->clock_f_max;
	else
		host->mmc_ctrlr.f_max = host->clock_base;

	if (host->clock_f_min) {
		host->mmc_ctrlr.f_min = host->clock_f_min;
	} else {
		if ((host->version & SDHCI_SPEC_VER_MASK) >= SDHCI_SPEC_300)
			host->mmc_ctrlr.f_min =
				host->clock_base / SDHCI_MAX_DIV_SPEC_300;
		else
			host->mmc_ctrlr.f_min =
				host->clock_base / SDHCI_MAX_DIV_SPEC_200;
	}

	if (caps & SDHCI_CAN_VDD_330)
		host->mmc_ctrlr.voltages |= MMC_VDD_32_33 | MMC_VDD_33_34;

	if (caps & SDHCI_CAN_VDD_300)
		host->mmc_ctrlr.voltages |= MMC_VDD_29_30 | MMC_VDD_30_31;

	if (caps & SDHCI_CAN_VDD_180)
		host->mmc_ctrlr.voltages |= MMC_VDD_165_195;

	if (host->quirks & SDHCI_QUIRK_BROKEN_VOLTAGE)
		host->mmc_ctrlr.voltages |= host->voltages;

	if (host->quirks & SDHCI_QUIRK_NO_EMMC_HS200)
		host->mmc_ctrlr.caps = MMC_MODE_HS | MMC_MODE_HS_52MHz |
				       MMC_MODE_4BIT | MMC_MODE_HC;
	else
		host->mmc_ctrlr.caps = MMC_MODE_HS | MMC_MODE_HS_52MHz |
				       MMC_MODE_4BIT | MMC_MODE_HC | MMC_MODE_HS_200MHz |
				       MMC_MODE_HS_400MHz | MMC_MODE_HS_400MHz_ES;

	if (host->quirks & SDHCI_QUIRK_EMMC_1V8_POWER)
		host->mmc_ctrlr.caps |= MMC_MODE_1V8_VDD;

	if (caps & SDHCI_CAN_DO_8BIT)
		host->mmc_ctrlr.caps |= MMC_MODE_8BIT;

	if (host->host_caps)
		host->mmc_ctrlr.caps |= host->host_caps;

	if (caps & SDHCI_CAN_64BIT)
		host->dma64 = 1;

	sdhci_reset(host, SDHCI_RESET_ALL);

	return 0;
}

static int sdhci_init(SdhciHost *host)
{
	int rv = sdhci_pre_init(host);

	if (rv)
		return rv; /* The error has been already reported */

	sdhci_set_power(host, sdhci_fls(host->mmc_ctrlr.voltages) - 1);

	if (host->quirks & SDHCI_QUIRK_NO_CD) {
		unsigned int status;

		sdhci_writel(host, SDHCI_CTRL_CD_TEST_INS | SDHCI_CTRL_CD_TEST,
			     SDHCI_HOST_CONTROL);

		status = sdhci_readl(host, SDHCI_PRESENT_STATE);

		while ((!(status & SDHCI_CARD_PRESENT)) ||
		       (!(status & SDHCI_CARD_STATE_STABLE)) ||
		       (!(status & SDHCI_CARD_DETECT_PIN_LEVEL)))
			status = sdhci_readl(host, SDHCI_PRESENT_STATE);
	}

	/* Enable only interrupts served by the SD controller */
	sdhci_writel(host, SDHCI_INT_DATA_MASK | SDHCI_INT_CMD_MASK,
		     SDHCI_INT_ENABLE);
	/* Mask all sdhci interrupt sources */
	sdhci_writel(host, 0x0, SDHCI_SIGNAL_ENABLE);

	/* Set timeout to maximum, shouldn't happen if everything's right. */
	sdhci_writeb(host, 0xe, SDHCI_TIMEOUT_CONTROL);

	udelay(10000);
	return 0;
}

static int sdhci_update(BlockDevCtrlrOps *me)
{
	SdhciHost *host = mmc_get_host();

	if (!host->initialized && sdhci_init(host))
		return -1;

	host->initialized = 1;

	if (mmc_setup_media(&host->mmc_ctrlr))
		return -1;

	host->mmc_ctrlr.media->dev.name = "SDHCI fixed";
	host->mmc_ctrlr.ctrlr.need_update = 0;

	return 0;
}

void add_sdhci(SdhciHost *host)
{
	host->mmc_ctrlr.send_cmd = &sdhci_send_command;
	host->mmc_ctrlr.set_ios = &sdhci_set_ios;
	host->mmc_ctrlr.execute_tuning = &sdhci_execute_tuning;
	host->mmc_ctrlr.hs400_enhanced_strobe = &sdhci_enhanced_strobe;

	host->mmc_ctrlr.ctrlr.ops.update = &sdhci_update;
	host->mmc_ctrlr.ctrlr.need_update = 1;

	/* TODO(vbendeb): check if SDHCI spec allows to retrieve this value. */
	host->mmc_ctrlr.b_max = 65535;
}

#endif
