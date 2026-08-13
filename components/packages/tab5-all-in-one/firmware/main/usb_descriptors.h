#pragma once
#include "tusb.h"

/* mainline drm/gud 驱动绑定的固定 VID/PID，不可更改 */
#define GUD_VID 0x16d0
#define GUD_PID 0x10a9

/* 接口编号。后续阶段在 VENDOR/HID 之后追加 UAC / UVC，勿改 VENDOR=0。 */
enum { ITF_NUM_VENDOR = 0, ITF_NUM_HID, ITF_NUM_TOTAL };

/* 端点编号。P4 全速控制器 ep_count=7 / ep_in_count=5(含 EP0)。 */
#define EPNUM_VENDOR_OUT 0x01
#define EPNUM_VENDOR_IN  0x81
#define EPNUM_HID        0x82

/* HID Report ID。触摸阶段追加 RID 2 = digitizer，共用本接口与端点
 * （P4 全速控制器最多 4 条 IN 端点，UAC/UVC 会用满，见 firmware/README.md）。 */
#define HID_RID_KEYBOARD 1

/*
 * 描述符数据由 esp_tinyusb 经 tinyusb_config_t 注入；不要在本工程实现
 * tud_descriptor_*_cb，否则与 esp_tinyusb 的实现重复符号。
 */
extern const tusb_desc_device_t aio_desc_device;
extern const uint8_t aio_desc_configuration[];
extern const char *aio_string_desc_arr[];
extern const int aio_string_desc_count;
