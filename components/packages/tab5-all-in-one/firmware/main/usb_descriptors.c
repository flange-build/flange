#include "usb_descriptors.h"

/* 设备描述符：Misc/IAD：为后续 UAC/HID/UVC 复合预留；本阶段仅 IF0 vendor。
 * VID/PID = 16d0:10a9（gud 绑定所需） */
const tusb_desc_device_t aio_desc_device = {
    .bLength = sizeof(tusb_desc_device_t),
    .bDescriptorType = TUSB_DESC_DEVICE,
    .bcdUSB = 0x0200,
    .bDeviceClass = TUSB_CLASS_MISC,
    .bDeviceSubClass = MISC_SUBCLASS_COMMON,
    .bDeviceProtocol = MISC_PROTOCOL_IAD,
    .bMaxPacketSize0 = CFG_TUD_ENDPOINT0_SIZE,
    .idVendor = GUD_VID,
    .idProduct = GUD_PID,
    .bcdDevice = 0x0100,
    .iManufacturer = 0x01,
    .iProduct = 0x02,
    .iSerialNumber = 0x03,
    .bNumConfigurations = 0x01,
};

/* 标准键盘，带 Report ID —— 触摸阶段以 RID 2 追加时是纯增量改动。 */
static const uint8_t aio_hid_report_desc[] = {
    TUD_HID_REPORT_DESC_KEYBOARD(HID_REPORT_ID(HID_RID_KEYBOARD))
};

/* 配置描述符：IF0 = GUD vendor，IF1 = HID 键盘。 */
#define CONFIG_TOTAL_LEN (TUD_CONFIG_DESC_LEN + TUD_VENDOR_DESC_LEN + TUD_HID_DESC_LEN)
const uint8_t aio_desc_configuration[] = {
    TUD_CONFIG_DESCRIPTOR(1, ITF_NUM_TOTAL, 0, CONFIG_TOTAL_LEN, 0x00, 100),
    TUD_VENDOR_DESCRIPTOR(ITF_NUM_VENDOR, 0, EPNUM_VENDOR_OUT, EPNUM_VENDOR_IN, 64),
    TUD_HID_DESCRIPTOR(ITF_NUM_HID, 0, HID_ITF_PROTOCOL_KEYBOARD,
                       sizeof(aio_hid_report_desc), EPNUM_HID,
                       CFG_TUD_HID_EP_BUFSIZE, 10),
};

_Static_assert(sizeof(aio_desc_configuration) == CONFIG_TOTAL_LEN,
               "USB 配置描述符长度不一致");

/* esp_tinyusb 只实现 tud_descriptor_*_cb，HID 这三个回调要我们自己提供，
 * 否则链接期缺符号（report_cb）或运行时对 GET/SET_REPORT STALL。 */
uint8_t const *tud_hid_descriptor_report_cb(uint8_t instance)
{
    (void)instance;
    return aio_hid_report_desc;
}

uint16_t tud_hid_get_report_cb(uint8_t instance, uint8_t report_id,
                               hid_report_type_t report_type, uint8_t *buffer, uint16_t reqlen)
{
    (void)instance; (void)report_id; (void)report_type; (void)buffer; (void)reqlen;
    return 0;
}

/* 空实现 = 忽略 host 下发的 LED 状态（如 CapsLock）。本阶段有意为之。 */
void tud_hid_set_report_cb(uint8_t instance, uint8_t report_id,
                           hid_report_type_t report_type, uint8_t const *buffer, uint16_t bufsize)
{
    (void)instance; (void)report_id; (void)report_type; (void)buffer; (void)bufsize;
}

/*
 * 字符串描述符：交由 esp_tinyusb 完成 UTF-16 转换与 langid 处理。
 * 索引 0 = langid（English, 0x0409），1=厂商 2=产品 3=序列号。
 */
static const char k_langid[] = {0x09, 0x04, 0x00};
const char *aio_string_desc_arr[] = {
    k_langid,
    "flange",
    "Tab5 GUD Display",
    "TAB5-0001",
};
const int aio_string_desc_count = sizeof(aio_string_desc_arr) / sizeof(aio_string_desc_arr[0]);
