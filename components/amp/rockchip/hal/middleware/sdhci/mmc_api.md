# SDHCI API

```c
void sdmmc_init(void *base_reg)
/* base_reg:  SDHCI regedit base address */

int32_t sdmmc_ioctrl(uint32_t cmd, void *param)
/*
cmd:
SDM_IOCTRL_REGISTER_CARD:   initialize EMMC device.
SDM_IOCTR_GET_CAPABILITY:  get  EMMC density.
*/

int32_t sdmmc_write(uint32_t start, uint32_t count, void *buffer)
/*
start: write data start address, the unit is sector.
count: write data sector count.
buffer: write data buffer, need cache line alignment, usually is 64 bytes.
*/

int32_t sdmmc_read(uint32_t start, uint32_t count, void *buffer)
/*
start: read data start address, the unit is sector.
count: read data sector count.
buffer: read data buffer, need cache line alignment, usually is 64 bytes.
*/
```


# Initialization Flow

Demo code:

```c
int ioctlParam[5] = {0, 0, 0, 0, 0};
int ret;

sdmmc_init((void *)0xFE310000);
ret = sdmmc_ioctrl(SDM_IOCTRL_REGISTER_CARD, ioctlParam);
if (ret) {
    printf("emmc init error!\n");
    return -1;
}

ret = sdmmc_ioctrl(SDM_IOCTR_GET_CAPABILITY, ioctlParam);
if (ret) {
    printf("emmc get capability error!\n");
    return -1;
}

userCapSize = ioctlParam[1];
```


# Cache Enable

If cache is enabled, the cache processing function in sdhci_setup_adma needs to be implemented.
