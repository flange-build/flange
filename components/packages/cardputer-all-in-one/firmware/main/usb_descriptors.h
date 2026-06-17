#pragma once
#include <stdint.h>
#include "tusb.h"

/* GUD 驱动绑定所需的 VID/PID（mainline gud：usb:v16D0p10A9...icFF...） */
#define GUD_VID 0x16D0
#define GUD_PID 0x10A9

enum { ITF_NUM_VENDOR = 0, ITF_NUM_HID, ITF_NUM_TOTAL };
enum { EPNUM_VENDOR_OUT = 0x01, EPNUM_VENDOR_IN = 0x81, EPNUM_HID = 0x82 };

/*
 * 描述符仅暴露“数据”，由 app_main 通过 tinyusb_config_t 注入。
 * 注意：esp_tinyusb 组件自身实现了 tud_descriptor_*_cb（见 descriptors_control.c），
 * 故本固件不得再实现这些回调，否则链接期重复符号。
 */
extern const tusb_desc_device_t aio_desc_device;
extern const uint8_t aio_desc_configuration[];
extern const char *aio_string_desc_arr[];
extern const int aio_string_desc_count;
