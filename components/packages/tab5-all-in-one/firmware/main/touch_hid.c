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
#include "display_dsi.h"
#include "esp_lcd_touch_gt911.h"
#include "esp_lcd_panel_io.h"
#include "driver/gpio.h"
#include "esp_check.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "tusb.h"

static const char *TAG = "touch";

/*
 * ⚠️ 临时诊断设施 —— 定位完问题请改回 0 或整段删除。
 *
 * 为什么需要它：本机的 USB-Serial/JTAG 已被关掉（TinyUSB 要占那条 FSLS PHY，
 * 见 app_main.c 的 route_fsls_phy0_to_otg），UART0 只在 M5-Bus 排针上、需另接
 * USB-TTL。也就是说**现场没有任何串口**，本文件里所有 ESP_LOG* 都看不到。
 *
 * 而「触摸不工作」有两种成因，光看 host 侧分不开：
 *   A. 固件根本没读到坐标（GT911 起不来，或一直返回 0 个点）
 *   B. 读到了，但 HID 报告没送出去 / host 解析不对
 * 于是把固件内部状态直接画到面板上，用户一眼可辨。
 *
 * 屏幕左上角有**两个** 16×16 方块，左起：
 *
 * ① x=0：初始化 + 心跳
 *   绿/暗绿**闪烁**   GT911 初始化通过，touch_task 在跑
 *   **静止红**        esp_lcd_touch_new_i2c_gt911() 失败，任务没起来
 *   **静止绿**        初始化过了但任务没跑起来（xTaskCreate 失败/卡死）
 *   什么都没有        touch_start() 压根没被调到，或显示链路本身有问题
 *
 * ② x=24：**最近一次**触摸读取的结果（与心跳同频刷新，约 500ms）
 *   蓝   esp_lcd_touch_read_data() 出错 ⇒ I2C 层不通了
 *   黄   read_data 过了但 esp_lcd_touch_get_data() 出错
 *   暗灰 两者都 OK、但 points == 0（**没手指时的正常色**）
 *   品红 points > 0，读到触点了 ⇒ GT911 侧没问题，问题在 HID/host（成因 B）
 *
 * 品红一旦出现就**粘住不再变回暗灰**：触摸是瞬时的，500ms 采样极易错过，
 * 不粘住的话手指一抬就看不到证据了。
 *
 * 另外点屏时会在触点处画 24×24 红块，落点即 GT911 报的面板原生坐标
 * （刻意不经 touch_map 变换），顺带验证读数本身合不合理。
 *
 * 代价（所以不能长期留着）：心跳每 500ms 触发两次整帧 cache 回写(各 1.8MB)，
 * 且会在 host 的 GUD 画面上留下色块。
 */
#define TOUCH_DEBUG_MARKER 1

#if TOUCH_DEBUG_MARKER
/* 左上角状态块（面板原生坐标系）：① 初始化状态 + 心跳，② 最近一次读取结果 */
#define DBG_STATUS_X     0
#define DBG_READ_X       24       /* 与 ① 留 8px 间隔，避免两块糊成一条 */
#define DBG_STATUS_Y     0
#define DBG_STATUS_SIZE  16
/* 触点块：比状态块大一圈，好和它区分开 */
#define DBG_POINT_SIZE   24
#define DBG_GREEN        0x07E0   /* 初始化成功 */
#define DBG_GREEN_DIM    0x03E0   /* 心跳的另一相 */
#define DBG_RED          0xF800   /* 初始化失败 / 读到触点 */
#define DBG_BLUE         0x001F   /* read_data 出错 */
#define DBG_YELLOW       0xFFE0   /* get_data 出错 */
#define DBG_GREY         0x39E7   /* 读取正常但 points == 0 */
#define DBG_MAGENTA      0xF81F   /* points > 0（粘住） */
#endif

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
#if TOUCH_DEBUG_MARKER
    bool     dbg_blink = false;
    int      dbg_tick = 0;
    /* 最近一次读取结果的颜色。初值取暗灰（= 读得通但没触点），这样开机后
     * 若这块一直是暗灰，含义明确：「I2C 通、就是一个点都读不到」。 */
    uint16_t dbg_read = DBG_GREY;
    /* 品红粘住标志：见文件头说明，500ms 采样错过瞬时触摸的概率很高。 */
    bool     dbg_ever_touched = false;
#endif

    while (1) {
        vTaskDelay(pdMS_TO_TICKS(TOUCH_POLL_MS));

#if TOUCH_DEBUG_MARKER
        /* 心跳画在**读 I2C 之前**：这样它只证明「任务还在跑」这一件事。
         * 若画在读之后，一条读失败的 continue 就会把心跳停掉，「任务卡死」
         * 与「GT911 读不通」在屏上就混成同一个现象了。
         *
         * 但**不能每轮都画**：display_debug_marker() 结尾要整帧 cache 回写
         * (1.8MB)，20ms 一次 ≈ 92MB/s，会挤占 PSRAM 带宽、把 GUD 显示拖卡，
         * 反而干扰判读。降到每 25 轮(约 500ms)一次，肉眼看仍是清晰的闪烁，
         * 回写量降到 1/25。触点红块只在真有触摸时画，本来就不常态触发。 */
        if (++dbg_tick >= 25) {
            dbg_tick = 0;
            dbg_blink = !dbg_blink;
            display_debug_marker(DBG_STATUS_X, DBG_STATUS_Y,
                                 DBG_STATUS_SIZE, DBG_STATUS_SIZE,
                                 dbg_blink ? DBG_GREEN : DBG_GREEN_DIM);
            /* 读取结果块同样只在心跳节拍重画（而不是每轮），理由同上：
             * 每次 display_debug_marker() 都要整帧回写 1.8MB。 */
            display_debug_marker(DBG_READ_X, DBG_STATUS_Y,
                                 DBG_STATUS_SIZE, DBG_STATUS_SIZE,
                                 dbg_ever_touched ? DBG_MAGENTA : dbg_read);
        }
#endif

        if (esp_lcd_touch_read_data(s_tp) != ESP_OK) {
#if TOUCH_DEBUG_MARKER
            dbg_read = DBG_BLUE;
#endif
            continue;
        }

        /* 用 esp_lcd_touch_get_data() 而非 esp_lcd_touch_get_coordinates()：
         * 后者在 esp_lcd_touch 1.2.x 已标 deprecated（2.0.0 移除），编译告警。 */
        esp_lcd_touch_point_data_t pts[TOUCH_POINTS_MAX];
        uint8_t points = 0;
        if (esp_lcd_touch_get_data(s_tp, pts, &points, TOUCH_POINTS_MAX) != ESP_OK) {
#if TOUCH_DEBUG_MARKER
            dbg_read = DBG_YELLOW;
#endif
            continue;
        }

#if TOUCH_DEBUG_MARKER
        dbg_read = (points > 0) ? DBG_MAGENTA : DBG_GREY;

        /* 用 pts[0] 的**面板原生坐标**直接落点，刻意不经 touch_map_panel_to_gud()：
         * 这里要看的是 GT911 出的最原始读数，套上变换就看不出是读数错还是变换错。
         * 无触点时不擦除上一个红块 —— 留痕比闪一下更容易观察，host 的 GUD 帧
         * 迟早会把它盖掉。 */
        if (points > 0) {
            dbg_ever_touched = true;
            display_debug_marker(pts[0].x, pts[0].y,
                                 DBG_POINT_SIZE, DBG_POINT_SIZE, DBG_RED);
        }
#endif

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
     * ⚠️⚠️ Tab5 v1（ILI9881C + GT911）硬件上 INT 脚有一颗**到 3V3 的上拉电阻**，
     * 它会压住 GT911 不出坐标：I2C 读得到产品 ID、初始化一路成功，但状态寄存器
     * 0x814E 的 buffer-ready 位(bit7)永远不置起，表现正是「初始化过、心跳正常、
     * 就是一个触点都读不到」。必须由 ESP 侧把 INT **主动驱动到低**压住那颗上拉。
     *
     * 这不是猜测：官方 esp-bsp `bsp/m5stack_tab5/src/bsp_display.c` 的
     * bsp_touch_new() 在 board_version == 1 分支专门做了这件事，注释原文——
     *   "Keep LCD touch interrupt pin in low for working touch
     *    Note: This is the fix (ver 1) - there is resistor to 3V3 on interrupt
     *    pin which is blocking GT911 touch."
     * 我们此前只对照了 BSP 里 tp_cfg 的初始化列表（那部分确实逐项相同），漏看了
     * 紧随其后的这段 GPIO 操作，于是复现了这个「BSP 已知并已修」的坑。
     *
     * 两个细节缺一不可：
     *  1) 必须在 esp_lcd_touch_new_i2c_gt911() **之前**驱动低；
     *  2) 且必须把 tp_cfg.int_gpio_num 置成 GPIO_NUM_NC —— 否则驱动会在
     *     esp_lcd_touch_gt911.c:152 把这个脚重新 gpio_config() 成 INPUT，
     *     把我们刚驱动的低电平抹掉，等于没修。官方 BSP 同样是先在 tp_cfg 里填了
     *     BSP_LCD_TOUCH_INT、随后一行改写成 GPIO_NUM_NC，正是为此。
     * 代价：放弃中断驱动触摸的可能。本来也没用上（我们是 20ms 轮询），不影响。
     *
     * I2C 地址不受影响：GT911 只在**上电/复位瞬间**按 INT 电平 latch 地址
     * （高⇒0x14、低⇒0x5D），那一刻由板上那颗外部上拉决定为高；此处拉低发生在
     * board_power_init() 拉起 TOUCH_EN 之后很久（中间还隔着 195 条面板 init 命令），
     * 地址早已锁定。顺带：display_dsi.c 的 panel_detect() 已 i2c_master_probe(0x14)
     * 成功才选了 ILI9881C 分支，0x14 这个地址本身是实测无疑的。
     *
     * ⚠️⚠️ 若这个修**没解决问题**，Plan B 是补 M5 官方的复位时序 —— 但两者
     * **有致命的先后顺序要求，写反会更坏**：
     *   M5Tab5-UserDemo 的 bsp_reset_tp() 与 M5GFX 都通过 IO 扩展 0x43 的 **P5**
     *   （即我们 board_power_init() 里那个 TOUCH_EN，M5 管它叫 TP_RST）做一次
     *   low→delay→high 的显式复位，且**全程把 INT 保持在高**以 latch 0x14；
     *   我们现在只把 P5 置了高，从没拉低过，等于没有干净的复位沿。
     *   要补的话必须是「先拉高 INT → 脉冲 P5 → 等 100ms → 再执行本函数的 INT 拉低」。
     *   若在 INT 已经被拉低之后才去脉冲 P5，GT911 会 latch 成 **0x5D**，
     *   连 I2C 都不再应答（屏上②会从暗灰变蓝），比现在还糟。
     *
     * 之所以先试 esp-bsp 这条而不是 M5 那条：esp-bsp 用的是**和我们完全相同的
     * esp_lcd_touch_gt911 驱动栈**，且那段注释明确写着是针对 board version 1
     * （ILI9881C + GT911，正是我们这块）的修正；M5GFX 走的是自己的触摸实现。
     */
    const gpio_config_t int_gpio_cfg = {
        .mode = GPIO_MODE_OUTPUT,
        .intr_type = GPIO_INTR_DISABLE,
        .pull_down_en = 0,
        .pull_up_en = 1,     /* 与 BSP 逐字一致；推挽输出下内部上拉不起作用 */
        .pin_bit_mask = BIT64(PIN_TOUCH_INT),
    };
    ESP_RETURN_ON_ERROR(gpio_config(&int_gpio_cfg), TAG, "touch int gpio");
    ESP_RETURN_ON_ERROR(gpio_set_level(PIN_TOUCH_INT, 0), TAG, "touch int 拉低");

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
         * **故意填 NC，尽管 INT 脚确实存在（G23）**。见上方那段长注释：G23 已被我们
         * 亲手配成输出并驱动到低以压住板上到 3V3 的上拉；这里若填 PIN_TOUCH_INT，
         * GT911 驱动会把它重新 gpio_config() 成 INPUT+NEGEDGE，低电平立刻失效，
         * 触摸又变回读不到点。官方 BSP 也是填 GPIO_NUM_NC。
         * 副作用：走的是驱动里 rst/int 皆 NC 的那条分支（打印 "I2C address
         * initialization procedure skipped"），本就是我们此前的行为，无变化。
         */
        .int_gpio_num = GPIO_NUM_NC,
        .levels = {
            .reset = 0,
            .interrupt = 0,
        },
        /*
         * 三个方向 flag 全 0 —— **不是待标定的占位值，是官方 BSP 的取值**。
         * esp-bsp `bsp/m5stack_tab5/src/bsp_display.c` 的 tp_cfg 初始化列表与此
         * 逐项相同：x_max/y_max = 720/1280、rst = NC、levels.interrupt = 0、
         * 三个 flag 全 false。即 GT911 就是按面板原生 720×1280 竖向出数，
         * touch_map.c 的反变换直接可用。
         * （⚠️ 但**只有初始化列表相同**：BSP 随后还改写了 int_gpio_num 并驱动 INT 到低，
         *  见本函数开头。当初"配置逐项相同"的结论就是漏看那两行才得出的。）
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
     * （free(tp)；int/rst 都是 NC 所以不会去动 G23，我们驱动的低电平得以保留），
     * **不碰我们传进去的 io**；而 touch_start() 失败现在不再 abort（见 app_main），
     * 这个 io 会一直挂在内部 I2C 总线的设备链上没人回收。
     *
     * ⚠️ 这个返回值比看上去有分量：esp_lcd_touch_new_i2c_gt911() 结尾**无条件**调用
     * touch_gt911_read_cfg()，后者要读产品 ID(0x8140, 3B) 和配置版本(0x8047, 1B)，
     * 任一 I2C 读失败就整个 goto err 返回错误。所以**它返回 ESP_OK 就等于证明了
     * GT911 在 0x14 上有应答、寄存器读得通**（rst==NC 只跳过前面那段地址选择流程，
     * 不影响这次读）。排查时别再把 I2C 层当嫌疑对象——那一环已经被这行代码验过了。
     */
    esp_err_t err = esp_lcd_touch_new_i2c_gt911(io, &tp_cfg, &s_tp);
    if (err != ESP_OK) {
        esp_lcd_panel_io_del(io);
        ESP_LOGE(TAG, "gt911 未应答(0x%02x)：%s，检查内部 I2C 与触摸电源",
                 ESP_LCD_TOUCH_IO_I2C_GT911_ADDRESS_BACKUP, esp_err_to_name(err));
#if TOUCH_DEBUG_MARKER
        /* 左上角常驻红块 = GT911 初始化失败。此后不会再有任何绘制（任务没起来），
         * 所以它是**静止**的，与心跳的绿色闪烁在屏上一眼可分。
         * app_main 的调用顺序保证 display_init() 已完成、帧缓冲可用；
         * display_debug_marker() 内部另有 s_fb == NULL 的防御。 */
        display_debug_marker(DBG_STATUS_X, DBG_STATUS_Y,
                             DBG_STATUS_SIZE, DBG_STATUS_SIZE, DBG_RED);
#endif
        return err;
    }

    ESP_LOGI(TAG, "gt911 ready (addr=0x%02x, int=G%d 由本函数驱动为低)",
             ESP_LCD_TOUCH_IO_I2C_GT911_ADDRESS_BACKUP, PIN_TOUCH_INT);

#if TOUCH_DEBUG_MARKER
    /* 初始化成功先画一次绿块，再交给 touch_task 去闪。多这一笔是为了把
     * 「起来了但任务没跑起来」也显出来：那种情况下屏上是**静止的绿块**。 */
    display_debug_marker(DBG_STATUS_X, DBG_STATUS_Y,
                         DBG_STATUS_SIZE, DBG_STATUS_SIZE, DBG_GREEN);
#endif

    xTaskCreate(touch_task, "touch", 4096, NULL, 5, NULL);
    return ESP_OK;
}
