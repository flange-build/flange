#pragma once
/*
 * 官方 ISP 图像处理算法（espressif/esp_ipa）的**消费侧**。
 *
 * ══ 这个文件存在的理由 ══════════════════════════════════════════════
 *
 * 画质算法（AE / AWB / CCM / gamma / 降噪 / 锐化 / LSC / 饱和度…）**全部由官方
 * esp_ipa 决定，本工程一行控制律都不写**。此前那一整套自研实现（AE 比例控制器、
 * AWB 灰世界 + 四道防护、CCT 估计、CCM 插值与强度钳制、gamma 选档、env.luma
 * 重建…）已**整体删除** —— 它们是基于「引 esp_ipa 会把 esp_video + usb_host_uvc
 * + esp_h264 拖进来」这个**错误判断**写出来的。依赖方向实测是反的：
 *   esp_video → esp_ipa（esp_video 的 manifest 里确实有 usb_host_uvc/esp_h264）
 *   esp_ipa   → 只有 cmake_utilities + idf>=5.4，**再无其他**
 * 也就是说 esp_ipa 完全可以单独引，而这正是「与官方 1:1」唯一可能的形式。
 *
 * ⚠️ **为什么必须 1:1 而不能自己写：官方标定数据与官方算法是一对，不可拆。**
 *   sc202cs_default.json 里那 19 档 CCM、9 档 LSC、4 档 gamma/锐化/BF、25 个 AE
 *   权重，全都是**按 esp_ipa 这套算法的行为**在实验室标出来的。把这些数喂给
 *   另一套控制律，得到的不是「近似官方」，而是一个谁也没验证过的第三种东西。
 *
 * ══ 数据流 ═════════════════════════════════════════════════════════
 *
 *   ISP 硬件统计（AE 5×5 / AWB 白点 / 直方图，都在 camera_csi.c 里建）
 *        │  camera_csi.c 填成 esp_ipa_stats_t
 *        ▼
 *   esp_ipa_pipeline_process()          ← 闭源 blob，官方算法本体
 *        │  输出 esp_ipa_metadata_t（flags 位表示哪些字段有效）
 *        ▼
 *   本文件按 IPA_METADATA_FLAGS_* 逐位分发：
 *        ISP 侧   → CCM / gamma / BF / demosaic / sharpen / color / LSC / AWB 统计框
 *        传感器侧 → 曝光 + 增益（ET 与 GN 同时置位时**一次性下发**）
 *
 * 消费侧的逻辑逐条照抄 esp_video/src/esp_video_isp_pipeline.c（开源，约 1500 行）——
 * 那是官方自己的消费侧实现，是「怎么用这个 blob」的唯一权威。**但不引 esp_video
 * 组件本身**：它会拖进 USB Host 栈，而本板 TinyUSB device 独占唯一一条 FSLS PHY。
 *
 * ══ rev v1.0 拿不到的那几位 ═════════════════════════════════════════
 *
 * 本板 P4 是 **rev v1.0**，ISP 的 BLC / WBG / crop 三个子块在硬件上就不存在
 * （驱动的版本门 ESP_CHIP_REV_ABOVE(rev,300)）。而官方标定文件里**带着
 * acc.blc**，于是 blob 会稳定地在 metadata 里置起 IPA_METADATA_FLAGS_BLC。
 * 处置方式与 esp_video 完全一致 —— 它用 `#if ESP_VIDEO_ISP_DEVICE_BLC` 把整段
 * 写硬件的代码编译掉，我们用 CAM_IPA_HAS_BLC（见 cam_ipa.c）做同一件事。
 * **这不是错误路径**：blob 照常算、照常给，只是这一位没人消费，见 cam_ipa.c
 * 里 CAM_IPA_HAS_BLC 那一段的完整推理与实测判读。
 */
#include "esp_cam_sensor.h"
#include "esp_err.h"
#include "esp_ipa.h"
#include "driver/isp.h"
#include <stdbool.h>
#include <stdint.h>

/*
 * 建 IPA pipeline 并跑一次 esp_ipa_pipeline_init()，把它给出的初值写进 ISP 与传感器。
 *
 * isp / sensor 两个句柄由 camera_csi.c 持有并传进来 —— 本文件不建任何硬件对象，
 * 只往已经建好的对象上写参数。这条边界让「谁拥有硬件」这件事只有一个答案。
 *
 * 须在 esp_cam_sensor_set_format() **之后**调用：曝光上下限、增益表、默认值都是
 * 传感器驱动在 set_format 里才填好的（sc202cs.c 的 exposure_max/gain_def），
 * 早调拿到的是上电默认态的值。
 *
 * 失败**只降级不拦启动**（与本工程其余画质级同一处置）：返回非 ESP_OK 时
 * 画面停在 ISP 的基础配置上（见 cam_ipa_report() 的判读表），取流本身不受影响。
 *
 * 幂等：重复调用直接返回 ESP_OK。
 */
esp_err_t cam_ipa_init(isp_proc_handle_t isp, esp_cam_sensor_device_t *sensor);

/*
 * 送一份统计进 pipeline 走一拍，并把算出来的 metadata 分发到 ISP 与传感器。
 *
 * **每拿到一份统计就调一次，调用方不要自己再加分频** —— 官方算法内部自带
 * 帧延迟（agc.exposure.frame_delay = 3）、最小步长（gain.min_step = 0.03）
 * 与迟滞（gamma.luma_min_step = 3.0），外面再叠一层分频只会让这些数失去意义。
 *
 * stats 为 NULL、pipeline 没建起来、或没在取流时直接返回（不做任何事）。
 */
void cam_ipa_process(const esp_ipa_stats_t *stats);

/*
 * 自检快照。与 camera_sensor_report() / camera_csi_report() 同构，理由也一样：
 * 这块板现场没有开箱即用的串口，开机那几行日志在 CDC 档下会被冲掉，结论必须
 * 能被复读。判读表写在 cam_ipa.c 的函数注释里。
 */
void cam_ipa_report(void);

/*
 * 此刻传感器的总增益（×1000 定点）。camera_csi.c 的自检行要打它。
 * IPA 没起来时返回 1000（= 1.000×，模式表的默认增益）。
 */
uint32_t cam_ipa_gain_milli(void);
