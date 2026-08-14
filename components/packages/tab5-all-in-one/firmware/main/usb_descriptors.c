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
 * ── UAC1（Audio Class 1.0）复合功能：一个 AudioControl 接口管两条 AudioStreaming ──
 *
 * TinyUSB 0.21 有完整的 TUD_AUDIO10_* 底层模板（src/device/usbd.h），但**没有**
 * 「播放 + 录音」的整功能模板（只有 TUD_AUDIO10_MIC_ONE_CH_DESCRIPTOR，单麦且不带
 * IAD），所以这套布局要自己拼。底稿取自 cardputer-all-in-one/firmware/main/
 * usb_descriptors.c，那边这套「1×AC + 播放 AS + 录音 AS」已实机跑通。
 *
 * 拓扑（terminal ID 是本文件内自洽的编号，被 baSourceID 交叉引用）：
 *   播放：ID1 输入端子(USB Streaming) → ID2 输出端子(Speaker)
 *   录音：ID3 输入端子(Microphone)    → ID4 输出端子(USB Streaming)
 *
 * 不放 Feature Unit（音量/静音）：host 侧软件音量已经够用，而 Feature Unit 会引入
 * 一组必须正确应答的 GET/SET_CUR 控制请求 —— 应答错了 snd-usb-audio 在 probe 阶段
 * 就报错，属于典型的「加了功能反而不能用」。要做也该等基础通路稳了再说。
 *
 * ⚠️ 两条 ISO 端点的 **bSynchAddress 都填 0**（宏的最后一个参数），即没有显式
 * 反馈端点 —— 反馈端点会占掉第 4 条 IN(0x84)，把 UVC 顶掉，见 usb_descriptors.h
 * 的端点表。异步 IN 本来就不需要反馈（反馈是给异步 **OUT** sink 用的，IN 方向
 * 设备是时钟主控）；adaptive OUT sink 靠自己吸收速率差，也不需要。
 *
 * ⚠️ 与之配对的一个静默陷阱：bmAttributes 的 sync 字段**绝不能填 0**
 * （TUSB_ISO_EP_ATT_NO_SYNC）。audio_device.c 的 UAC1 分支正是靠
 * `sync == TUSB_ISO_EP_ATT_NO_SYNC` 判定「这是一条反馈端点」的 —— 填 0 会让
 * TinyUSB 把我们的数据端点当成反馈端点，数据永远发不出去，而枚举一切正常。
 * 下面播放用 ADAPTIVE、录音用 ASYNCHRONOUS，两者都非 0；
 * test/check_usb_desc.py 有专门一条断言守着这两件事。
 */
#if CONFIG_AIO_AUDIO_DESC

#define UAC1_STREAM_DESC_LEN (TUD_AUDIO10_DESC_STD_AS_LEN * 2 + \
                              TUD_AUDIO10_DESC_CS_AS_INT_LEN + \
                              TUD_AUDIO10_DESC_TYPE_I_FORMAT_LEN(1) + \
                              TUD_AUDIO10_DESC_STD_AS_ISO_EP_LEN + \
                              TUD_AUDIO10_DESC_CS_AS_ISO_EP_LEN)

#define UAC1_AUDIO_DESC_LEN (8 /* IAD */ + \
                             TUD_AUDIO10_DESC_STD_AC_LEN + \
                             TUD_AUDIO10_DESC_CS_AC_LEN(2) + \
                             2 * (TUD_AUDIO10_DESC_INPUT_TERM_LEN + \
                                  TUD_AUDIO10_DESC_OUTPUT_TERM_LEN) + \
                             2 * UAC1_STREAM_DESC_LEN)

#define UAC1_AUDIO_DESCRIPTOR(_ac_itf, _spk_as, _mic_as, _stridx, _epout, _epin) \
    /* IAD：告诉 host「这 3 个接口是一个音频功能」，snd-usb-audio 靠它成组绑定。
     * 设备描述符已经是 Misc/IAD(239/2/1)，不必为它再改。 */ \
    8, TUSB_DESC_INTERFACE_ASSOCIATION, _ac_itf, 3, TUSB_CLASS_AUDIO, 0, 0, _stridx, \
    TUD_AUDIO10_DESC_STD_AC(_ac_itf, 0 /* 无中断端点：省一条 IN */, _stridx), \
    /* 第二个参数是「下属单元/端子描述符的总字节数」，宏自己会把 AC 头的长度加进去 */ \
    TUD_AUDIO10_DESC_CS_AC(0x0100 /* bcdADC = UAC 1.0 */, \
                           2 * (TUD_AUDIO10_DESC_INPUT_TERM_LEN + \
                                TUD_AUDIO10_DESC_OUTPUT_TERM_LEN), \
                           _spk_as, _mic_as /* baInterfaceNr[]，必须指向两个 AS 接口 */), \
    /* 播放链：USB 流 → 喇叭 */ \
    TUD_AUDIO10_DESC_INPUT_TERM(1, AUDIO_TERM_TYPE_USB_STREAMING, 0, \
                                UAC_CHANNEL_COUNT, AUDIO10_CHANNEL_CONFIG_NON_PREDEFINED, 0, 0), \
    TUD_AUDIO10_DESC_OUTPUT_TERM(2, AUDIO_TERM_TYPE_OUT_GENERIC_SPEAKER, 0, 1 /* ← ID1 */, 0), \
    /* 录音链：麦克风 → USB 流 */ \
    TUD_AUDIO10_DESC_INPUT_TERM(3, AUDIO_TERM_TYPE_IN_GENERIC_MIC, 0, \
                                UAC_CHANNEL_COUNT, AUDIO10_CHANNEL_CONFIG_NON_PREDEFINED, 0, 0), \
    TUD_AUDIO10_DESC_OUTPUT_TERM(4, AUDIO_TERM_TYPE_USB_STREAMING, 0, 3 /* ← ID3 */, 0), \
    /* ── 播放 AS：alt 0 = 零带宽（host 不放音时不占 ISO 预留），alt 1 = 带端点 ── */ \
    TUD_AUDIO10_DESC_STD_AS_INT(_spk_as, 0, 0, 0), \
    TUD_AUDIO10_DESC_STD_AS_INT(_spk_as, 1, 1, 0), \
    TUD_AUDIO10_DESC_CS_AS_INT(1 /* bTerminalLink → ID1 */, 1, AUDIO10_DATA_FORMAT_TYPE_I_PCM), \
    TUD_AUDIO10_DESC_TYPE_I_FORMAT(UAC_CHANNEL_COUNT, UAC_BYTES_PER_SAMPLE, 16, UAC_SAMPLE_RATE), \
    /* adaptive sink：设备自己吸收速率差。末参 0 = bSynchAddress，见上方 ⚠️ */ \
    TUD_AUDIO10_DESC_STD_AS_ISO_EP(_epout, \
                                   TUSB_XFER_ISOCHRONOUS | TUSB_ISO_EP_ATT_ADAPTIVE, \
                                   UAC_EP_OUT_SIZE, 1 /* bInterval = 每帧 */, 0), \
    TUD_AUDIO10_DESC_CS_AS_ISO_EP(AUDIO10_CS_AS_ISO_DATA_EP_ATT_SAMPLING_FRQ, \
                                  AUDIO10_CS_AS_ISO_DATA_EP_LOCK_DELAY_UNIT_UNDEFINED, 0), \
    /* ── 录音 AS ── */ \
    TUD_AUDIO10_DESC_STD_AS_INT(_mic_as, 0, 0, 0), \
    TUD_AUDIO10_DESC_STD_AS_INT(_mic_as, 1, 1, 0), \
    TUD_AUDIO10_DESC_CS_AS_INT(4 /* bTerminalLink → ID4 */, 1, AUDIO10_DATA_FORMAT_TYPE_I_PCM), \
    TUD_AUDIO10_DESC_TYPE_I_FORMAT(UAC_CHANNEL_COUNT, UAC_BYTES_PER_SAMPLE, 16, UAC_SAMPLE_RATE), \
    /* asynchronous source：设备按自己的 I2S 时钟出数据，每帧发几个样本由
     * CFG_TUD_AUDIO_EP_IN_FLOW_CONTROL 按软件 FIFO 水位决定（标称 ±1）。
     * 同样 bSynchAddress = 0。 */ \
    TUD_AUDIO10_DESC_STD_AS_ISO_EP(_epin, \
                                   TUSB_XFER_ISOCHRONOUS | TUSB_ISO_EP_ATT_ASYNCHRONOUS, \
                                   UAC_EP_IN_SIZE, 1, 0), \
    TUD_AUDIO10_DESC_CS_AS_ISO_EP(AUDIO10_CS_AS_ISO_DATA_EP_ATT_SAMPLING_FRQ, \
                                  AUDIO10_CS_AS_ISO_DATA_EP_LOCK_DELAY_UNIT_MILLISEC, 1)

/* 音频功能的字符串索引，同时是 IAD 与三个音频接口的 iInterface。
 * 与下方 aio_string_desc_arr 的第 5 个元素对应，两处改一处必错，故在此定名。 */
#define AIO_STRID_AUDIO 4

#else /* !CONFIG_AIO_AUDIO_DESC：音频默认关闭，见 main/Kconfig.projbuild */

#define UAC1_AUDIO_DESC_LEN 0
#define AIO_STRID_AUDIO     4   /* 字符串数组不随音频增删，索引保持稳定 */

#endif

/*
 * 配置描述符：IF0 = GUD vendor，IF1 = HID 键盘 + 触摸，
 * IF2/IF3/IF4 = UAC1 音频（AudioControl + 播放 AS + 录音 AS，由 IAD 成组）。
 *
 * 音频排在 HID **之后**：接口号对 host 侧没有功能影响（drm/gud 按 VID/PID + 接口类
 * 绑定，usbhid / hid-multitouch 按接口类绑定，snd-usb-audio 按 IAD + 接口类绑定，
 * 没有任何一方按接口号绑定），所以宁可不动已实机验证的 IF0/IF1。
 * 端点号同理刻意不动（0x81 / 0x82），少一个变量。
 */
#define CONFIG_TOTAL_LEN \
    (TUD_CONFIG_DESC_LEN + TUD_VENDOR_DESC_LEN + TUD_HID_DESC_LEN + UAC1_AUDIO_DESC_LEN)
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
#if CONFIG_AIO_AUDIO_DESC
    UAC1_AUDIO_DESCRIPTOR(ITF_NUM_AUDIO_CONTROL, ITF_NUM_AUDIO_STREAMING_OUT,
                          ITF_NUM_AUDIO_STREAMING_IN, AIO_STRID_AUDIO,
                          EPNUM_AUDIO_OUT, EPNUM_AUDIO_IN),
#endif
};

_Static_assert(sizeof(aio_desc_configuration) == CONFIG_TOTAL_LEN,
               "USB 配置描述符长度不一致");

/*
 * 描述符声明的端点大小与 tinyusb_config/tusb_config.h 给驱动的上限对账。
 * 两者分处两个文件、无法互相 include，只能靠断言钉住 —— 不一致时 TinyUSB 会在
 * 收发路径上截断或拒绝，而枚举完全正常，症状极难归因。
 */
#if CONFIG_AIO_AUDIO_DESC
_Static_assert(UAC_EP_OUT_SIZE <= CFG_TUD_AUDIO_FUNC_1_EP_OUT_SZ_MAX,
               "描述符声明的播放端点大小超过 tusb_config.h 里给驱动的上限");
_Static_assert(UAC_EP_IN_SIZE <= CFG_TUD_AUDIO_FUNC_1_EP_IN_SZ_MAX,
               "描述符声明的录音端点大小超过 tusb_config.h 里给驱动的上限");
_Static_assert(CFG_TUD_AUDIO_ENABLE_FEEDBACK_EP == 0,
               "全速控制器只有 4 条可用 IN 端点，反馈端点会顶掉 UVC 的位置");
#endif

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
 * 4 = 音频功能（须等于 AIO_STRID_AUDIO，是 IAD 与三个音频接口的 iInterface）。
 * aio_string_desc_count 由 sizeof/sizeof 自动算，增删元素不用手改。
 */
static const char k_langid[] = {0x09, 0x04, 0x00};
const char *aio_string_desc_arr[] = {
    k_langid,
    "flange",
    "Tab5 USB Terminal",
    "TAB5-0001",
    "Tab5 Audio",
};
const int aio_string_desc_count = sizeof(aio_string_desc_arr) / sizeof(aio_string_desc_arr[0]);

/* 把 UAC1_AUDIO_DESCRIPTOR 的 _stridx 与字符串数组钉在一起：在数组中间插一条新
 * 字符串却忘了改 AIO_STRID_AUDIO，host 侧只表现为「声卡名字不对」，几乎不会有人
 * 去查描述符。 */
_Static_assert(sizeof(aio_string_desc_arr) / sizeof(aio_string_desc_arr[0]) == AIO_STRID_AUDIO + 1,
               "音频字符串必须位于索引 AIO_STRID_AUDIO（当前是数组最后一个）");
