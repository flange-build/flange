/*
 * M5Stack Tab5 电容触摸（GT911）→ USB HID digitizer（单点绝对坐标）。
 *
 * GT911 与 IO 扩展/codec/IMU 同挂**内部 I2C**（G31/G32），故直接复用
 * board_i2c_bus() 的总线句柄，不像键盘那样自建总线。
 * 触摸电源使能在 PI4IOE5V6408-1(0x43) 的 PIN5 上，board_power_init() 已拉高。
 *
 * 上报走键盘那条 HID 接口(IF1)与端点，用 Report ID 2 区分，见 usb_descriptors.c。
 */
#include "touch_hid.h"
#include "touch_map.h"
#include "tab5_pins.h"
#include "board_power.h"
#include "usb_descriptors.h"
#include "esp_lcd_touch_gt911.h"
#include "esp_lcd_panel_io.h"
#include "esp_check.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "tusb.h"

static const char *TAG = "touch";

/* 轮询周期。触摸不像键盘那样怕丢事件（坐标是状态而非边沿），20ms
 * 对指针跟随已经足够跟手，无需中断驱动。 */
#define TOUCH_POLL_MS 20

/* esp_lcd_touch 一次最多返回 CONFIG_ESP_LCD_TOUCH_MAX_POINTS 个点；
 * 本阶段只看第一个点，但缓冲要按上限开 —— esp_lcd_touch_get_data() 会
 * memset 满 max_point_cnt 个元素，传小了就是越界写。 */
#define TOUCH_POINTS_MAX CONFIG_ESP_LCD_TOUCH_MAX_POINTS

static esp_lcd_touch_handle_t s_tp;

/*
 * RID 2 的报告负载，逐位对应 usb_descriptors.c 里的 AIO_HID_REPORT_DESC_TOUCH：
 * tip 的 bit0 是 Tip Switch、高 7 位是描述符里那段常量填充；x/y 是归一化到
 * [0, TOUCH_HID_LOGICAL_MAX] 的绝对坐标。
 *
 * packed 是必需的：不加的话 uint16_t 前会插 1 字节对齐填充，报告变 6 字节、
 * 且 x/y 整体后移一字节，host 解出来的坐标全是垃圾。
 * 字节序：HID 规定小端，P4(RISC-V) 本就是小端，直接结构体发出去即可。
 */
typedef struct __attribute__((packed)) {
    uint8_t  tip;   /* bit0 = 接触中 */
    uint16_t x;
    uint16_t y;
} touch_report_t;

_Static_assert(sizeof(touch_report_t) == 5, "digitizer 报告应为 1+2+2 字节");

/* 返回是否真的发出去了。调用方据此决定要不要把它记为「已发出的状态」——
 * 记错了就再也不会重发，见 touch_task() 里的说明。 */
static bool touch_report(bool tip, uint16_t hid_x, uint16_t hid_y)
{
    const touch_report_t rpt = {
        .tip = tip ? 1 : 0,
        .x = hid_x,
        .y = hid_y,
    };

    /* 端点忙时等它腾空（最多 20ms），写法与 kbd_build_and_report() 一致，
     * 理由也一样：描述符里 bInterval=10ms，全速下 host 10ms 才来取一次，
     * tud_hid_ready() 为假时直接丢弃会静默吞掉报告。触摸这边丢掉的若正好是
     * tip=0 那条「抬起」，host 就一直认为手指还按着 —— 与键盘的卡键同源。 */
    for (int i = 0; i < 20 && !tud_hid_ready(); i++)
        vTaskDelay(pdMS_TO_TICKS(1));
    if (!tud_hid_report(HID_RID_TOUCH, &rpt, sizeof(rpt))) {
        ESP_LOGW(TAG, "touch hid report 丢弃（端点持续忙）");
        return false;
    }
    return true;
}

static void touch_task(void *arg)
{
    (void)arg;
    /* 上一次**已发出**的状态。只在它变化时才发：20ms 轮询按住不放会每帧
     * 产生一条同样的报告，而端点 bInterval=10ms、还要与键盘共用，白占带宽
     * 且会拖长键盘等端点的时间。坐标本身是状态量（不是边沿），host 记住
     * 最后一条即可，重发没有信息量。 */
    bool     last_tip = false;
    uint16_t last_x = 0, last_y = 0;

    while (1) {
        vTaskDelay(pdMS_TO_TICKS(TOUCH_POLL_MS));

        if (esp_lcd_touch_read_data(s_tp) != ESP_OK)
            continue;

        /* 用 esp_lcd_touch_get_data() 而非 esp_lcd_touch_get_coordinates()：
         * 后者在 esp_lcd_touch 1.2.x 已标 deprecated（2.0.0 移除），编译告警。 */
        esp_lcd_touch_point_data_t pts[TOUCH_POINTS_MAX];
        uint8_t points = 0;
        if (esp_lcd_touch_get_data(s_tp, pts, &points, TOUCH_POINTS_MAX) != ESP_OK)
            continue;

        const bool tip = points > 0;
        /* 抬起时坐标沿用最后一次的位置 —— digitizer 的惯例是「手指在哪儿松开的」，
         * 若归零，host 会先看到指针瞬移到左上角再抬起，表现为误点。 */
        uint16_t hid_x = last_x, hid_y = last_y;

        if (tip) {
            uint16_t gud_x = 0, gud_y = 0;
            touch_map_panel_to_gud(pts[0].x, pts[0].y, &gud_x, &gud_y);
            hid_x = touch_map_gud_to_hid(gud_x, GUD_W - 1);
            hid_y = touch_map_gud_to_hid(gud_y, GUD_H - 1);
            /* LOGD 而非 LOGI：20ms 轮询下按住不放每秒 50 条，会把串口刷没。 */
            ESP_LOGD(TAG, "raw(%u,%u) → gud(%u,%u) → hid(%u,%u) n=%u",
                     (unsigned)pts[0].x, (unsigned)pts[0].y,
                     (unsigned)gud_x, (unsigned)gud_y,
                     (unsigned)hid_x, (unsigned)hid_y, (unsigned)points);
        }

        if (tip == last_tip && hid_x == last_x && hid_y == last_y)
            continue;

        /* 只有真的发出去了才记进 last_*：否则「状态没变就不发」这条规则会把
         * 一次失败的发送永久固化 —— 尤其是丢掉 tip=0 那条抬起报告时，手指已
         * 离开屏幕、不会再产生新状态，host 就一直以为按着。发送失败保持
         * last_* 不动，下一个 20ms 轮询会自然重试。 */
        if (!touch_report(tip, hid_x, hid_y))
            continue;

        last_tip = tip;
        last_x = hid_x;
        last_y = hid_y;
    }
}

esp_err_t touch_start(void)
{
    /*
     * ⚠️ GT911 的**默认**地址是 0x5D，0x14 是备用地址 —— Tab5 用的正是 0x14。
     * ESP_LCD_TOUCH_IO_I2C_GT911_CONFIG() 宏填的是 0x5D，且组件只校验传入值
     * 合法、不会自动探测（esp_lcd_touch_gt911.c 的地址选择流程还要求有 rst
     * 引脚，Tab5 没有，那段直接被跳过）。不显式改成 BACKUP 就一定探不到。
     */
    esp_lcd_panel_io_i2c_config_t io_cfg = ESP_LCD_TOUCH_IO_I2C_GT911_CONFIG();
    io_cfg.dev_addr = ESP_LCD_TOUCH_IO_I2C_GT911_ADDRESS_BACKUP;

    esp_lcd_panel_io_handle_t io = NULL;
    ESP_RETURN_ON_ERROR(esp_lcd_new_panel_io_i2c(board_i2c_bus(), &io_cfg, &io),
                        TAG, "touch panel io");

    esp_lcd_touch_config_t tp_cfg = {
        .x_max = PANEL_W,
        .y_max = PANEL_H,
        .rst_gpio_num = GPIO_NUM_NC,        /* Tab5 触摸没有独立 reset 脚 */
        /*
         * 填了 INT 脚，GT911 驱动会对它 gpio_config(intr_type = NEGEDGE)，而 IDF 的
         * gpio_config() 顺带 gpio_intr_enable()。我们没给 interrupt_callback，所以
         * G23 是「中断使能但无 handler」——已查证无害且**不依赖 GPIO ISR service**：
         * gpio_intr_enable() 只做 HAL 寄存器写，不碰 gpio_isr_func/isr_handle；
         * 没装 ISR service 时 CPU 中断压根没分配，状态位只是空闲锁存，无人读取。
         * 这条要紧：kbd_start() 失败（没插键盘）时 ISR service 不会被装上，
         * 触摸**不能**因此跟着起不来。将来改中断驱动时把 interrupt_callback 填上即可。
         */
        .int_gpio_num = PIN_TOUCH_INT,
        .levels = {
            .reset = 0,
            .interrupt = 0,
        },
        /*
         * 三个方向 flag 全 0 —— **不是待标定的占位值，是官方 BSP 的取值**。
         * esp-bsp `bsp/m5stack_tab5/src/bsp_display.c` 的 tp_cfg 逐项相同：
         * x_max/y_max = 720/1280、rst = NC、levels.interrupt = 0、三个 flag 全 false。
         * 即 GT911 就是按面板原生 720×1280 竖向出数，touch_map.c 的反变换直接可用。
         *
         * 官方在使能触摸电源后等 500ms 再探测，我们 board_power_init() 只等 50ms；
         * 但本函数排在 display_init()(195 条面板 init 命令) 与 kbd_start() 之后，
         * 距 TOUCH_EN 拉高早已远超 500ms，这个差异在本调用顺序下不成立。
         */
        .flags = {
            .swap_xy = 0,
            .mirror_x = 0,
            .mirror_y = 0,
        },
    };
    /*
     * 探不到就把 panel io 拆掉再返回。GT911 驱动自己的 err 分支只清它那一份
     * （含 gpio_reset_pin(INT)、且失败时不会写 s_tp），**不碰我们传进去的 io**；
     * 而 touch_start() 失败现在不再 abort（见 app_main），这个 io 会一直挂在
     * 内部 I2C 总线的设备链上没人回收。
     */
    esp_err_t err = esp_lcd_touch_new_i2c_gt911(io, &tp_cfg, &s_tp);
    if (err != ESP_OK) {
        esp_lcd_panel_io_del(io);
        ESP_LOGE(TAG, "gt911 未应答(0x%02x)：%s，检查内部 I2C 与触摸电源",
                 ESP_LCD_TOUCH_IO_I2C_GT911_ADDRESS_BACKUP, esp_err_to_name(err));
        return err;
    }

    ESP_LOGI(TAG, "gt911 ready (addr=0x%02x, int=G%d)",
             ESP_LCD_TOUCH_IO_I2C_GT911_ADDRESS_BACKUP, PIN_TOUCH_INT);

    xTaskCreate(touch_task, "touch", 4096, NULL, 5, NULL);
    return ESP_OK;
}
