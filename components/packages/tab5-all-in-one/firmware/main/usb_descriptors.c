#include "usb_descriptors.h"
/* 只为 TOUCH_HID_LOGICAL_MAX：报告描述符声明的 Logical Maximum 与
 * touch_map_gud_to_hid() 归一化用的上限必须是同一个数，分开写迟早会漂。 */
#include "touch_map.h"

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

/*
 * RID 2：单点 digitizer（触摸屏）。TinyUSB 没有现成的 digitizer 描述符宏
 * （只有 keyboard/mouse/consumer/gamepad 等），按 HID Usage Tables 的
 * Digitizers 页(0x0D)手写。用 HID_* 宏而非裸字节数组：每个 item 的 tag/type/size
 * 由宏算，改一处不会连累相邻字节。
 *
 * 单点最小可用形态，负载共 5 字节：
 *   Tip Switch 1 bit + 7 bit 填充（补齐到字节边界）+ 绝对 X/Y 各 16 bit
 * X/Y 归一化到 0..TOUCH_HID_LOGICAL_MAX，描述符因此不与 GUD 分辨率耦死 ——
 * 换分辨率只改 touch_map 的归一化，这里不动。
 *
 * host 侧预期：本描述符没有 Contact Count / Contact Identifier，也没有 Win8
 * 认证要的那份 Contact Count Maximum Feature 报告，所以 Linux 的 hid-core
 * 不会把它划进 HID_GROUP_MULTITOUCH，走的是 hid-generic + hid-input ——
 * Tip Switch → BTN_TOUCH、Generic Desktop X/Y(绝对) → ABS_X/ABS_Y，
 * 正好是单点绝对定位要的形态。多点留到后续阶段。
 */
#define AIO_HID_REPORT_DESC_TOUCH \
    HID_USAGE_PAGE ( HID_USAGE_PAGE_DIGITIZER                    ) ,\
    HID_USAGE      ( HID_USAGE_DIGITIZER_TOUCH_SCREEN            ) ,\
    HID_COLLECTION ( HID_COLLECTION_APPLICATION                  ) ,\
      HID_REPORT_ID( HID_RID_TOUCH                               ) \
      /* 一个手指 = 一个 Logical Collection；多点时就是复制这一段 */ \
      HID_USAGE      ( HID_USAGE_DIGITIZER_FINGER                ) ,\
      HID_COLLECTION ( HID_COLLECTION_LOGICAL                    ) ,\
        /* Tip Switch：1 = 手指接触屏面。host 映射成 BTN_TOUCH */ \
        HID_USAGE      ( HID_USAGE_DIGITIZER_TIP_SWITCH          ) ,\
        HID_LOGICAL_MIN( 0                                       ) ,\
        HID_LOGICAL_MAX( 1                                       ) ,\
        HID_REPORT_SIZE( 1                                       ) ,\
        HID_REPORT_COUNT(1                                       ) ,\
        HID_INPUT      ( HID_DATA | HID_VARIABLE | HID_ABSOLUTE  ) ,\
        /* 7 bit 常量填充：把 tip 补齐成整字节，好让后面的 16bit X/Y 字节对齐，
         * 也让 C 侧 touch_report_t 能直接是 {uint8_t; uint16_t; uint16_t} */ \
        HID_REPORT_SIZE( 7                                       ) ,\
        HID_REPORT_COUNT(1                                       ) ,\
        HID_INPUT      ( HID_CONSTANT | HID_VARIABLE | HID_ABSOLUTE ) ,\
        /* X/Y 用 Generic Desktop 页的 X/Y（不是 Digitizer 页）——
         * hid-input 只认这一组来生成 ABS_X/ABS_Y */ \
        HID_USAGE_PAGE ( HID_USAGE_PAGE_DESKTOP                  ) ,\
        HID_LOGICAL_MIN( 0                                       ) ,\
        HID_LOGICAL_MAX_N( TOUCH_HID_LOGICAL_MAX, 2              ) ,\
        HID_REPORT_SIZE( 16                                      ) ,\
        HID_REPORT_COUNT(1                                       ) ,\
        HID_USAGE      ( HID_USAGE_DESKTOP_X                     ) ,\
        HID_INPUT      ( HID_DATA | HID_VARIABLE | HID_ABSOLUTE  ) ,\
        HID_USAGE      ( HID_USAGE_DESKTOP_Y                     ) ,\
        HID_INPUT      ( HID_DATA | HID_VARIABLE | HID_ABSOLUTE  ) ,\
      HID_COLLECTION_END                                            ,\
    HID_COLLECTION_END

/* 标准键盘(RID 1) + 单点 digitizer(RID 2)，同一份报告描述符、同一条端点。 */
static const uint8_t aio_hid_report_desc[] = {
    TUD_HID_REPORT_DESC_KEYBOARD(HID_REPORT_ID(HID_RID_KEYBOARD)),
    AIO_HID_REPORT_DESC_TOUCH
};

/* 配置描述符：IF0 = GUD vendor，IF1 = HID 键盘 + 触摸。 */
#define CONFIG_TOTAL_LEN (TUD_CONFIG_DESC_LEN + TUD_VENDOR_DESC_LEN + TUD_HID_DESC_LEN)
const uint8_t aio_desc_configuration[] = {
    TUD_CONFIG_DESCRIPTOR(1, ITF_NUM_TOTAL, 0, CONFIG_TOTAL_LEN, 0x00, 100),
    TUD_VENDOR_DESCRIPTOR(ITF_NUM_VENDOR, 0, EPNUM_VENDOR_OUT, EPNUM_VENDOR_IN, 64),
    /*
     * bInterfaceProtocol = NONE（原先是 KEYBOARD）。
     *
     * 传 HID_ITF_PROTOCOL_KEYBOARD 会把 bInterfaceSubClass 一并设成 BOOT，
     * 即向 host 声明「本接口支持 boot keyboard 协议」。但 boot 协议**不允许
     * Report ID**（boot 报告是固定 8 字节裸格式），而本接口现在同时承载
     * 键盘(RID 1)与 digitizer(RID 2)、必须靠 Report ID 区分 —— 两者在规范上
     * 互斥，继续声明 BOOT 就是在说谎。
     *
     * 代价：BIOS/UEFI/GRUB 这类只会 SET_PROTOCOL(boot) 的早期环境不再能把它
     * 当键盘用。本产品形态是「接一台已启动的 Linux 主机的 USB 瘦终端」，
     * 不涉及那个阶段。Linux 的 usbhid 默认就走 report 协议，日常零影响。
     */
    TUD_HID_DESCRIPTOR(ITF_NUM_HID, 0, HID_ITF_PROTOCOL_NONE,
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
    "Tab5 USB Terminal",
    "TAB5-0001",
};
const int aio_string_desc_count = sizeof(aio_string_desc_arr) / sizeof(aio_string_desc_arr[0]);
