#pragma once
/*
 * SC202CS 摄像头传感器。**本阶段（P4 Task7）只做 SCCB 探测，不取流、不出图。**
 * MIPI-CSI 控制器、ISP、以及把画面接到 UVC 上，是后续任务的事。
 *
 * 分层与音频、面板、触摸完全同构：
 *   寄存器序列   → 托管组件 espressif/esp_cam_sensor（**芯片驱动**组件，
 *                  依赖只有 cmake_utilities + esp_sccb_intf，两者都零外部依赖）
 *   板级接线     → 本文件（电源在 IO 扩展 0x43 的 PIN6，SCCB 复用内部 I2C）
 * **刻意不引 espressif/esp_video**：它强制拖 usb_host_uvc + esp_h264 + esp_ipa，
 * 在一块「TinyUSB device 独占唯一一条 FSLS PHY」的板子上引入 USB Host 栈毫无道理。
 * 完整依据见 main/idf_component.yml 里 esp_cam_sensor 那一段。
 *
 * ⓘ 文件名叫 camera_csi 而不是 camera_sccb：Task 8 起 CSI 取流也落在这里，
 *   现在换名字只会让后面的 diff 变脏。
 */
#include "esp_err.h"

/*
 * 给摄像头上电，在共用的内部 I2C 总线上建一个 SCCB io，读 PID，再交给
 * esp_cam_sensor 的 sc202cs_detect()。
 *
 * 失败时**自己把摄像头电源关掉**并返回错误，调用方只需降级：本阶段 UVC 仍用
 * 片上合成图案帧源，显示/键盘/触摸/音频四项能力一概不受影响。
 * 与 kbd_start() / touch_start() / codec_audio_init() 同一处置原则。
 *
 * 不幂等：重复调用会重复上电与重复建 SCCB io。开机只调一次。
 */
esp_err_t camera_sensor_probe(void);

/*
 * 自检快照打一遍。与 codec_audio_report() 同构，存在的理由也一样：探测跑在 CDC
 * 日志串口真正出字节之前，现场看不到它的 ESP_LOG*，所以结论要能被复读。
 *
 * 它把四种失败**明确区分开**（判读表写在 camera_csi.c 的函数注释里）：
 *   SCCB io 没建起来 / 0x36 不应答(NAK) / 应答但 PID 不是 0xeb52 / 组件内部失败。
 */
void camera_sensor_report(void);
