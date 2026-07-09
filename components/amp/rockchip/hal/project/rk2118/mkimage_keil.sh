#!/bin/bash

# SPDX-License-Identifier: BSD-3-Clause
#
# Copyright (c) 2025 Rockchip Electronics Co., Ltd.
#

cp KEIL/Objects/rk2118.bin ./Image/bare.img
./align_bin_size.sh ./Image/bare.img
../../../../tools/resource_header_tool pack --json Image/bare.json ./Image/bare.img
