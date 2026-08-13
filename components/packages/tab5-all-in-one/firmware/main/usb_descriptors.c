#include "usb_descriptors.h"
/* 为 TOUCH_HID_LOGICAL_MAX 与 TOUCH_CONTACTS_MAX：报告描述符声明的
 * Logical Maximum / contact 数，必须与 touch_map 那边的归一化上限、
 * touch_report_t 的 slot 数是同一个数，分开写迟早会漂。 */
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
 * 一个 contact（手指）在报告描述符里的那一段。TOUCH_CONTACTS_MAX 份
 * 逐字相同，所以做成宏重复展开 —— 手写五遍必然出现不一致，而这类不一致
 * 在 host 侧只表现为「某几根手指坐标错位」，从现象几乎反推不出来。
 *
 * 负载 6 字节，与 touch_map.h 的 touch_contact_t 逐位对应：
 *   Tip Switch 1 bit + 7 bit 常量填充 + Contact Identifier 8 bit
 *   + 绝对 X/Y 各 16 bit
 *
 * ⚠️ 结尾那句 HID_USAGE_PAGE(DIGITIZER) 不是冗余：Usage Page 是 **Global**
 * item，会一直生效到下次改写。段内为了 X/Y 切到了 Generic Desktop 页，
 * 不切回来的话，下一份 contact 的 Usage(Finger)/Usage(Tip Switch) 以及
 * 段尾的 Contact Count 全会被解析成 Desktop 页里同号的 usage，整份描述符报废。
 */
#define AIO_TOUCH_CONTACT_DESC \
      HID_USAGE      ( HID_USAGE_DIGITIZER_FINGER                ) ,\
      HID_COLLECTION ( HID_COLLECTION_LOGICAL                    ) ,\
        /* Tip Switch：1 = 手指接触屏面。hid-multitouch 靠它 + Contact
         * Identifier 才把本设备认成多点触摸屏 */ \
        HID_USAGE      ( HID_USAGE_DIGITIZER_TIP_SWITCH          ) ,\
        HID_LOGICAL_MIN( 0                                       ) ,\
        HID_LOGICAL_MAX( 1                                       ) ,\
        HID_REPORT_SIZE( 1                                       ) ,\
        HID_REPORT_COUNT(1                                       ) ,\
        HID_INPUT      ( HID_DATA | HID_VARIABLE | HID_ABSOLUTE  ) ,\
        /* 7 bit 常量填充：把 tip 补齐成整字节，好让后面的字段字节对齐，
         * 也让 C 侧 touch_contact_t 能直接是 {u8; u8; u16; u16} */ \
        HID_REPORT_SIZE( 7                                       ) ,\
        HID_REPORT_COUNT(1                                       ) ,\
        HID_INPUT      ( HID_CONSTANT | HID_VARIABLE | HID_ABSOLUTE ) ,\
        /* Contact Identifier：同一根手指在按住期间保持同一个 id，
         * host 靠它把帧与帧之间的触点连成轨迹（→ ABS_MT_TRACKING_ID）。
         * ⚠️ Logical Maximum 255 必须用 2 字节编码：HID 的 logical min/max
         * 是**有符号**量，单字节 0xFF 会被解成 -1。 */ \
        HID_USAGE      ( HID_USAGE_DIGITIZER_CONTACT_IDENTIFIER  ) ,\
        HID_LOGICAL_MAX_N( 255, 2                                ) ,\
        HID_REPORT_SIZE( 8                                       ) ,\
        HID_REPORT_COUNT(1                                       ) ,\
        HID_INPUT      ( HID_DATA | HID_VARIABLE | HID_ABSOLUTE  ) ,\
        /* X/Y 用 Generic Desktop 页的 X/Y（不是 Digitizer 页）——
         * hid-input / hid-multitouch 只认这一组来生成 ABS_MT_POSITION_X/Y */ \
        HID_USAGE_PAGE ( HID_USAGE_PAGE_DESKTOP                  ) ,\
        HID_LOGICAL_MAX_N( TOUCH_HID_LOGICAL_MAX, 2              ) ,\
        HID_REPORT_SIZE( 16                                      ) ,\
        HID_REPORT_COUNT(1                                       ) ,\
        HID_USAGE      ( HID_USAGE_DESKTOP_X                     ) ,\
        HID_INPUT      ( HID_DATA | HID_VARIABLE | HID_ABSOLUTE  ) ,\
        HID_USAGE      ( HID_USAGE_DESKTOP_Y                     ) ,\
        HID_INPUT      ( HID_DATA | HID_VARIABLE | HID_ABSOLUTE  ) ,\
        /* 切回 Digitizer 页，见上方 ⚠️ */ \
        HID_USAGE_PAGE ( HID_USAGE_PAGE_DIGITIZER                ) ,\
      HID_COLLECTION_END                                            ,

/*
 * RID 2：多点 digitizer（触摸屏），最多 TOUCH_CONTACTS_MAX 个并发触点。
 * TinyUSB 没有现成的 digitizer 描述符宏（只有 keyboard/mouse/consumer/gamepad），
 * 按 HID Usage Tables 的 Digitizers 页(0x0D)手写。用 HID_* 宏而非裸字节数组：
 * 每个 item 的 tag/type/size 由宏算，改一处不会连累相邻字节。
 *
 * 负载共 sizeof(touch_report_t) = 31 字节：5 × 6 字节 contact + 1 字节 Contact Count。
 * X/Y 归一化到 0..TOUCH_HID_LOGICAL_MAX，描述符因此不与 GUD 分辨率耦死 ——
 * 换分辨率只改 touch_map 的归一化，这里不动。
 *
 * host 侧预期：Linux 的 hid-core 在扫描描述符时一见到 Input 里的
 * Contact Identifier(0x51) 就把设备划进 HID_GROUP_MULTITOUCH，交给
 * hid-multitouch 而不是 hid-generic；Contact Count Maximum 这份 Feature 报告
 * 则告诉它一次最多几个触点（应答见下方 tud_hid_get_report_cb）。
 * 结果是 ABS_MT_SLOT / ABS_MT_TRACKING_ID / ABS_MT_POSITION_X/Y 那套多点协议。
 *
 * ⚠️ 键盘(RID 1)也在这同一个 HID 接口上，因此会一并归 hid-multitouch 管。
 * 这不影响键盘：hid-multitouch 的 mt_input_mapping() 对
 * application == GenericDesktop/Keyboard 的字段直接返回 0，退回 hid-input 的
 * 默认处理，与之前 hid-generic 下的行为一致。
 */
#define AIO_HID_REPORT_DESC_TOUCH \
    HID_USAGE_PAGE ( HID_USAGE_PAGE_DIGITIZER                    ) ,\
    HID_USAGE      ( HID_USAGE_DIGITIZER_TOUCH_SCREEN            ) ,\
    HID_COLLECTION ( HID_COLLECTION_APPLICATION                  ) ,\
      HID_REPORT_ID( HID_RID_TOUCH                               ) \
      /* TOUCH_CONTACTS_MAX 份，逐字相同 —— 改数量要同时改这里的展开次数，
       * 漏改会被下方 sizeof(touch_report_t) 那条 _Static_assert 拦住。 */ \
      AIO_TOUCH_CONTACT_DESC \
      AIO_TOUCH_CONTACT_DESC \
      AIO_TOUCH_CONTACT_DESC \
      AIO_TOUCH_CONTACT_DESC \
      AIO_TOUCH_CONTACT_DESC \
      /* Contact Count：本帧实际有几个触点。host 据此只处理前 N 个 slot，
       * 其余 tip=0 的空槽被忽略；填 0 即「全部手指已抬起」。 */ \
      HID_USAGE      ( HID_USAGE_DIGITIZER_CONTACT_COUNT         ) ,\
      HID_LOGICAL_MIN( 0                                         ) ,\
      HID_LOGICAL_MAX( TOUCH_CONTACTS_MAX                        ) ,\
      HID_REPORT_SIZE( 8                                         ) ,\
      HID_REPORT_COUNT(1                                         ) ,\
      HID_INPUT      ( HID_DATA | HID_VARIABLE | HID_ABSOLUTE    ) ,\
      /* Contact Count Maximum：**Feature** 报告，不是 Input。
       * hid-multitouch 会主动 GET_REPORT(Feature, RID 2) 来读它，
       * 应答在 tud_hid_get_report_cb() 里。 */ \
      HID_USAGE      ( HID_USAGE_DIGITIZER_CONTACT_COUNT_MAXIMUM ) ,\
      HID_LOGICAL_MIN( 0                                         ) ,\
      HID_LOGICAL_MAX( TOUCH_CONTACTS_MAX                        ) ,\
      HID_REPORT_SIZE( 8                                         ) ,\
      HID_REPORT_COUNT(1                                         ) ,\
      HID_FEATURE    ( HID_DATA | HID_VARIABLE | HID_ABSOLUTE    ) ,\
    HID_COLLECTION_END

/* 描述符里展开了几份 contact，与 touch_report_t 的 slot 数必须一致。
 * 这里用报告总长把两边钉在一起：改了 TOUCH_CONTACTS_MAX 却忘了增删上面的
 * AIO_TOUCH_CONTACT_DESC，就会在这条断言上炸掉，而不是等到实机坐标乱跳。 */
_Static_assert(sizeof(touch_report_t) == 6 * 5 + 1,
               "报告描述符展开了 5 份 contact，TOUCH_CONTACTS_MAX 必须同步");

/* 标准键盘(RID 1) + 多点 digitizer(RID 2)，同一份报告描述符、同一条端点。 */
static const uint8_t aio_hid_report_desc[] = {
    TUD_HID_REPORT_DESC_KEYBOARD(HID_REPORT_ID(HID_RID_KEYBOARD)),
    AIO_HID_REPORT_DESC_TOUCH
};

/*
 * 配置描述符：IF0 = GUD vendor，IF1 = HID 键盘 + 触摸，
 * 可选 IF2/IF3 = CDC 调试串口（默认关闭，见 sdkconfig.defaults 末尾）。
 *
 * TUD_CDC_DESCRIPTOR **自带 IAD**，一段 TUD_CDC_DESC_LEN = 66 字节里含通信 + 数据
 * 两个接口；本设备描述符本来就是 Misc/IAD(239/2/1)，无需为它改设备描述符。
 */
#if CONFIG_TINYUSB_CDC_ENABLED
#define AIO_CDC_DESC_LEN TUD_CDC_DESC_LEN
/* 字符串索引 4，与下方 aio_string_desc_arr 的第 5 个元素对应，
 * 传给 TUD_CDC_DESCRIPTOR 的 _stridx。两处改一处必错，故在此定名。 */
#define AIO_STRID_CDC    4
#else
#define AIO_CDC_DESC_LEN 0
#endif

#define CONFIG_TOTAL_LEN \
    (TUD_CONFIG_DESC_LEN + TUD_VENDOR_DESC_LEN + TUD_HID_DESC_LEN + AIO_CDC_DESC_LEN)
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
#if CONFIG_TINYUSB_CDC_ENABLED
    /* 通知端点 8 字节即够：CDC ACM 的 SERIAL_STATE 通知负载最长 10 字节，
     * 且本工程只做单向日志输出、从不主动上报串口状态线。 */
    TUD_CDC_DESCRIPTOR(ITF_NUM_CDC, AIO_STRID_CDC, EPNUM_CDC_NOTIF, 8,
                       EPNUM_CDC_OUT, EPNUM_CDC_IN, 64),
#endif
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

/*
 * 目前只应答一件事：Contact Count Maximum（RID 2 的 Feature 报告）。
 *
 * 这不是可选项 —— Linux 的 hid-multitouch 在 probe 时会 GET_REPORT(Feature)
 * 读这个值来决定分配几个 MT slot；STALL 或返回空会让它退回默认值甚至
 * 判定设备不完整。多点触摸能不能真正生效，就差这一个字节。
 *
 * ⚠️ buffer 里**不要**再写 Report ID：TinyUSB 已经在 hid_device.c 的
 * GET_REPORT 分支里把它作为第一字节写进去，并把 buffer 指针后移了一格。
 * 这里只填负载，返回负载长度。
 */
uint16_t tud_hid_get_report_cb(uint8_t instance, uint8_t report_id,
                               hid_report_type_t report_type, uint8_t *buffer, uint16_t reqlen)
{
    (void)instance;

    if (report_type == HID_REPORT_TYPE_FEATURE && report_id == HID_RID_TOUCH && reqlen >= 1) {
        buffer[0] = TOUCH_CONTACTS_MAX;
        return 1;
    }

    /* 其余一律不应答（返回 0）。 */
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
 * 索引 0 = langid（English, 0x0409），1=厂商 2=产品 3=序列号，
 * 4 = CDC 调试串口（仅在 CONFIG_TINYUSB_CDC_ENABLED 时存在，须等于 AIO_STRID_CDC）。
 * aio_string_desc_count 由 sizeof/sizeof 自动算，增删元素不用手改。
 */
static const char k_langid[] = {0x09, 0x04, 0x00};
const char *aio_string_desc_arr[] = {
    k_langid,
    "flange",
    "Tab5 USB Terminal",
    "TAB5-0001",
#if CONFIG_TINYUSB_CDC_ENABLED
    "Tab5 Debug Console",
#endif
};
const int aio_string_desc_count = sizeof(aio_string_desc_arr) / sizeof(aio_string_desc_arr[0]);

#if CONFIG_TINYUSB_CDC_ENABLED
/* 把 TUD_CDC_DESCRIPTOR 的 _stridx 与字符串数组钉在一起：在数组中间插一条新字符串
 * 却忘了改 AIO_STRID_CDC，host 侧只表现为「串口名字不对」，几乎不会有人去查描述符。 */
_Static_assert(sizeof(aio_string_desc_arr) / sizeof(aio_string_desc_arr[0]) == AIO_STRID_CDC + 1,
               "CDC 字符串必须位于索引 AIO_STRID_CDC（当前是数组最后一个）");
#endif
