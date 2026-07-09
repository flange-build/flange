# SPDX-License-Identifier: BSD-3-Clause */

# Copyright (c) 2021 Rockchip Electronics Co., Ltd.

#-------------------------------------------------------------------------
# set OPENAMP_PATH
#-------------------------------------------------------------------------
OPENAMP_INC += \
-I"$(HAL_PATH)/middleware/OpenAMP/open-amp/lib/include" \
-I"$(HAL_PATH)/middleware/OpenAMP/libmetal/lib/include" \
-I"$(HAL_PATH)/middleware/OpenAMP/virtual_driver" \
-I"$(HAL_PATH)/middleware/OpenAMP" \

OPENAMP_SRC += \
    $(HAL_PATH)/middleware/OpenAMP  \
    $(HAL_PATH)/middleware/OpenAMP/virtual_driver  \
    $(HAL_PATH)/middleware/OpenAMP/open-amp/lib/remoteproc  \
    $(HAL_PATH)/middleware/OpenAMP/open-amp/lib/rpmsg \
    $(HAL_PATH)/middleware/OpenAMP/open-amp/lib/virtio  \
    $(HAL_PATH)/middleware/OpenAMP/libmetal/lib  \
    $(HAL_PATH)/middleware/OpenAMP/libmetal/lib/system/generic  \
    $(HAL_PATH)/middleware/OpenAMP/libmetal/lib/system/generic/cortexm \

SRC_DIRS += $(OPENAMP_SRC)
INCLUDES += $(OPENAMP_INC)
