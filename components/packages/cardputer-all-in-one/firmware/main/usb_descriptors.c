#include "usb_descriptors.h"

/* 设备描述符：Misc/IAD 复合设备，VID/PID = 16d0:10a9（gud 绑定所需） */
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

/* HID report 描述符：标准键盘（report id = 0） */
static const uint8_t aio_hid_report_desc[] = {
    TUD_HID_REPORT_DESC_KEYBOARD()};

/* UAC1 mono audio：一个 AC 管理 speaker OUT 与 microphone IN 两个 AS interface。 */
#define UAC1_STREAM_DESC_LEN (TUD_AUDIO10_DESC_STD_AS_LEN + \
                              TUD_AUDIO10_DESC_STD_AS_LEN + \
                              TUD_AUDIO10_DESC_CS_AS_INT_LEN + \
                              TUD_AUDIO10_DESC_TYPE_I_FORMAT_LEN(1) + \
                              TUD_AUDIO10_DESC_STD_AS_ISO_EP_LEN + \
                              TUD_AUDIO10_DESC_CS_AS_ISO_EP_LEN)

#define UAC1_AUDIO_DESC_LEN (8 + \
                             TUD_AUDIO10_DESC_STD_AC_LEN + \
                             TUD_AUDIO10_DESC_CS_AC_LEN(2) + \
                             2 * (TUD_AUDIO10_DESC_INPUT_TERM_LEN + \
                                  TUD_AUDIO10_DESC_OUTPUT_TERM_LEN) + \
                             2 * UAC1_STREAM_DESC_LEN)

#define UAC1_AUDIO_DESCRIPTOR(_ac_itf, _speaker_as, _mic_as, _stridx, _epout, _epin) \
    8, TUSB_DESC_INTERFACE_ASSOCIATION, _ac_itf, 3, TUSB_CLASS_AUDIO, 0, 0, _stridx, \
    TUD_AUDIO10_DESC_STD_AC(_ac_itf, 0, _stridx), \
    TUD_AUDIO10_DESC_CS_AC(0x0100, \
                           2 * (TUD_AUDIO10_DESC_INPUT_TERM_LEN + \
                                TUD_AUDIO10_DESC_OUTPUT_TERM_LEN), \
                           _speaker_as, _mic_as), \
    TUD_AUDIO10_DESC_INPUT_TERM(1, AUDIO_TERM_TYPE_USB_STREAMING, 0, \
                                UAC_CHANNEL_COUNT, AUDIO10_CHANNEL_CONFIG_NON_PREDEFINED, \
                                0, 0), \
    TUD_AUDIO10_DESC_OUTPUT_TERM(2, AUDIO_TERM_TYPE_OUT_GENERIC_SPEAKER, 0, 1, 0), \
    TUD_AUDIO10_DESC_INPUT_TERM(3, AUDIO_TERM_TYPE_IN_GENERIC_MIC, 0, \
                                UAC_CHANNEL_COUNT, AUDIO10_CHANNEL_CONFIG_NON_PREDEFINED, \
                                0, 0), \
    TUD_AUDIO10_DESC_OUTPUT_TERM(4, AUDIO_TERM_TYPE_USB_STREAMING, 0, 3, 0), \
    TUD_AUDIO10_DESC_STD_AS_INT(_speaker_as, 0, 0, 0), \
    TUD_AUDIO10_DESC_STD_AS_INT(_speaker_as, 1, 1, 0), \
    TUD_AUDIO10_DESC_CS_AS_INT(1, 1, AUDIO10_DATA_FORMAT_TYPE_I_PCM), \
    TUD_AUDIO10_DESC_TYPE_I_FORMAT(UAC_CHANNEL_COUNT, UAC_BYTES_PER_SAMPLE, 16, \
                                   UAC_SAMPLE_RATE), \
    TUD_AUDIO10_DESC_STD_AS_ISO_EP(_epout, \
                                   TUSB_XFER_ISOCHRONOUS | TUSB_ISO_EP_ATT_ADAPTIVE, \
                                   UAC_EP_OUT_SIZE, 1, 0), \
    TUD_AUDIO10_DESC_CS_AS_ISO_EP(AUDIO10_CS_AS_ISO_DATA_EP_ATT_SAMPLING_FRQ, \
                                  AUDIO10_CS_AS_ISO_DATA_EP_LOCK_DELAY_UNIT_UNDEFINED, 0), \
    TUD_AUDIO10_DESC_STD_AS_INT(_mic_as, 0, 0, 0), \
    TUD_AUDIO10_DESC_STD_AS_INT(_mic_as, 1, 1, 0), \
    TUD_AUDIO10_DESC_CS_AS_INT(4, 1, AUDIO10_DATA_FORMAT_TYPE_I_PCM), \
    TUD_AUDIO10_DESC_TYPE_I_FORMAT(UAC_CHANNEL_COUNT, UAC_BYTES_PER_SAMPLE, 16, \
                                   UAC_SAMPLE_RATE), \
    TUD_AUDIO10_DESC_STD_AS_ISO_EP(_epin, \
                                   TUSB_XFER_ISOCHRONOUS | TUSB_ISO_EP_ATT_ASYNCHRONOUS, \
                                   UAC_EP_IN_SIZE, 1, 0), \
    TUD_AUDIO10_DESC_CS_AS_ISO_EP(AUDIO10_CS_AS_ISO_DATA_EP_ATT_SAMPLING_FRQ, \
                                  AUDIO10_CS_AS_ISO_DATA_EP_LOCK_DELAY_UNIT_MILLISEC, 1)

/* 配置描述符：IF0 GUD + IF1/2/3 UAC1 audio + IF4 HID keyboard。 */
#define CONFIG_TOTAL_LEN (TUD_CONFIG_DESC_LEN + TUD_VENDOR_DESC_LEN + \
                          UAC1_AUDIO_DESC_LEN + TUD_HID_DESC_LEN)
const uint8_t aio_desc_configuration[] = {
    TUD_CONFIG_DESCRIPTOR(1, ITF_NUM_TOTAL, 0, CONFIG_TOTAL_LEN, 0x00, 100),
    TUD_VENDOR_DESCRIPTOR(ITF_NUM_VENDOR, 0, EPNUM_VENDOR_OUT, EPNUM_VENDOR_IN, 64),
    UAC1_AUDIO_DESCRIPTOR(ITF_NUM_AUDIO_CONTROL, ITF_NUM_AUDIO_STREAMING_OUT,
                          ITF_NUM_AUDIO_STREAMING_IN, 4, EPNUM_AUDIO_OUT,
                          EPNUM_AUDIO_IN),
    TUD_HID_DESCRIPTOR(ITF_NUM_HID, 0, HID_ITF_PROTOCOL_KEYBOARD,
                       sizeof(aio_hid_report_desc), EPNUM_HID, CFG_TUD_HID_EP_BUFSIZE, 10),
};

_Static_assert(sizeof(aio_desc_configuration) == CONFIG_TOTAL_LEN,
               "USB 配置描述符长度不一致");

/*
 * 字符串描述符：交由 esp_tinyusb 完成 UTF-16 转换与 langid 处理。
 * 索引 0 = langid（English, 0x0409），1=厂商 2=产品 3=序列号 4=音频功能。
 */
static const char k_langid[] = {0x09, 0x04, 0x00};
const char *aio_string_desc_arr[] = {
    k_langid,
    "flange",
    "Cardputer GUD Display",
    "AIO-0001",
    "Cardputer Audio",
};
const int aio_string_desc_count = sizeof(aio_string_desc_arr) / sizeof(aio_string_desc_arr[0]);

/*
 * HID 回调：esp_tinyusb 仅实现 tud_descriptor_*_cb，不实现以下 HID 弱回调，
 * 故由本固件提供（与 gud_device.c 提供 tud_vendor_control_xfer_cb 同理）。
 * report 描述符直接返回静态数组；get/set report 本任务无需处理。
 */
uint8_t const *tud_hid_descriptor_report_cb(uint8_t instance)
{
    (void)instance;
    return aio_hid_report_desc;
}

uint16_t tud_hid_get_report_cb(uint8_t instance, uint8_t report_id,
                               hid_report_type_t report_type, uint8_t *buffer, uint16_t reqlen)
{
    (void)instance;
    (void)report_id;
    (void)report_type;
    (void)buffer;
    (void)reqlen;
    return 0;
}

void tud_hid_set_report_cb(uint8_t instance, uint8_t report_id,
                           hid_report_type_t report_type, uint8_t const *buffer, uint16_t bufsize)
{
    (void)instance;
    (void)report_id;
    (void)report_type;
    (void)buffer;
    (void)bufsize;
}
