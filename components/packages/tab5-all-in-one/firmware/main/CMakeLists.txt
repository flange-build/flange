set(aio_srcs "app_main.c" "usb_descriptors.c" "gud_device.c" "lz4.c"
             "display_dsi.c" "standby_screen.c" "board_power.c"
             "kbd_i2c.c" "kbd_translate.c" "touch_hid.c" "touch_map.c"
             "uvc_pattern.c")
set(aio_reqs esp_driver_i2c esp_driver_gpio esp_lcd esp_mm esp_driver_ppa)

# UVC 调试档（CONFIG_AIO_DEBUG_CDC）下**整个音频功能不编译**：CDC 的通知端点要占
# 0x83，也就是 UAC 录音那一条（推导见 main/usb_descriptors.h 的 AIO_HAS_AUDIO 段）。
# 连 esp_driver_i2s 一起去掉，省下的 flash 也让「这一档真的没有音频」这件事在
# 构建系统里就成立，而不是只靠描述符里少了三个接口。
if(NOT CONFIG_AIO_DEBUG_CDC)
    list(APPEND aio_srcs "audio_frame.c" "codec_audio.c" "uac_volume.c")
    list(APPEND aio_reqs esp_driver_i2s)
endif()

idf_component_register(SRCS ${aio_srcs}
                       INCLUDE_DIRS "." "tinyusb_config"
                       PRIV_REQUIRES ${aio_reqs})

# esp_tinyusb 2.2.1 的默认 tusb_config.h 不含 Audio class。让依赖组件与应用统一
# 使用 main/tinyusb_config/tusb_config.h；该文件再 include_next 默认配置，
# 保留 Vendor/HID/Kconfig 映射。做法逐行照搬 cardputer-all-in-one。
#
# ⚠️ BEFORE 与「两个库都要加」缺一不可：esp_tinyusb 自己把它的 include/ 塞进了
#    tinyusb 库，不用 BEFORE 会排在它后面而不生效；只改 tinyusb 会让 esp_tinyusb 的
#    descriptors_control.c 看到不同的 CFG_TUD_*，接口数与描述符长度对不上。
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
