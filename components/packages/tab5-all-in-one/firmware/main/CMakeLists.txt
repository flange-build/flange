idf_component_register(SRCS "app_main.c" "usb_descriptors.c" "gud_device.c" "lz4.c" "display_dsi.c" "board_power.c"
                       INCLUDE_DIRS "."
                       PRIV_REQUIRES esp_driver_i2c esp_driver_gpio)

# 官方 LZ4 v1.9.4 参考实现(lz4/lz4, BSD-2-Clause)，仅用 LZ4_decompress_safe 解 GUD
# host 端 LZ4 压缩帧。第三方源码放宽告警，避免 main 的 -Werror 因其内部告警失败。
set_source_files_properties(lz4.c PROPERTIES COMPILE_FLAGS "-Wno-error -Wno-unused-function")
