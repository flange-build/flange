set(aio_srcs "app_main.c" "usb_descriptors.c" "gud_device.c" "lz4.c" "display_dsi.c"
             "standby_screen.c" "board_power.c" "kbd_i2c.c" "kbd_translate.c"
             "touch_hid.c" "touch_map.c" "audio_frame.c")

# codec_audio.c 调 tud_audio_*，那些符号只在 CFG_TUD_AUDIO=1 时存在；音频关闭
# （默认）时把它整个排除，否则是链接期缺符号。audio_frame.c 是纯函数、无 USB
# 依赖，且 test/test_audio_frame.c 一直在测它，所以始终编译。
if(CONFIG_AIO_AUDIO_FULL)
    list(APPEND aio_srcs "codec_audio.c")
endif()

idf_component_register(SRCS ${aio_srcs}
                       INCLUDE_DIRS "." "tinyusb_config"
                       PRIV_REQUIRES esp_driver_i2c esp_driver_gpio esp_driver_i2s esp_lcd esp_mm esp_driver_ppa)

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
