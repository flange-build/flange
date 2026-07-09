# SPDX-License-Identifier: BSD-3-Clause */

# Copyright (c) 2022 Rockchip Electronics Co., Ltd.

RPMSG_LITE_PATH=$(HAL_PATH)/middleware/rpmsg-lite/lib

INCLUDES += \
-I"$(RPMSG_LITE_PATH)/include" \
-I"$(RPMSG_LITE_PATH)/include/environment/bm" \
-I"$(RPMSG_LITE_PATH)/include/platform/$(SOC)" \
-I"$(RPMSG_LITE_PATH)/test" \

SRC_DIRS += \
    $(RPMSG_LITE_PATH)/common \
    $(RPMSG_LITE_PATH)/rpmsg_lite \
    $(RPMSG_LITE_PATH)/rpmsg_lite/porting/platform/$(SOC) \
    $(RPMSG_LITE_PATH)/init/platform/$(SOC) \
    $(RPMSG_LITE_PATH)/virtio \
    $(RPMSG_LITE_PATH)/test \

SRCS += \
    $(RPMSG_LITE_PATH)/rpmsg_lite/porting/environment/rpmsg_env_bm.c \
