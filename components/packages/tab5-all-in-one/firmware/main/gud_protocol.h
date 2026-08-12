/* SPDX-License-Identifier: MIT */
/*
 * Copyright 2020 Noralf Trønnes
 *
 * GUD (Generic USB Display) 协议定义。
 *
 * 本文件 vendored 自 mainline Linux 内核 include/drm/gud.h（v6.8 / 与本机
 * host 内核 6.8.0-124 字节级一致）。原文件双许可 MIT/GPL，此处保留 MIT 头。
 *
 * 改动说明（仅为在 ESP-IDF / TinyUSB 下编译，语义不变）：
 *   - 内核类型 __le32/__le16/__le64/__u8 → 标准 stdint（GUD 协议要求小端，
 *     ESP32-P4 本身即小端，故直接用 uint*_t 即字节兼容）；
 *   - __packed → __attribute__((packed))；
 *   - BIT(n) → (1u << n)；
 *   - 移除 #include <linux/types.h>。
 * 所有请求码、魔数、结构体布局、像素格式、连接器类型、status 值均原样保留。
 *
 * 与姊妹包 cardputer-all-in-one 的同名文件相比，**有意**存在注释差异（除本段外
 * 还有两处：上面的 ESP32-P4，以及下面 gud_set_buffer_req 的使用说明）——
 * 本包的芯片与调用时机都不同，注释必须各自正确。
 * **这不是漏同步**，diff 时不要「修回」去。
 * 代码本体（结构体与常量）仍与 Cardputer 及内核原文逐字节一致。
 */

#ifndef __GUD_PROTOCOL_H
#define __GUD_PROTOCOL_H

#include <stdint.h>

#ifndef GUD_BIT
#define GUD_BIT(n) (1u << (n))
#endif

/*
 * struct gud_display_descriptor_req - Display descriptor (30 字节, packed)
 */
struct gud_display_descriptor_req {
	uint32_t magic;
#define GUD_DISPLAY_MAGIC			0x1d50614d
	uint8_t version;
	uint32_t flags;
#define GUD_DISPLAY_FLAG_STATUS_ON_SET		GUD_BIT(0)
#define GUD_DISPLAY_FLAG_FULL_UPDATE		GUD_BIT(1)
	uint8_t compression;
#define GUD_COMPRESSION_LZ4			GUD_BIT(0)
	uint32_t max_buffer_size;
	uint32_t min_width;
	uint32_t max_width;
	uint32_t min_height;
	uint32_t max_height;
} __attribute__((packed));

/*
 * struct gud_property_req - Property (10 字节, packed)
 */
struct gud_property_req {
	uint16_t prop;
	uint64_t val;
} __attribute__((packed));

/*
 * struct gud_display_mode_req - Display mode (24 字节, packed)
 */
struct gud_display_mode_req {
	uint32_t clock;
	uint16_t hdisplay;
	uint16_t hsync_start;
	uint16_t hsync_end;
	uint16_t htotal;
	uint16_t vdisplay;
	uint16_t vsync_start;
	uint16_t vsync_end;
	uint16_t vtotal;
	uint32_t flags;
#define GUD_DISPLAY_MODE_FLAG_PHSYNC		GUD_BIT(0)
#define GUD_DISPLAY_MODE_FLAG_NHSYNC		GUD_BIT(1)
#define GUD_DISPLAY_MODE_FLAG_PVSYNC		GUD_BIT(2)
#define GUD_DISPLAY_MODE_FLAG_NVSYNC		GUD_BIT(3)
#define GUD_DISPLAY_MODE_FLAG_INTERLACE		GUD_BIT(4)
#define GUD_DISPLAY_MODE_FLAG_DBLSCAN		GUD_BIT(5)
#define GUD_DISPLAY_MODE_FLAG_CSYNC		GUD_BIT(6)
#define GUD_DISPLAY_MODE_FLAG_PCSYNC		GUD_BIT(7)
#define GUD_DISPLAY_MODE_FLAG_NCSYNC		GUD_BIT(8)
#define GUD_DISPLAY_MODE_FLAG_HSKEW		GUD_BIT(9)
/* BCast and PixelMultiplex are deprecated */
#define GUD_DISPLAY_MODE_FLAG_DBLCLK		GUD_BIT(12)
#define GUD_DISPLAY_MODE_FLAG_CLKDIV2		GUD_BIT(13)
/* Internal protocol flags */
#define GUD_DISPLAY_MODE_FLAG_PREFERRED		GUD_BIT(10)
} __attribute__((packed));

/*
 * struct gud_connector_descriptor_req - Connector descriptor (5 字节, packed)
 */
struct gud_connector_descriptor_req {
	uint8_t connector_type;
#define GUD_CONNECTOR_TYPE_PANEL		0
#define GUD_CONNECTOR_TYPE_VGA			1
#define GUD_CONNECTOR_TYPE_COMPOSITE		2
#define GUD_CONNECTOR_TYPE_SVIDEO		3
#define GUD_CONNECTOR_TYPE_COMPONENT		4
#define GUD_CONNECTOR_TYPE_DVI			5
#define GUD_CONNECTOR_TYPE_DISPLAYPORT		6
#define GUD_CONNECTOR_TYPE_HDMI			7
	uint32_t flags;
#define GUD_CONNECTOR_FLAGS_POLL_STATUS		GUD_BIT(0)
#define GUD_CONNECTOR_FLAGS_INTERLACE		GUD_BIT(1)
#define GUD_CONNECTOR_FLAGS_DOUBLESCAN		GUD_BIT(2)
} __attribute__((packed));

/*
 * struct gud_set_buffer_req - Set buffer transfer info
 * （由 gud_device.c 的 gud_arm_set_buffer() 解析，武装一次收帧）
 */
struct gud_set_buffer_req {
	uint32_t x;
	uint32_t y;
	uint32_t width;
	uint32_t height;
	uint32_t length;
	uint8_t compression;
	uint32_t compressed_length;
} __attribute__((packed));

/*
 * struct gud_state_req - Display state (SET_STATE_CHECK/COMMIT 的 payload)
 */
struct gud_state_req {
	struct gud_display_mode_req mode;
	uint8_t format;
	uint8_t connector;
	struct gud_property_req properties[];
} __attribute__((packed));

/* List of supported connector properties: */
#define GUD_PROPERTY_TV_LEFT_MARGIN			1
#define GUD_PROPERTY_TV_RIGHT_MARGIN			2
#define GUD_PROPERTY_TV_TOP_MARGIN			3
#define GUD_PROPERTY_TV_BOTTOM_MARGIN			4
#define GUD_PROPERTY_TV_MODE				5
#define GUD_PROPERTY_TV_BRIGHTNESS			6
#define GUD_PROPERTY_TV_CONTRAST			7
#define GUD_PROPERTY_TV_FLICKER_REDUCTION		8
#define GUD_PROPERTY_TV_OVERSCAN			9
#define GUD_PROPERTY_TV_SATURATION			10
#define GUD_PROPERTY_TV_HUE				11
#define GUD_PROPERTY_BACKLIGHT_BRIGHTNESS		12

/* List of supported properties that are not connector propeties: */
#define GUD_PROPERTY_ROTATION				50
  #define GUD_ROTATION_0			GUD_BIT(0)
  #define GUD_ROTATION_90			GUD_BIT(1)
  #define GUD_ROTATION_180			GUD_BIT(2)
  #define GUD_ROTATION_270			GUD_BIT(3)
  #define GUD_ROTATION_REFLECT_X		GUD_BIT(4)
  #define GUD_ROTATION_REFLECT_Y		GUD_BIT(5)

/* USB Control requests: */

/* Get status from the last GET/SET control request. Value is u8. */
#define GUD_REQ_GET_STATUS				0x00
  /* Status values: */
  #define GUD_STATUS_OK				0x00
  #define GUD_STATUS_BUSY			0x01
  #define GUD_STATUS_REQUEST_NOT_SUPPORTED	0x02
  #define GUD_STATUS_PROTOCOL_ERROR		0x03
  #define GUD_STATUS_INVALID_PARAMETER		0x04
  #define GUD_STATUS_ERROR			0x05

/* Get display descriptor as a &gud_display_descriptor_req */
#define GUD_REQ_GET_DESCRIPTOR				0x01

/* Get supported pixel formats as a byte array of GUD_PIXEL_FORMAT_* */
#define GUD_REQ_GET_FORMATS				0x40
  #define GUD_FORMATS_MAX_NUM			32
  #define GUD_PIXEL_FORMAT_R1			0x01 /* 1-bit monochrome */
  #define GUD_PIXEL_FORMAT_R8			0x08 /* 8-bit greyscale */
  #define GUD_PIXEL_FORMAT_XRGB1111		0x20
  #define GUD_PIXEL_FORMAT_RGB332		0x30
  #define GUD_PIXEL_FORMAT_RGB565		0x40
  #define GUD_PIXEL_FORMAT_RGB888		0x50
  #define GUD_PIXEL_FORMAT_XRGB8888		0x80
  #define GUD_PIXEL_FORMAT_ARGB8888		0x81

/* Get supported global (non-connector) properties as a &gud_property_req array */
#define GUD_REQ_GET_PROPERTIES				0x41
  #define GUD_PROPERTIES_MAX_NUM		32

/* Connector requests have the connector index passed in the wValue field */

/* Get connector descriptors as an array of &gud_connector_descriptor_req */
#define GUD_REQ_GET_CONNECTORS				0x50
  #define GUD_CONNECTORS_MAX_NUM		32

/* Get properties supported by the connector as a &gud_property_req array */
#define GUD_REQ_GET_CONNECTOR_PROPERTIES		0x51
  #define GUD_CONNECTOR_PROPERTIES_MAX_NUM	32

/* TV_MODE name values (only if TV_MODE property present) */
#define GUD_REQ_GET_CONNECTOR_TV_MODE_VALUES		0x52
  #define GUD_CONNECTOR_TV_MODE_NAME_LEN	16
  #define GUD_CONNECTOR_TV_MODE_MAX_NUM		16

/* When userspace checks connector status, this is issued first */
#define GUD_REQ_SET_CONNECTOR_FORCE_DETECT		0x53

/* Get connector status. Value is u8. */
#define GUD_REQ_GET_CONNECTOR_STATUS			0x54
  #define GUD_CONNECTOR_STATUS_DISCONNECTED	0x00
  #define GUD_CONNECTOR_STATUS_CONNECTED	0x01
  #define GUD_CONNECTOR_STATUS_UNKNOWN		0x02
  #define GUD_CONNECTOR_STATUS_CONNECTED_MASK	0x03
  #define GUD_CONNECTOR_STATUS_CHANGED		GUD_BIT(7)

/* Get &gud_display_mode_req array of supported display modes */
#define GUD_REQ_GET_CONNECTOR_MODES			0x55
  #define GUD_CONNECTOR_MAX_NUM_MODES		128

/* Get Extended Display Identification Data */
#define GUD_REQ_GET_CONNECTOR_EDID			0x56
  #define GUD_CONNECTOR_MAX_EDID_LEN		2048

/* Set buffer properties before bulk transfer as &gud_set_buffer_req */
#define GUD_REQ_SET_BUFFER				0x60

/* Check display configuration as &gud_state_req */
#define GUD_REQ_SET_STATE_CHECK				0x61

/* Apply the previous STATE_CHECK configuration */
#define GUD_REQ_SET_STATE_COMMIT			0x62

/* Enable/disable the display controller, value is u8: 0/1 */
#define GUD_REQ_SET_CONTROLLER_ENABLE			0x63

/* Enable/disable display/output (DPMS), value is u8: 0/1 */
#define GUD_REQ_SET_DISPLAY_ENABLE			0x64

#endif /* __GUD_PROTOCOL_H */
