#pragma once
/*
 * 触摸坐标反变换：面板原生坐标 → host 看到的 GUD 坐标。
 *
 * 纯函数，不依赖 ESP-IDF —— 与 kbd_translate.c 同样的理由：这段算式
 * 完全可以在宿主机验证，且写错了在实机上只表现为「点哪儿指针跑到别处」，
 * 极难从现象反推。见 firmware/test/test_touch_map.c。
 */
#include <stdint.h>

/*
 * 把面板原生坐标(720×1280 竖向)还原成 host 看到的 GUD 坐标(640×360 横向)，
 * 与 display_blit() 的 2× 放大 + 90° CCW 旋转互逆。
 *
 * 入参会先被钳到面板范围内（触摸控制器可能报出略超范围的值），因此输出
 * 必然落在 [0,GUD_W-1] × [0,GUD_H-1]。gud_x / gud_y 由调用者提供存储。
 */
void touch_map_panel_to_gud(uint16_t panel_x, uint16_t panel_y,
                            uint16_t *gud_x, uint16_t *gud_y);

/*
 * HID digitizer 报告里 X/Y 的 Logical Maximum。报告描述符与下面的归一化
 * 共用这一个常量（usb_descriptors.c 为此包含本头文件）—— 两处写死不同的数
 * 只会表现为「指针位置按比例偏移」，从现象很难反推。
 *
 * 取 32767 而非 65535：Logical Maximum 在 HID 里是**有符号**量，超过 32767
 * 就得用 3/4 字节编码并小心正负，没必要。
 */
#define TOUCH_HID_LOGICAL_MAX 32767

/*
 * 把 GUD 坐标归一化成 HID 逻辑值 [0, TOUCH_HID_LOGICAL_MAX]。
 * gud_max 传该轴的最大合法坐标（GUD_W-1 / GUD_H-1），入参超界会先钳到它。
 *
 * 归一化让报告描述符与 GUD 分辨率解耦：换分辨率只改调用方传的 gud_max。
 * gud_max 必须非 0（调用方传的都是编译期常量 639 / 359）。
 */
uint16_t touch_map_gud_to_hid(uint16_t gud, uint16_t gud_max);

/*
 * 同时上报的最大触点数。**三处必须共用这一个常量**：
 *   1) usb_descriptors.c 的报告描述符（展开几份 contact collection、
 *      Contact Count / Contact Count Maximum 的 Logical Maximum）；
 *   2) 下面 touch_report_t 的 slot 数；
 *   3) tud_hid_get_report_cb() 里 Contact Count Maximum 这份 Feature 报告的应答值。
 * 各写各的话，host 解出来的触点数与报告实际长度对不上，症状是坐标全乱。
 *
 * 取 5 而非更大：GT911 本身按 CONFIG_ESP_LCD_TOUCH_MAX_POINTS=5 上报，
 * 再多的 slot 永远填不满，只是白占端点带宽。
 */
#define TOUCH_CONTACTS_MAX 5

/*
 * 单个触点在 HID 报告里的布局，逐位对应 usb_descriptors.c 里
 * AIO_TOUCH_CONTACT_DESC 展开出的一份 contact collection。
 *
 * packed 是必需的：不加的话 uint16_t 前会插对齐填充，x/y 整体后移，
 * host 解出来的坐标全是垃圾。
 * 字节序：HID 规定小端，P4(RISC-V) 与宿主机本就是小端，直接发结构体即可。
 */
typedef struct __attribute__((packed)) {
    uint8_t  tip;         /* bit0 = 接触中；高 7 位是描述符里那段常量填充 */
    uint8_t  contact_id;  /* Contact Identifier，取触摸控制器的 track_id */
    uint16_t x;           /* 归一化到 [0, TOUCH_HID_LOGICAL_MAX] 的绝对坐标 */
    uint16_t y;
} touch_contact_t;

/* RID 2 的完整报告负载：定长 TOUCH_CONTACTS_MAX 个 slot + 接触点数。 */
typedef struct __attribute__((packed)) {
    touch_contact_t contacts[TOUCH_CONTACTS_MAX];
    uint8_t         contact_count;
} touch_report_t;

/* 钉死尺寸：描述符与结构体一旦不同步，host 解出来全是垃圾，而这种错
 * 在实机上只表现为「坐标乱跳」，极难反推。 */
_Static_assert(sizeof(touch_contact_t) == 6, "contact 应为 1+1+2+2 字节");
_Static_assert(sizeof(touch_report_t) == 6 * TOUCH_CONTACTS_MAX + 1,
               "digitizer 报告应为 5 个 contact + 1 字节接触点数");

/*
 * 把 n 个活跃触点装进定长报告：前 min(n, TOUCH_CONTACTS_MAX) 个 slot 取
 * active[] 的 contact_id / x / y 并置 tip=1，其余 slot 整体清零（tip=0），
 * contact_count 填实际装入的个数。
 *
 * active[i].tip **会被忽略并覆盖**成 1 —— 由本函数统一置位，
 * 「contact_count 恒等于 tip=1 的 slot 数」这个不变量才是结构性成立的，
 * 而不是靠每个调用点自己记得填对。
 *
 * n 超过 TOUCH_CONTACTS_MAX 时截断到 TOUCH_CONTACTS_MAX（不是错误：
 * 触摸控制器的上报上限与本常量各自演进，截断比越界写安全）。
 * n == 0 产出的是全零报告，即 host 侧「所有手指都已抬起」的那一条。
 *
 * ⚠️ 活跃触点必须**紧挨着排在最前面**、不留空洞（本函数即如此），不能按
 * contact_id 去占固定 slot。Linux hid-multitouch 的默认 class 带
 * MT_QUIRK_ALWAYS_VALID + MT_QUIRK_CONTACT_CNT_ACCURATE：它只处理前
 * contact_count 个 slot，剩下的直接不看（靠 input_mt_sync_frame 释放）。
 * 中间留空洞的话，空洞后面的真实触点会被整个丢弃。
 */
void touch_report_fill(touch_report_t *rpt, const touch_contact_t *active, uint8_t n);
