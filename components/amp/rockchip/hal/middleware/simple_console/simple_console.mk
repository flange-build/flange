# SPDX-License-Identifier: BSD-3-Clause */

# Copyright (c) 2023 Rockchip Electronics Co., Ltd.

SIMPLE_CONSOLE_INC += \
-I"$(HAL_PATH)/middleware/simple_console"

SIMPLE_CONSOLE_SRC += \
    $(HAL_PATH)/middleware/simple_console

SRC_DIRS += $(SIMPLE_CONSOLE_SRC)
INCLUDES += $(SIMPLE_CONSOLE_INC)
