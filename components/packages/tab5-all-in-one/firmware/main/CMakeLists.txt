idf_component_register(SRCS "app_main.c" "usb_descriptors.c" "gud_device.c" "lz4.c" "display_dsi.c"
                       INCLUDE_DIRS "." "tinyusb_config"
                       PRIV_REQUIRES esp_driver_gpio
                       LDFRAGMENTS "linker.lf")

# esp_tinyusb 默认 tusb_config.h 不含我们要的类配置。让依赖组件与应用统一使用
# main/tinyusb_config/tusb_config.h；该文件再 include_next 默认配置，保留 Kconfig 映射。
idf_build_get_property(build_components BUILD_COMPONENTS)

if(tinyusb IN_LIST build_components)
    set(tinyusb_component tinyusb)
else()
    set(tinyusb_component espressif__tinyusb)
endif()

if(esp_tinyusb IN_LIST build_components)
    set(esp_tinyusb_component esp_tinyusb)
else()
    set(esp_tinyusb_component espressif__esp_tinyusb)
endif()

idf_component_get_property(tinyusb_lib ${tinyusb_component} COMPONENT_LIB)
idf_component_get_property(esp_tinyusb_lib ${esp_tinyusb_component} COMPONENT_LIB)
set(tinyusb_config_dir "${CMAKE_CURRENT_LIST_DIR}/tinyusb_config")
target_include_directories(${tinyusb_lib} BEFORE PRIVATE "${tinyusb_config_dir}")
target_include_directories(${esp_tinyusb_lib} BEFORE PRIVATE "${tinyusb_config_dir}")

# 官方 LZ4 v1.9.4 参考实现(lz4/lz4, BSD-2-Clause)，仅用 LZ4_decompress_safe 解 GUD
# host 端 LZ4 压缩帧。第三方源码放宽告警，避免 main 的 -Werror 因其内部告警失败。
set_source_files_properties(lz4.c PROPERTIES COMPILE_FLAGS "-Wno-error -Wno-unused-function")
