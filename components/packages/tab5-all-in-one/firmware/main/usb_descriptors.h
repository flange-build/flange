#pragma once
#include "tusb.h"

/* mainline drm/gud 驱动绑定的固定 VID/PID，不可更改 */
#define GUD_VID 0x16d0
#define GUD_PID 0x10a9

/*
 * 接口编号。后续阶段在 VENDOR/HID 之后追加 UAC / UVC，勿改 VENDOR=0。
 *
 * CDC（调试串口）**默认关闭**，由 CONFIG_TINYUSB_CDC_ENABLED 决定；它占**两个**
 * 接口（通信 + 数据，TUD_CDC_DESCRIPTOR 自带 IAD），所以 ITF_NUM_TOTAL 是条件式的：
 * 关闭 = 2，开启 = 4。开关与代价见 sdkconfig.defaults 末尾与 firmware/README.md。
 *
 * 该宏由 esp_tinyusb 的 tusb_config.h 保证恒有定义（未选中时为 0），
 * tusb.h 已经把它拉进来，因此这里的 #if 在两种配置下都成立。
 */
enum {
    ITF_NUM_VENDOR = 0,
    ITF_NUM_HID,
#if CONFIG_TINYUSB_CDC_ENABLED
    ITF_NUM_CDC,        /* CDC 通信接口（带中断 IN 通知端点） */
    ITF_NUM_CDC_DATA,   /* CDC 数据接口（bulk OUT/IN） */
#endif
    ITF_NUM_TOTAL
};

/* 端点编号。P4 全速控制器 ep_count=7 / ep_in_count=5(含 EP0)，即最多 4 条可用 IN。 */
#define EPNUM_VENDOR_OUT 0x01
#define EPNUM_VENDOR_IN  0x81
#define EPNUM_HID        0x82

#if CONFIG_TINYUSB_CDC_ENABLED
/*
 * ⚠️ 开启 CDC 后 4 条可用 IN 端点全部用满：
 *   0x81 vendor(GUD) / 0x82 HID / 0x83 CDC 通知 / 0x84 CDC 数据。
 * UAC（麦克风 1 条 IN）与 UVC（视频流 1 条 IN）届时都放不下 —— 这正是 CDC
 * 只作为调试设施、默认关闭的原因。
 */
#define EPNUM_CDC_NOTIF  0x83
#define EPNUM_CDC_OUT    0x02
#define EPNUM_CDC_IN     0x84
#endif

/* HID Report ID。键盘与触摸共用 IF1 这一个接口与 EPNUM_HID 这一条 IN 端点
 * （P4 全速控制器最多 4 条 IN 端点，UAC/UVC 会用满，见 firmware/README.md），
 * 靠 Report ID 区分 —— 这也是本接口必须放弃 boot 协议的原因，见 usb_descriptors.c。 */
#define HID_RID_KEYBOARD 1
#define HID_RID_TOUCH    2

/*
 * 描述符数据由 esp_tinyusb 经 tinyusb_config_t 注入；不要在本工程实现
 * tud_descriptor_*_cb，否则与 esp_tinyusb 的实现重复符号。
 */
extern const tusb_desc_device_t aio_desc_device;
extern const uint8_t aio_desc_configuration[];
extern const char *aio_string_desc_arr[];
extern const int aio_string_desc_count;
