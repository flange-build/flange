#pragma once

/*
 * esp_tinyusb 的默认配置覆盖 Vendor/HID 等 Kconfig 映射，但未开放 Audio 类。
 * include_next 保留其平台、FreeRTOS 和既有 class 配置，再追加本项目的 UAC1 参数。
 */
#include_next "tusb_config.h"

#undef CFG_TUD_AUDIO
#define CFG_TUD_AUDIO 1

#define CFG_TUD_AUDIO_ENABLE_EP_OUT 1
#define CFG_TUD_AUDIO_FUNC_1_N_CHANNELS_RX 1
#define CFG_TUD_AUDIO_FUNC_1_N_BYTES_PER_SAMPLE_RX 2
#define CFG_TUD_AUDIO_FUNC_1_RESOLUTION_RX 16
#define CFG_TUD_AUDIO_FUNC_1_EP_OUT_SZ_MAX 32
#define CFG_TUD_AUDIO_FUNC_1_EP_OUT_SW_BUF_SZ 256
