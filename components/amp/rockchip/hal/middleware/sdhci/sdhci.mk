# SPDX-License-Identifier: BSD-3-Clause */

# Copyright (c) 2021 Rockchip Electronics Co., Ltd.

#-------------------------------------------------------------------------
# set SDHCI_PATH
#-------------------------------------------------------------------------
SDHCI_INC += \
-I"$(HAL_PATH)/middleware/sdhci"

SDHCI_SRC += \
    $(HAL_PATH)/middleware/sdhci

SRC_DIRS += $(SDHCI_SRC)
INCLUDES += $(SDHCI_INC)
