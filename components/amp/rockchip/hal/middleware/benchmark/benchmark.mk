# SPDX-License-Identifier: BSD-3-Clause */

# Copyright (c) 2022 Rockchip Electronics Co., Ltd.

BENCHMARK_PATH=$(HAL_PATH)/middleware/benchmark

INCLUDES += \
-I"$(BENCHMARK_PATH)" \
-I"$(BENCHMARK_PATH)/coremark" \
-I"$(BENCHMARK_PATH)/coremark/barebones" \
# -I"$(BENCHMARK_PATH)/linpack" \
# -I"$(BENCHMARK_PATH)/tinymembench" \

SRC_DIRS += \
    $(BENCHMARK_PATH) \
    $(BENCHMARK_PATH)/coremark \
    $(BENCHMARK_PATH)/coremark/barebones \
#    $(BENCHMARK_PATH)/linpack \
#    $(BENCHMARK_PATH)/tinymembench \
