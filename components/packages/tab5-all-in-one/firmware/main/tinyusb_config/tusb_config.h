#pragma once

/*
 * esp_tinyusb 2.2.1 的默认 tusb_config.h 把 Vendor/HID/CDC 等映射到了 Kconfig，
 * 但**没有开放 Audio 类**（它的 Kconfig 与 include/tusb_config.h 里 AUDIO 零命中）。
 * include_next 保留它的平台、FreeRTOS 与既有 class 配置，再追加本工程的 UAC1 参数。
 *
 * CMake 侧的接线见 main/CMakeLists.txt：必须**同时**把本目录塞进 tinyusb 与
 * esp_tinyusb 两个库的 include 路径最前面 —— 只改一个会让两边看到不同的
 * CFG_TUD_*，接口数与描述符长度对不上。
 *
 * ⚠️ 整段音频配置由 CONFIG_AIO_AUDIO_DESC 控制（见 main/Kconfig.projbuild），
 *    **默认关闭**。关闭时本文件退化成一层透明的 include_next，CFG_TUD_AUDIO
 *    保持 esp_tinyusb 的默认值 0，与音频落地之前的构建逐位一致。
 *    sdkconfig.h 必须在 include_next **之前**取到：IDF 给每个编译单元都加了
 *    -I build/config，所以这里能直接 include 到。
 */
#include "sdkconfig.h"

#include_next "tusb_config.h"

#if CONFIG_AIO_AUDIO_DESC

#undef CFG_TUD_AUDIO
#define CFG_TUD_AUDIO 1

/*
 * 播放（host → 设备）。SZ_MAX 必须 ≥ 描述符里声明的 wMaxPacketSize，
 * SW_BUF_SZ 必须 ≥ SZ_MAX（不满足时 audio_device.h 直接 #error）。
 * 256 字节软件缓冲 ≈ 8 个 USB 帧，足够吸收数据泵任务的调度抖动。
 */
#define CFG_TUD_AUDIO_ENABLE_EP_OUT             1
#define CFG_TUD_AUDIO_FUNC_1_EP_OUT_SZ_MAX      36
#define CFG_TUD_AUDIO_FUNC_1_EP_OUT_SW_BUF_SZ   256

/* 录音（设备 → host） */
#define CFG_TUD_AUDIO_ENABLE_EP_IN              1
#define CFG_TUD_AUDIO_FUNC_1_EP_IN_SZ_MAX       36
#define CFG_TUD_AUDIO_FUNC_1_EP_IN_SW_BUF_SZ    256

/*
 * 让 TinyUSB 按软件 FIFO 水位决定每帧发几个样本（标称 16 个，±1）。
 * 这正是「异步 IN 不需要反馈端点」的实现基础：设备时钟与 host 帧钟的漂移
 * 由包大小自己吸收，而不是靠一条额外的端点去告诉 host。
 */
#define CFG_TUD_AUDIO_EP_IN_FLOW_CONTROL        1

/*
 * ⚠️ 这两条显式写 0，不靠默认值 —— 它们各自会多要一条 IN 端点。
 * P4 全速控制器只有 4 条可用 IN，已经分给
 * vendor(0x81) / HID(0x82) / UAC 录音(0x83) / UVC 预留(0x84)。
 * 多出来的第 5 条会让 dcd_dwc2.c 的 TU_ASSERT 失败，且**无日志**。
 */
#define CFG_TUD_AUDIO_ENABLE_FEEDBACK_EP        0
#define CFG_TUD_AUDIO_ENABLE_INTERRUPT_EP       0

#endif /* CONFIG_AIO_AUDIO_DESC */
