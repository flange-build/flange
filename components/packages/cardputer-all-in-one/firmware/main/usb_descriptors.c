#include "usb_descriptors.h"

/* 设备描述符：vendor 类设备，VID/PID = 16d0:10a9（gud 绑定所需） */
const tusb_desc_device_t aio_desc_device = {
    .bLength = sizeof(tusb_desc_device_t),
    .bDescriptorType = TUSB_DESC_DEVICE,
    .bcdUSB = 0x0200,
    /* 类信息放在接口层（bInterfaceClass=0xFF），设备层置 0 */
    .bDeviceClass = 0x00,
    .bDeviceSubClass = 0x00,
    .bDeviceProtocol = 0x00,
    .bMaxPacketSize0 = CFG_TUD_ENDPOINT0_SIZE,
    .idVendor = GUD_VID,
    .idProduct = GUD_PID,
    .bcdDevice = 0x0100,
    .iManufacturer = 0x01,
    .iProduct = 0x02,
    .iSerialNumber = 0x03,
    .bNumConfigurations = 0x01,
};

/* 配置描述符：单个 vendor 接口 + bulk IN/OUT 端点（包大小 64，FS） */
#define CONFIG_TOTAL_LEN (TUD_CONFIG_DESC_LEN + TUD_VENDOR_DESC_LEN)
const uint8_t aio_desc_configuration[] = {
    TUD_CONFIG_DESCRIPTOR(1, ITF_NUM_TOTAL, 0, CONFIG_TOTAL_LEN, 0x00, 100),
    TUD_VENDOR_DESCRIPTOR(ITF_NUM_VENDOR, 0, EPNUM_VENDOR_OUT, EPNUM_VENDOR_IN, 64),
};

/*
 * 字符串描述符：交由 esp_tinyusb 完成 UTF-16 转换与 langid 处理。
 * 索引 0 = langid（English, 0x0409），1=厂商 2=产品 3=序列号。
 */
static const char k_langid[] = {0x09, 0x04, 0x00};
const char *aio_string_desc_arr[] = {
    k_langid,
    "flange",
    "Cardputer GUD Display",
    "AIO-0001",
};
const int aio_string_desc_count = sizeof(aio_string_desc_arr) / sizeof(aio_string_desc_arr[0]);
