#pragma once
/*
 * UAC1 的音量刻度 ↔ esp_codec_dev 的百分比刻度 的换算。
 *
 * 纯函数、不依赖 ESP-IDF —— 与 audio_frame.c / touch_map.c 同样的理由，而且这里的
 * 理由更硬：**两套刻度的单位、符号、零点全都不一样**，换算写错在实机上的表现极具
 * 误导性 ——「音量条能拖但声音不跟着变」「拖到一半突然静音」「方向反了」，
 * 全都会被误判成 codec 或 I2C 的问题，而这块板现场没有串口可查。
 * 见 firmware/test/test_uac_volume.c。
 *
 * ── 两套刻度 ────────────────────────────────────────────────────────
 *
 * host 侧（USB Audio Class 1.0，§5.2.2.4.3.2 Volume Control）：
 *   **有符号 16 位、单位 1/256 dB**，线上小端。
 *   有效范围 0x8001(−127.9961 dB) .. 0x7FFF(+127.9961 dB)；
 *   0x8000 是**特殊值**，表示 −∞ dB（静音），不是「最小音量」。
 *   ⚠️ dB 是负数：−50 dB = −50×256 = −12800 = 0xCE00。把它当无符号读，
 *      拿到的是 52736，随后一切钳位判断都反了。
 *
 * 设备侧（esp_codec_dev 的 esp_codec_dev_set_out_vol()）：
 *   **0..100 的整数百分比**。它内部按默认音量曲线换成 dB
 *   （managed_components/espressif__esp_codec_dev/esp_codec_dev.c 的 _get_vol_db()）：
 *     vol 0 → **−96 dB**（特殊分支，不是曲线端点）
 *     vol 0..100 线性插值到 −50 dB .. 0 dB
 *   即除 vol=0 外，dB = −50 + vol × 0.5。
 *
 * ── MIN / MAX / RES 的取值理由 ──────────────────────────────────────
 *
 * MIN = −50 dB：**esp_codec_dev 默认曲线的下端点**，不是随便挑的听感值。
 *   ES8388 的 DAC 寄存器本身能到 −96 dB，但我们只能经百分比这个入口去够它 ——
 *   声明一个比曲线更宽的范围，下半段就会全部钳到 vol=0，症状正是
 *   「音量条拖到一半突然静音」。宁可诚实地只声明够得着的那一段。
 *
 * MAX = 0 dB：曲线上端点 = 满量程，不做数字增益（>0 dB 只会削顶）。
 *
 * RES = 0.5 dB：这是**真实**的步进，两侧正好对上 ——
 *   百分比刻度只有 101 档、跨 50 dB ⇒ 每档 0.5 dB；
 *   ES8388 的 DACCONTROL4/5 寄存器步进也恰是 0.5 dB。
 *   声明成 1 dB 会让 host 以为只有 51 档，白丢一半分辨率；
 *   声明成更细的值则是撒谎 —— host 送来的中间值会被静默吞掉，
 *   表现为「音量条动了但声音没变」。
 *
 * 于是本换算与 esp_codec_dev 的默认曲线**逐点重合**：q8 = −12800 + 128 × percent，
 * 即 host 看到的 dB 就是 codec 真正被设成的 dB，没有第二层隐藏映射。
 */
#include <stdint.h>

/* 全部以 1/256 dB（q8）为单位，与线上格式同刻度。 */
#define UAC_VOL_MIN_Q8 (-12800) /* −50.0 dB，esp_codec_dev 默认曲线下端点 */
#define UAC_VOL_MAX_Q8 (0)      /*   0.0 dB，满量程 */
#define UAC_VOL_RES_Q8 (128)    /*   0.5 dB，= 1 个百分点 = 1 个 ES8388 寄存器步进 */

/* UAC1 规定的「−∞ dB」特殊值。线上是 0x8000，即 int16_t 的 −32768。
 * 它**不是**最小音量，不能参与钳位比较，必须单独判。 */
#define UAC_VOL_SILENCE_Q8 (-32768)

/* 开机音量：−15 dB = 70%。满量程直推板载小喇叭在中低频容易破音，而破音很容易被
 * 误判成时钟配错。这个值同时是 host 枚举后第一次 GET_CUR 读到的值 ——
 * 与硬件实际状态一致，别让 host 一上来就看到一个假的音量。
 * 「−3840 就是 70%」由 test_uac_volume.c 钉住。 */
#define UAC_VOL_DEFAULT_Q8 (-3840)

/*
 * UAC1 音量(q8 dB) → esp_codec_dev 百分比(0..100)。
 *
 * 钳位：低于 MIN 或等于 UAC_VOL_SILENCE_Q8 → 0；高于 MAX → 100。
 * 中间值四舍五入到最近的百分点。
 *
 * ⓘ 返回 0 时 esp_codec_dev 会落到它的 −96 dB 分支而不是 −50 dB。这是**有意接受**的：
 *   音量条拖到底就该是静音，比停在「还能听见」更符合预期；而且 Mute 是另一条独立
 *   的控制，不依赖这个行为。
 */
int uac_volume_q8_to_percent(int16_t db_q8);

/*
 * esp_codec_dev 百分比(0..100) → UAC1 音量(q8 dB)。越界钳到两端。
 * 与上面互为逆：对每一个合法百分比都有 q8_to_percent(percent_to_q8(p)) == p。
 */
int16_t uac_volume_percent_to_q8(int percent);

/* 线上 2 字节小端 ↔ 有符号 q8。单独成函数是因为这正是符号最容易丢的一步：
 * `b[0] | b[1] << 8` 的结果是 int，直接存进 int16_t 之外的地方就成了正数。 */
int16_t uac_volume_decode(const uint8_t *le);
void uac_volume_encode(int16_t db_q8, uint8_t *le);
