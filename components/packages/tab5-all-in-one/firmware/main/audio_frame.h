#pragma once
/*
 * USB 单声道帧 ↔ I2S 线上立体声帧 的转换。
 *
 * 纯函数、不依赖 ESP-IDF —— 与 kbd_translate.c / touch_map.c 同样的理由：
 * 这几行完全可以在宿主机上验证，而写错了在实机上只表现为「声音小一半 /
 * 只有一边有声 / 音高快一倍」，从现象几乎反推不出是哪一步算错。
 * 见 firmware/test/test_audio_frame.c。
 */
#include <stdint.h>
#include <stddef.h>

/*
 * 单声道 → 交错立体声：左右两路填同一个样本。
 * frames = 样本帧数；mono 有 frames 个元素，stereo 有 2*frames 个元素。
 * 两个缓冲不得重叠。
 *
 * 为什么不用 I2S 的 I2S_SLOT_MODE_MONO 代替：全双工要求 TX 与 RX 的 slot 配置
 * 完全一致（驱动对两份 i2s_std_config_t 做 memcmp），而录音侧必须是双声道
 * （两只麦，MONO 会把 slot_mask 设成只剩左声道，MIC2 就白装了）——
 * 线上只能统一成立体声 2 slot，单↔双的转换放到这里。
 */
void audio_frame_mono_to_stereo(const int16_t *mono, int16_t *stereo, size_t frames);

/*
 * 交错立体声 → 单声道：两路取算术平均。
 * 用 (l + r) >> 1（int32 上的算术右移）而不是 /2：
 *   - int32 中间量不会溢出（两个 int16 之和最多 ±65536）；
 *   - 右移对负数向下取整、除法向零取整，两者对半波会产生不同的直流偏置。
 *     选定右移并在测试里钉死，免得日后有人「顺手改成 /2」—— 听不出差别，
 *     但行为变了。
 */
void audio_frame_stereo_to_mono(const int16_t *stereo, int16_t *mono, size_t frames);
