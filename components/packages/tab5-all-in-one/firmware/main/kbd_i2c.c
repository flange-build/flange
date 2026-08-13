/*
 * M5Stack Tab5 Keyboard（I2C 从机 0x6D）→ USB HID 键盘。
 *
 * 键盘挂在与内部 I2C（G31/G32）物理分离的另一条总线（G0/G1）上，故本文件
 * 自己持有一条 i2c_master_bus，不复用 board_power 的那条。
 *
 * 用固件的 Normal 模式（寄存器 0x10 写 0）读行列事件，自建按下集合状态机；
 * 不用键盘自带的 HID 模式 —— 它的修饰键不进队列、且一次只能表达一个键。
 */
#include "kbd_i2c.h"
#include "tab5_pins.h"
#include "tab5_kbd_map.h"
#include "driver/i2c_master.h"
#include "driver/gpio.h"
#include "esp_check.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static const char *TAG = "kbd";

/* 寄存器地址取自官方固件 user_i2c_reg.h。注意 0xFE/0xFF 是绝对地址——
 * 协议图最后一行标的 0xF0 是块基址，Version/Address 在该行 E/F 列。
 * 0xFD 是固件升级入口，误写会变砖，本文件永不触碰。 */
#define REG_INTR_CONFIG    0x00
#define REG_INTR_STATUS    0x01
#define REG_EVENT_NUM      0x02
#define REG_KEYBOARD_MODE  0x10
#define REG_KEY_EVENT      0x20
#define REG_FW_VERSION     0xFE

#define KBD_MODE_NORMAL    0

/* Normal 模式事件：bit7 按下(1)/释放(0)，bit[6:4] 行，bit[3:0] 列；队列空读回 0xFF */
#define KEY_EVENT_EMPTY    0xFF

#define KBD_ROWS 5
#define KBD_COLS 14

/* 当前按下的键（行列位图）。Normal 模式给的是按下/释放边沿事件，
 * 而 HID 报告要的是「此刻按着哪些键」的全量快照，所以必须自己维护集合。 */
static bool s_pressed[KBD_ROWS][KBD_COLS];

/* 四个功能键的位置，取自官方固件 updatemodifier_mask() */
#define IS_SYM(r, c)   ((r) == 3 && (c) == 0)
#define IS_AA(r, c)    ((r) == 3 && (c) == 1)

static i2c_master_bus_handle_t s_bus;
static i2c_master_dev_handle_t s_dev;
static TaskHandle_t s_kbd_task;

/* INT 低有效：键盘固件拉低表示队列非空。用下降沿唤醒读取任务，
 * ISR 里只做任务通知，I2C 读取放任务上下文（I2C 不能在 ISR 里做）。 */
static void IRAM_ATTR kbd_int_isr(void *arg)
{
    (void)arg;
    BaseType_t hp = pdFALSE;
    vTaskNotifyGiveFromISR(s_kbd_task, &hp);
    portYIELD_FROM_ISR(hp);
}

static esp_err_t kbd_read_reg(uint8_t reg, uint8_t *out, size_t len)
{
    return i2c_master_transmit_receive(s_dev, &reg, 1, out, len, 100);
}

static esp_err_t kbd_write_reg(uint8_t reg, uint8_t val)
{
    const uint8_t buf[2] = { reg, val };
    return i2c_master_transmit(s_dev, buf, sizeof(buf), 100);
}

/*
 * 把当前按下集合翻译成标准 HID 键盘报告（modifier + 最多 6 个 keycode）。
 *
 * 分层规则（与官方固件 convert_to_hid() 语义一致）：
 *   - Sym(3,0) / Aa(3,1)：**本地层键，不上报**。官方表里它们的 firstKeyCode 是
 *     KEY_LEFTSHIFT，但物理键盘上标「!」的键其基础层本身就是 Shift+1 ——
 *     Sym 不是 Shift，而是切到第二层。当 Shift 上报会让符号全错。
 *   - Ctrl(4,0) / Alt(4,1)：查表得到的 usage 落在 0xE0~0xE7（HID 修饰键区间），
 *     由下面的通用规则自动归入 modifier 字节，不占 keycode 槽。
 *   - 字母键：Aa 生效 → 用 second 层（大写）。
 *   - 其余键：Sym 按住且 key_modifier_flag 置位 → 用 second 层。
 */
static void kbd_build_and_report(void)
{
    bool sym = s_pressed[3][0];
    bool aa  = s_pressed[3][1];

    uint8_t modifier = 0;
    uint8_t keys[6] = {0};
    int nk = 0;

    for (int r = 0; r < KBD_ROWS; r++) {
        for (int c = 0; c < KBD_COLS; c++) {
            if (!s_pressed[r][c]) continue;
            if (IS_SYM(r, c) || IS_AA(r, c)) continue;   /* 本地层键，不上报 */

            const key_value_t *k = &key_value_map[r][c];
            bool is_letter = (k->firstKeyCode >= KEY_A && k->firstKeyCode <= KEY_Z);
            bool use_second = is_letter ? aa : (sym && key_modifier_flag[r][c]);

            uint8_t mod, code;
            if (use_second) {
                mod  = k->secondModifierMask;
                code = k->secondKeyCode;
            } else if (is_letter) {
                /* ⚠️ 不能取表里的 firstModifierMask：上游把底排 z/x/c/v/b/n/m 的
                 * firstModifierMask 写成了 KEY_MOD_LSHIFT。官方 convert_to_hid()
                 * 的小写分支根本不读这个字段（只用运行时 modifier_mask），从而
                 * 绕开了它；照抄字段会让这一整排打出大写。这里照同样语义处理。 */
                mod  = 0;
                code = k->firstKeyCode;
            } else {
                mod  = k->firstModifierMask;
                code = k->firstKeyCode;
            }

            modifier |= mod;
            /* 0xE0~0xE7 是 HID 修饰键 usage：转成 modifier 位，不占 keycode 槽 */
            if (code >= KEY_LEFTCTRL && code <= KEY_RIGHTMETA) {
                modifier |= (uint8_t)(1u << (code - KEY_LEFTCTRL));
            } else if (code != KEY_NONE && nk < 6) {
                keys[nk++] = code;
            }
        }
    }

    ESP_LOGI(TAG, "report mod=0x%02x keys=%02x %02x %02x %02x %02x %02x",
             modifier, keys[0], keys[1], keys[2], keys[3], keys[4], keys[5]);
    /* Task 4 在此接 tud_hid_keyboard_report() */
}

static void kbd_task(void *arg)
{
    (void)arg;
    while (1) {
        /* 等 INT。保留 100ms 超时兜底：INT 是**电平语义**（队列非空即低），
         * 若我们在它已经拉低之后才配置下降沿中断，就永远等不到边沿。
         * 超时轮询让这种竞态自愈。代价是空闲时每秒 10 次一字节 I2C 读，可忽略。 */
        ulTaskNotifyTake(pdTRUE, pdMS_TO_TICKS(100));

        /* 一次排空队列：EVENT_NUM 给出当前事件数，逐个读走后 INT 自然释放。 */
        uint8_t n = 0;
        if (kbd_read_reg(REG_EVENT_NUM, &n, 1) != ESP_OK)
            continue;
        for (uint8_t i = 0; i < n; i++) {
            uint8_t ev = KEY_EVENT_EMPTY;
            if (kbd_read_reg(REG_KEY_EVENT, &ev, 1) != ESP_OK || ev == KEY_EVENT_EMPTY)
                break;
            const bool pressed = (ev & 0x80) != 0;
            const uint8_t row = (ev >> 4) & 0x07;
            const uint8_t col = ev & 0x0F;
            ESP_LOGI(TAG, "raw %s row=%u col=%u", pressed ? "press" : "release",
                     (unsigned)row, (unsigned)col);

            /* 越界防御：行列来自从机，若固件/线路异常给出非法值，别越界写内存 */
            if (row >= KBD_ROWS || col >= KBD_COLS)
                continue;
            s_pressed[row][col] = pressed;
            kbd_build_and_report();
        }
    }
}

esp_err_t kbd_start(void)
{
    i2c_master_bus_config_t bus_cfg = {
        .i2c_port = I2C_NUM_1,          /* I2C_NUM_0 已被 board_power 的内部总线占用 */
        .sda_io_num = PIN_KBD_SDA,
        .scl_io_num = PIN_KBD_SCL,
        .clk_source = I2C_CLK_SRC_DEFAULT,
        .glitch_ignore_cnt = 7,
        .flags.enable_internal_pullup = true,
    };
    ESP_RETURN_ON_ERROR(i2c_new_master_bus(&bus_cfg, &s_bus), TAG, "kbd i2c bus");

    ESP_RETURN_ON_ERROR(i2c_master_probe(s_bus, KBD_I2C_ADDR, 100), TAG,
                        "键盘未应答(0x%02x)，检查排线与 G0/G1", KBD_I2C_ADDR);

    i2c_device_config_t dev_cfg = {
        .dev_addr_length = I2C_ADDR_BIT_LEN_7,
        .device_address = KBD_I2C_ADDR,
        .scl_speed_hz = 100000,
    };
    ESP_RETURN_ON_ERROR(i2c_master_bus_add_device(s_bus, &dev_cfg, &s_dev), TAG, "kbd i2c dev");

    uint8_t fw = 0;
    ESP_RETURN_ON_ERROR(kbd_read_reg(REG_FW_VERSION, &fw, 1), TAG, "读固件版本失败");
    ESP_RETURN_ON_ERROR(kbd_write_reg(REG_KEYBOARD_MODE, KBD_MODE_NORMAL), TAG, "设 Normal 模式失败");

    ESP_LOGI(TAG, "fw=0x%02x addr=0x%02x mode=normal", fw, KBD_I2C_ADDR);

    /* 中断配置必须在建任务**之后** —— ISR 要用到 s_kbd_task 句柄。 */
    xTaskCreate(kbd_task, "kbd", 4096, NULL, 5, &s_kbd_task);

    gpio_config_t int_cfg = {
        .mode = GPIO_MODE_INPUT,
        .pin_bit_mask = 1ULL << PIN_KBD_INT,
        .pull_up_en = GPIO_PULLUP_ENABLE,   /* INT 低有效，常态由上拉保持高 */
        .intr_type = GPIO_INTR_NEGEDGE,
    };
    ESP_RETURN_ON_ERROR(gpio_config(&int_cfg), TAG, "kbd int gpio");
    ESP_RETURN_ON_ERROR(gpio_install_isr_service(0), TAG, "isr service");
    ESP_RETURN_ON_ERROR(gpio_isr_handler_add(PIN_KBD_INT, kbd_int_isr, NULL), TAG, "isr add");
    return ESP_OK;
}
