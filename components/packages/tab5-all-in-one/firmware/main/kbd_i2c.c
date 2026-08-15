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
#include "kbd_translate.h"
#include "usb_descriptors.h"
#include "driver/i2c_master.h"
#include "driver/gpio.h"
#include "esp_check.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "tusb.h"
#include <inttypes.h>
#include <stdio.h>

static const char *TAG = "kbd";

/* 寄存器地址取自官方固件 user_i2c_reg.h。注意 0xFE/0xFF 是绝对地址——
 * 协议图最后一行标的 0xF0 是块基址，Version/Address 在该行 E/F 列。
 * 0xFD 是固件升级入口，误写会变砖，本文件永不触碰。 */
/* INTR_CONFIG / INTR_STATUS 当前不用，但**有意保留**：键盘上电默认
 * INT_CFG = 0x07（三种模式的中断全开）已满足需求，而排空 EVENT_NUM 队列
 * 本身就会让从机释放 INT，故既不需要显式配置也不需要显式清中断。
 * 留着是因为它们是这张寄存器表的一部分，删了下次要用还得重查手册。 */
#define REG_INTR_CONFIG    0x00
#define REG_INTR_STATUS    0x01
#define REG_EVENT_NUM      0x02
#define REG_KEYBOARD_MODE  0x10
#define REG_KEY_EVENT      0x20
#define REG_FW_VERSION     0xFE

#define KBD_MODE_NORMAL    0

/* Normal 模式事件：bit7 按下(1)/释放(0)，bit[6:4] 行，bit[3:0] 列；队列空读回 0xFF */
#define KEY_EVENT_EMPTY    0xFF

/* 当前按下的键（行列位图）。Normal 模式给的是按下/释放边沿事件，
 * 而 HID 报告要的是「此刻按着哪些键」的全量快照，所以必须自己维护集合。 */
static bool s_pressed[KBD_ROWS][KBD_COLS];

static i2c_master_bus_handle_t s_bus;
static i2c_master_dev_handle_t s_dev;
static TaskHandle_t s_kbd_task;

/* 连续 I2C 读失败节流计数：排线松了/键盘掉电时不能每次失败都刷屏
 * （100ms 轮询下会很快连成一片），但也不能完全静默——那样实机排障
 * 无从下手。每连续失败 10 次告警一次，读成功即清零。 */
static uint32_t s_i2c_fail_count;

/* 上一条 HID 报告没发出去（端点持续忙），待重发。见 kbd_task() 末尾的重试。 */
static bool s_report_pending;

static void kbd_note_i2c_result(esp_err_t err)
{
    if (err == ESP_OK) {
        s_i2c_fail_count = 0;
        return;
    }
    if (++s_i2c_fail_count % 10 == 0)
        ESP_LOGW(TAG, "键盘 I2C 连续读失败 %" PRIu32 " 次，检查排线与 G0/G1(0x%02x)",
                 s_i2c_fail_count, KBD_I2C_ADDR);
}

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

/* 把当前按下集合翻译成 HID 报告并发给 host，返回是否真的发出去了。
 * 分层逻辑（Sym/Aa/Ctrl/Alt）在 kbd_translate.c，拆出来是为了能在宿主机测试，
 * 这里只管发送。 */
static bool kbd_build_and_report(void)
{
    uint8_t modifier = 0;
    uint8_t keys[KBD_KEYS_MAX] = {0};
    int nk = kbd_translate(s_pressed, &modifier, keys);

    char keys_str[KBD_KEYS_MAX * 3 + 1] = {0};
    for (int i = 0; i < KBD_KEYS_MAX; i++)
        snprintf(keys_str + i * 3, 4, "%02x ", keys[i]);
    ESP_LOGD(TAG, "report mod=0x%02x keys=%s", modifier, keys_str);

    /* 端点忙时等它腾空（最多 20ms）：描述符里 bInterval=10ms，全速下 host
     * 10ms 才来取一次数据，同一批次排空里连调 tud_hid_keyboard_report()
     * 否则只有第一条发得出去，之后的全被静默丢弃——若丢的正好是「释放」
     * 那条，host 就认为键还按着，终端里表现成卡键/自动重复，且现象极像
     * 硬件故障。不能改成「一批只发最终状态」来规避：若批次里同时有
     * press-A 和 release-A，合并后这次按键会整个消失，必须逐条发。 */
    for (int i = 0; i < 20 && !tud_hid_ready(); i++)
        vTaskDelay(pdMS_TO_TICKS(1));
    if (!tud_hid_keyboard_report(HID_RID_KEYBOARD, modifier, nk ? keys : NULL)) {
        ESP_LOGW(TAG, "hid report 发送失败（端点持续忙），待重发");
        return false;
    }
    return true;
}

static void kbd_task(void *arg)
{
    (void)arg;
    while (1) {
        /* 等 INT。保留 100ms 超时兜底：INT 是**电平语义**（队列非空即低），
         * 若我们在它已经拉低之后才配置下降沿中断，就永远等不到边沿。
         * 超时轮询让这种竞态自愈。代价是空闲时每秒 10 次一字节 I2C 读，可忽略。 */
        ulTaskNotifyTake(pdTRUE, pdMS_TO_TICKS(100));

        /* 排空队列，读完立刻复查 EVENT_NUM：INT 是电平语义（队列非空即低），
         * 若排空期间新事件又到了，NEGEDGE 不会再触发，只读一轮会让它一直
         * 等到下次 100ms 超时才被处理（手感上是偶尔一个字母慢半拍）。
         * 这个 do-while 同时收窄 kbd_build_and_report() 里 HID 端点忙丢
         * 报告的触发窗口——批次越小，两条报告间隔越接近事件本身的节奏。 */
        uint8_t n;
        do {
            esp_err_t err = kbd_read_reg(REG_EVENT_NUM, &n, 1);
            kbd_note_i2c_result(err);
            if (err != ESP_OK)
                break;
            for (uint8_t i = 0; i < n; i++) {
                uint8_t ev = KEY_EVENT_EMPTY;
                err = kbd_read_reg(REG_KEY_EVENT, &ev, 1);
                kbd_note_i2c_result(err);
                if (err != ESP_OK || ev == KEY_EVENT_EMPTY)
                    break;
                const bool pressed = (ev & 0x80) != 0;
                const uint8_t row = (ev >> 4) & 0x07;
                const uint8_t col = ev & 0x0F;
                ESP_LOGD(TAG, "raw %s row=%u col=%u", pressed ? "press" : "release",
                         (unsigned)row, (unsigned)col);

                /* 越界防御：行列来自从机，若固件/线路异常给出非法值，别越界写内存 */
                if (row >= KBD_ROWS || col >= KBD_COLS)
                    continue;
                s_pressed[row][col] = pressed;
                s_report_pending = !kbd_build_and_report();
            }
        } while (n > 0);

        /*
         * 排空后补发一次上面没发出去的报告。
         *
         * 为什么必须补：等满 20ms 端点仍忙时报告就丢了，若丢的正好是「全部
         * 松开」那条，而此后用户不再按键（不会再产生事件、也就不会再有任何
         * 发送），host 会一直认为键按着 —— 终端里表现成字符自动重复。这与
         * 触摸丢掉 tip=0 抬起报告是同一个洞（见 touch_hid.c）。
         *
         * 为什么重发是安全的：报告是 s_pressed 的**纯函数**（kbd_translate()
         * 每次都从按下集合重算「此刻按着哪些键」的完整快照），重发只是把当前
         * 真相再声明一遍，不会凭空造出或抹掉一次按键。上面那条「不能一批只发
         * 最终状态」的禁忌针对的是**批内合并**（press-A 与 release-A 合并后
         * 这次按键整个消失），与失败后重试是两回事，不冲突。
         *
         * 放在排空之后是关键：此刻 s_pressed 已吸收完本轮全部事件，补发的就是
         * 最新真相。任务本身有 100ms 超时兜底会醒，所以即使之后再无按键也会重试，
         * 不需要额外的重试计数或定时器。
         */
        if (s_report_pending)
            s_report_pending = !kbd_build_and_report();
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

    /* 探测失败是**受支持的正常配置**（Tab5 Keyboard 是可拆配件，不插就该降级启动），
     * 所以这条路径必须把总线还回去 —— 否则每次不插键盘开机都白占住 I2C_NUM_1 与 G0/G1。
     * 此刻还没 add_device，设备链为空，i2c_del_master_bus() 可直接成功，
     * 不需要 goto 清理链。 */
    if (i2c_master_probe(s_bus, KBD_I2C_ADDR, 100) != ESP_OK) {
        i2c_del_master_bus(s_bus);
        s_bus = NULL;
        ESP_LOGW(TAG, "键盘未应答(0x%02x)；未插键盘底座时属正常", KBD_I2C_ADDR);
        return ESP_ERR_NOT_FOUND;
    }

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

    /* 开机时队列可能已非空（INT 已被拉低）：若不清，这批陈旧事件会在装好
     * 中断后随第一次排空灌进 s_pressed，残留一个「开机前就按下」的键状态，
     * 直到用户再按一次同一物理键才会翻转掉。REG_EVENT_NUM 写 0 即清空队列
     * 并释放 INT（寄存器表语义），必须放在装 GPIO 中断之前做，让「INT 已
     * 拉低」这个初始态直接不成立。 */
    ESP_RETURN_ON_ERROR(kbd_write_reg(REG_EVENT_NUM, 0), TAG, "清空开机残留队列失败");

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
