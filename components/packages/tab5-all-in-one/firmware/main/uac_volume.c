#include "uac_volume.h"

int uac_volume_q8_to_percent(int16_t db_q8)
{
    /* ⚠️ 必须排在钳位之前：0x8000 = −32768 数值上确实小于 MIN，两条分支这里
     * 恰好都返回 0，但语义完全不同（「−∞」vs「比最小还小」）。写在前面是为了
     * 让日后有人改 MIN 时不会连带把这条特殊值悄悄改错。 */
    if (db_q8 == UAC_VOL_SILENCE_Q8)
        return 0;

    if (db_q8 <= UAC_VOL_MIN_Q8)
        return 0;
    if (db_q8 >= UAC_VOL_MAX_Q8)
        return 100;

    /* db_q8 − MIN 恒为正（上面已排除 ≤MIN），所以这里的整除不会碰到 C 的
     * 「向零取整」与算术右移分叉的那个坑；加半个 RES 即四舍五入到最近百分点。 */
    return ((int)db_q8 - UAC_VOL_MIN_Q8 + UAC_VOL_RES_Q8 / 2) / UAC_VOL_RES_Q8;
}

int16_t uac_volume_percent_to_q8(int percent)
{
    if (percent <= 0)
        return (int16_t)UAC_VOL_MIN_Q8;
    if (percent >= 100)
        return (int16_t)UAC_VOL_MAX_Q8;
    return (int16_t)(UAC_VOL_MIN_Q8 + percent * UAC_VOL_RES_Q8);
}

int16_t uac_volume_decode(const uint8_t *le)
{
    /* 先拼成 uint16_t 再整体转 int16_t：直接在 int 上拼再截断，中间那步是正数，
     * 一旦有人顺手把中间量存成 int 或 unsigned 就静默丢符号。 */
    const uint16_t raw = (uint16_t)((uint16_t)le[0] | ((uint16_t)le[1] << 8));

    return (int16_t)raw;
}

void uac_volume_encode(int16_t db_q8, uint8_t *le)
{
    const uint16_t raw = (uint16_t)db_q8;

    le[0] = (uint8_t)(raw & 0xff);
    le[1] = (uint8_t)(raw >> 8);
}
