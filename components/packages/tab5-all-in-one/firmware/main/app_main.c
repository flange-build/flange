#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_log.h"
#include "tinyusb.h"
#include "tinyusb_default_config.h"
#include "display_dsi.h"
#include "usb_descriptors.h"
#include "gud_device.h"
#include "board_power.h"
#include "kbd_i2c.h"
#include "touch_hid.h"
#include "codec_audio.h"
#include "driver/gpio.h"                /* gpio_set_drive_capability */
#include "esp_private/periph_ctrl.h"    /* PERIPH_RCC_ATOMIC */
#include "hal/usb_wrap_ll.h"   /* usb_wrap_ll_phy_select：把内部 FSLS PHY 0 判给 OTG1.1 */
#include "tab5_pins.h"
#if CONFIG_TINYUSB_CDC_ENABLED
/* ⚠️ 这两个头必须在 #if 内包含：tinyusb_cdc_acm.h 在 CDC 未开启时会 #error。 */
#include "tinyusb_cdc_acm.h"
#include "tinyusb_console.h"
#endif

static const char *TAG = "tab5_aio";

/*
 * 把内部 FSLS PHY 0 从 USB-Serial/JTAG 手里划给 USB_WRAP(OTG1.1)。
 *
 * ESP32-P4 有**两条**内部 FSLS PHY，靠 LP_SYS.usb_ctrl 里的一个选择器做映射
 * （见 hal/usb_wrap_ll.h 的注释）：
 *     sw_usb_phy_sel = false（默认）→ USJ 用 PHY 0，USB_WRAP 用 PHY 1
 *     sw_usb_phy_sel = true         → USJ 用 PHY 1，USB_WRAP 用 PHY 0
 * 而 **PHY 0 才是引到 GPIO24/25 的那条**，也就是 Tab5 USB-C 实际接的地方。
 *
 * 关键：IDF v6.0 里 usb_wrap_ll_phy_select() / usb_serial_jtag_ll_phy_select()
 * **没有任何调用点** —— `usb_new_phy()` 只配置 OTG 那一侧，不碰这个映射。
 * 所以不显式改的话，TinyUSB 在 PHY 1（未引出）上发数据，USJ 稳稳占着 USB-C，
 * 主机看到的就只有 `303a:1001` 的 CDC ACM，`16d0:10a9` 永远不出现。
 *
 * 这是 P4 独有的：ESP32-S3 只有一条 FSLS PHY，没有这个映射矩阵，
 * 所以 S3 上的 TinyUSB 工程不需要这一步（也正因如此这个坑很难从 S3 经验推出来）。
 *
 * 必须在 tinyusb_driver_install() 之前调用。
 */
static void route_fsls_phy0_to_otg(void)
{
    usb_wrap_ll_phy_select(&USB_WRAP, 0);

    /*
     * ⚠️ 提前打开 USB_WRAP 的总线时钟。
     *
     * 换过 PHY 之后，**任何人**把 G26/G27 配成 IO_MUX 功能，IDF 的
     * gpio_ll_func_sel() 都会顺手写一次 USB_WRAP.otg_conf.usb_pad_enable = 0
     * （机理见 tab5_pins.h 音频段）。而 I2S 配脚发生在 tinyusb_driver_install()
     * **之前**（见 app_main 里的顺序说明），那时 USB_WRAP 的总线时钟还是关的 ——
     * IDF 启动阶段 esp_perip_clk_init() 已经把 HP_SYS_CLKRST.soc_clk_ctrl1 的
     * reg_usb_otg11_sys_clk_en 清零（esp_hal_clock/esp32p4/clk_gate_ll.h:321-323）。
     * 对时钟被门控的外设做寄存器访问在 P4 上是总线错误，所以先把它打开。
     *
     * 打开它没有副作用：tinyusb_driver_install() → usb_wrap_hal_init() 马上又会
     * 打开一次（esp_hal_usb/usb_wrap_hal.c:11-19），我们只是把它提前了几毫秒。
     * soc_clk_ctrl1 / hp_usb_clkrst_ctrl0 是与别的外设共用的 32 位寄存器，
     * 必须走 PERIPH_RCC_ATOMIC() 的读改写锁，不能裸写。
     */
    PERIPH_RCC_ATOMIC() {
        usb_wrap_ll_enable_bus_clock(true);
    }

    ESP_LOGI(TAG, "内部 FSLS PHY 0 已划给 OTG1.1（USB-C 从 USB-Serial/JTAG 收回）");
}

/*
 * 把 I2S 配 G26/G27 时被 IDF **误伤**的三样东西修回来。
 *
 * 机理（完整版见 tab5_pins.h 的音频段，那里有逐行源码出处）：IDF 的
 * gpio_ll_func_sel() / gpio_ll_pullup_dis() 都写死了「PHY0 归 USJ、PHY1 归 OTG」
 * 这个默认映射，而 route_fsls_phy0_to_otg() 恰恰把它对调了。于是每次有人把
 * G26/G27 配成 IO_MUX 功能，IDF 都以为在关 PHY1 的焊盘，实际关掉的是
 * **PHY0 = G24/G25 = USB-C**。
 *
 * 三个动作，按「确认必需 / 保险起见」分：
 *
 *  1. usb_pad_enable = 1 —— **确认必需**。这就是被误伤的那一位。
 *     正常路径上 tinyusb_driver_install() → usb_wrap_hal_init() →
 *     usb_wrap_ll_phy_set_defaults() 已经把它置回 1（usb_wrap_hal.c:11-19），
 *     这里再写一次是幂等兜底：万一日后有人在装 TinyUSB **之后**再动这两个脚
 *     （改引脚、加第二个 I2S、gpio_reset_pin(26) …），这一行就是唯一的救命稻草。
 *
 *  2. pad_pull_override = 0 —— **保险起见**。gpio_ll_pullup_dis(G27) 会写
 *     pad_pull_override=1 / dp_pullup=0，换过 PHY 之后等于拿掉 G25(D+) 的上拉，
 *     主机会直接看不到设备。当前 I2S 路径不走这条（i2s_gpio_check_and_set() 只调
 *     gpio_func_sel / gpio_input_enable / esp_rom_gpio_connect_out_signal），
 *     但同一个 bug 家族，清回硬件默认（0 = 上下拉交给 PHY 硬件管）零成本。
 *     ⓘ device 模式下 IDF 本来就不用这个 override（usb_phy.c 只在 HOST 模式里
 *       调 usb_wrap_hal_phy_enable_pull_override），所以清它不会破坏任何东西。
 *
 *  3. 驱动能力回默认 —— **保险起见 / 卫生**。usb_phy.c:309-313 会**无条件**把
 *     usb_dwc_info.controllers[1].internal_phy_io（写死 dm=26/dp=27）这两个脚的
 *     驱动能力抬到 GPIO_DRIVE_CAP_3(40mA)，原文注释：
 *         "For FSLS PHY that shares pads with GPIO peripheral, we must set
 *          drive capability to 3 (40mA)"
 *     它同样不知道我们换了 PHY —— 抬的是 I2S 在用的两个脚，而不是 USB 在用的。
 *     I2S 驱动自己从不碰驱动能力（i2s_common.c 的 i2s_gpio_check_and_set() 只做
 *     func_sel / 信号矩阵），所以这 40mA 会一直留在音频线上。恢复成焊盘复位默认
 *     GPIO_DRIVE_CAP_DEFAULT(=2 ≈ 20mA)，让这两个脚和别的普通 GPIO 一模一样。
 *     ⓘ 2 确实就是 G26/G27 的复位值：P4 TRM 第 9 章引脚表给 GPIO26/27 的 DRV
 *       复位值是 2，而 GPIO24/25 是 3（datasheet：「默认驱动强度 20 mA，
 *       GPIO24/GPIO25 例外，为 40 mA」）。也与 io_mux_struct.h 的 fun_drv
 *       default: 2 对上。**不设成更弱**：超出「只收拾自己制造的烂摊子」的范围，
 *       且 BCLK 要驱动两颗 codec。
 *     ⚠️ 千万**别**顺手去调低 G24/G25 的驱动能力：usb_phy.c 那段写死了 26/27，
 *       从来不碰 24/25 —— USB-C 能工作全靠这两个脚复位值本来就是 3(40mA)。
 *
 * 必须排在 tinyusb_driver_install() **之后**：动作 3 撤销的正是它内部做的事，
 * 放在前面会被它重新抬上去。
 */
static void otg_fsls_pads_repair(void)
{
    const bool pad_was_enabled = usb_wrap_ll_phy_is_pad_enabled(&USB_WRAP);

    usb_wrap_ll_phy_enable_pad(&USB_WRAP, true);
    usb_wrap_ll_phy_disable_pull_override(&USB_WRAP);
    gpio_set_drive_capability(PIN_I2S_DOUT, GPIO_DRIVE_CAP_DEFAULT);
    gpio_set_drive_capability(PIN_I2S_SCLK, GPIO_DRIVE_CAP_DEFAULT);

    /*
     * 与 app_main() 里 codec_audio_init() 之后那条日志配成一对：那条应当读到 0
     * （I2S 刚把焊盘关掉），这条应当读到 1（install 里的
     * usb_wrap_ll_phy_set_defaults() 又置回来了）。两条一起构成机理的现场证据。
     * 若这条读到 0，说明又有人在装 TinyUSB **之后**配了 G26/G27 —— 那本函数就得
     * 跟着挪到那次配脚之后。
     */
    ESP_LOGI(TAG, "OTG FSLS 焊盘已修复（进入时 usb_pad_enable=%d，应为 1；G26/G27 驱动能力回默认）",
             pad_was_enabled);
}

void app_main(void)
{
    ESP_ERROR_CHECK(board_power_init());

    ESP_ERROR_CHECK(display_init());

    display_standby_screen();

    /* GUD 控制协议状态机初始化（须在 TinyUSB 安装前，回调可能立即触发） */
    ESP_ERROR_CHECK(gud_device_init());

    /*
     * ⚠️ 必须显式选全速端口。Tab5 的 USB-C 接在 P4 的 USB1P1 全速 PHY(GPIO24/25)
     * 上，高速 PHY(USB2_OTG_D±) 接的是 USB-A 母座。而 esp_tinyusb 2.2.1 的
     * TINYUSB_DEFAULT_CONFIG() 在 ESP32-P4 上默认展开为 HIGH_SPEED —— 用默认值
     * 会驱动错的 PHY，USB-C 永远枚举不出来。
     */
    route_fsls_phy0_to_otg();

    /*
     * ⚠️⚠️ 音频的**硬件** bring-up 必须排在 tinyusb_driver_install() 之前，
     *      而数据泵必须排在它之后。这个顺序不是风格问题，是这块板最贵的那个坑：
     *
     * codec_audio_init() 里 i2s_channel_init_std_mode() 会把 G26/G27 配成
     * IO_MUX 功能，而 IDF 的 gpio_ll_func_sel() 见到这两个脚就会写一次
     * USB_WRAP.otg_conf.usb_pad_enable = 0 —— 换过 PHY 之后那一位管的是
     * **G24/G25 这条 USB-C**。放在这里，误伤发生时 USB 还没连上主机，
     * 随后 tinyusb_driver_install() 内部的 usb_new_phy() 会把它重新置 1，
     * **不存在「已枚举的设备被短暂拔掉」的窗口**。
     * 若反过来（音频在后），主机会看到一次 disconnect，GUD/HID 全部重来。
     * 完整机理与源码出处见 tab5_pins.h 的音频段。
     *
     * 与键盘/触摸同一处置原则：失败只降级、不拦启动。描述符是静态的，
     * 即便这里失败 host 照样枚举出声卡，只是收发到静音 —— 而显示(GUD)
     * 才是这个产品的核心形态，不该被一颗 codec 拖垮。
     *
     * ⓘ 代价：codec 的 I2C 序列（约几十毫秒）排在了 USB 上电之前，开机到主机
     *   看见设备会晚这么多。可接受，也让 codec 的 I2C 不必与 USB 中断抢时间。
     */
    esp_err_t audio_err = codec_audio_init();
    if (audio_err != ESP_OK)
        ESP_LOGW(TAG, "音频硬件初始化失败(%s)，继续启动（USB 不受影响）",
                 esp_err_to_name(audio_err));

    /*
     * ⓘ **机理的现场证据，别删。** 此刻读到的 usb_pad_enable 应当是 **0** ——
     * 那正是 i2s_channel_init_std_mode() 配 G26/G27 时 IDF 顺手写下的。
     * 这一行把「IDF 会误伤 USB-C 焊盘」从推断变成一条可在串口上看到的事实；
     * 下一句 tinyusb_driver_install() 会把它置回 1（见 otg_fsls_pads_repair()）。
     * 若这里读到 1，说明 I2S 根本没配那两个脚 —— 那就是 codec_audio_init() 在
     * i2s_full_duplex_init() 之前就失败了，与本机理无关。
     */
    ESP_LOGI(TAG, "音频硬件就绪；此刻 OTG usb_pad_enable=%d（配过 G26/G27 时应为 0）",
             usb_wrap_ll_phy_is_pad_enabled(&USB_WRAP));

    tinyusb_config_t tusb_cfg = TINYUSB_CONFIG_FULL_SPEED(NULL, NULL);
    tusb_cfg.descriptor.device = &aio_desc_device;
    tusb_cfg.descriptor.full_speed_config = aio_desc_configuration;
    tusb_cfg.descriptor.string = aio_string_desc_arr;
    tusb_cfg.descriptor.string_count = aio_string_desc_count;
    ESP_ERROR_CHECK(tinyusb_driver_install(&tusb_cfg));
    ESP_LOGI(TAG, "tinyusb installed (GUD + HID + UAC1)");

    /* 把 usb_new_phy() 顺手抬到 40mA 的 G26/G27 驱动能力等三样东西修回来。
     * 必须紧跟 install，且必须在 codec_audio_start() 之前 —— 见函数上方注释。 */
    otg_fsls_pads_repair();

#if CONFIG_TINYUSB_CDC_ENABLED
    /*
     * 可选的 USB CDC 调试串口（默认关闭，开关是 menuconfig 里的
     * Tab5 All-in-One → CONFIG_AIO_DEBUG_CDC，它会 select 出本宏）。
     *
     * 这块板现场没有可用串口：USB-Serial/JTAG 被关掉了（TinyUSB 要占那条 FSLS PHY），
     * UART0 只在 M5-Bus 排针上。开启本段后 ESP_LOG* 直接从 USB-C 出来，
     * `idf.py monitor` 即可看，代价是让出 GUD 的 IN 端点（GUD 不用它）与 UVC
     * 预留的 0x84，4 条可用 IN 端点用满（端点表与依据见 usb_descriptors.h）。
     *
     * ⚠️ **开机早期的日志会丢。** tinyusb_console_init() 之后 stdout / ESP_LOG* 就写进
     * CDC 的 TX 环形缓冲，而这些字节要等 host 侧真的把 ttyACM 打开并开始读才会流出去 ——
     * 从上电到你敲下 `idf.py monitor` 之间产生的日志，超出缓冲的部分被覆盖丢弃。
     * 看不到最前面几行是**正常现象，不是 bug**；要抓上电阶段请接 UART0(G37/G38)。
     *
     * 失败只记 WARNING 继续：调试设施挂了不该拖垮已验证的显示/键盘/触摸，
     * 与下方 kbd_start() / touch_start() 同一处置原则。
     */
    const tinyusb_config_cdcacm_t acm_cfg = { .cdc_port = TINYUSB_CDC_ACM_0 };
    esp_err_t cdc_err = tinyusb_cdcacm_init(&acm_cfg);
    if (cdc_err != ESP_OK) {
        ESP_LOGW(TAG, "CDC 调试串口初始化失败(%s)，继续启动（日志仍走 UART0）",
                 esp_err_to_name(cdc_err));
    } else {
        cdc_err = tinyusb_console_init(TINYUSB_CDC_ACM_0);
        if (cdc_err != ESP_OK)
            ESP_LOGW(TAG, "CDC 控制台重定向失败(%s)，继续启动（日志仍走 UART0）",
                     esp_err_to_name(cdc_err));
        else
            ESP_LOGI(TAG, "CDC 调试串口已启用，日志改从 USB-C 输出");
    }
#endif

    /*
     * 键盘与触摸是**可选外设**，缺席时只降级、不拦启动：
     *   - Tab5 Keyboard 是可拆配件（2×5 排针），不接底座时 kbd_start() 里的
     *     i2c_master_probe(0x6D) 必然失败；
     *   - 触摸控制器随面板批次而异（GT911 / ST7123）。
     * 若这里照旧用 ESP_ERROR_CHECK，一个没插的配件就会把整机打进 boot loop，
     * 连屏幕都没有 —— 而显示(GUD)才是这个产品的核心形态。
     * 对比：board_power / display / gud_device / TinyUSB 仍用 ESP_ERROR_CHECK，
     * 那些是核心链路，起不来就没有任何可用形态，早死早报比带病运行好。
     * 日志用 WARNING 而非 ERROR，并写明「可能是正常的」，免得用户以为坏了。
     */
    esp_err_t err = kbd_start();
    if (err != ESP_OK)
        ESP_LOGW(TAG, "键盘不可用(%s)，继续启动；未插键盘底座时属正常",
                 esp_err_to_name(err));

    err = touch_start();
    if (err != ESP_OK)
        ESP_LOGW(TAG, "触摸不可用(%s)，继续启动", esp_err_to_name(err));

    /*
     * UAC1 音频的**第二半**：功放上电 + 数据泵任务。硬件 bring-up 已经在
     * tinyusb_driver_install() 之前跑过了（见上面那段 codec_audio_init() 的注释）。
     *
     * 必须排在 tinyusb_driver_install() 之后：数据泵任务一起来就会调 tud_audio_*。
     * 与键盘/触摸同一处置原则：失败只降级、不拦启动。
     */
    /*
     * ⚠️ **无条件调用**，别再拿 audio_err 一票否决。
     *
     * 播放(ES8388) 与录音(ES7210) 是两颗独立芯片、两条独立的 USB streaming 接口，
     * 本来就该各自降级；此处曾经的 `if (audio_err == ESP_OK)` 把它们绑成全有全无 ——
     * ES7210 一挂，完好的 ES8388 连功放都不开，用户一声都听不到。
     * codec_audio_init() 现在只在 **I2S 本身**起不来时才返回错误（那时两个方向都
     * 没戏），单颗 codec 的失败记在自检快照里，由 codec_audio_start() 自己按
     * 「哪条链路可用」决定开不开功放、怎么跑数据泵。
     */
    err = codec_audio_start();
    if (err != ESP_OK)
        ESP_LOGW(TAG, "音频不可用(%s)，继续启动", esp_err_to_name(err));

    /*
     * 音频自检快照打一遍。codec_audio_init() 跑在 tinyusb_driver_install() 之前，
     * 它那一段 ESP_LOG* 在开 CDC 的档下现场一个字看不到（串口那时还没起来），
     * 所以把「卡在哪一步」的结论留到这里补打。UART0 那条控制台没有覆盖问题，
     * 打一遍就够。
     */
    codec_audio_report();

    while (1) {
        vTaskDelay(pdMS_TO_TICKS(10000));
#if CONFIG_AIO_DEBUG_CDC
        /*
         * 只有开了 CDC 日志串口才**复读**自检，理由是 CDC 独有的一个性质：
         * 它的 TX 环形缓冲只有几百字节，且要等 host 打开 ttyACM 才开始流 ——
         * 上面那一遍在用户敲下 `idf.py monitor` 之前早被冲掉了，不复读等于没打。
         * UART0 控制台没有这个问题（字节直接出去、终端有回滚），所以默认档
         * 不复读：每轮要做十几次 I2C 寄存器回读，而那条内部总线还挂着触摸、
         * IO 扩展与 IMU，白占带宽。要连续观察就开 CONFIG_AIO_DEBUG_CDC。
         */
        codec_audio_report();
#endif
    }
}
