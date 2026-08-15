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
#if AIO_HAS_AUDIO
#include "codec_audio.h"
#endif
#include "uvc_stream.h"
#include "camera_csi.h"
#include "driver/gpio.h"                /* gpio_set_drive_capability */
#include "esp_private/periph_ctrl.h"    /* PERIPH_RCC_ATOMIC */
#include "hal/usb_wrap_ll.h"   /* usb_wrap_ll_phy_select：把内部 FSLS PHY 0 判给 OTG1.1 */
#include "soc/usb_dwc_struct.h"         /* 实测 DWC2 的 FIFO 分配，见 log_usb_fifo_usage() */
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

/*
 * 实测 DWC2 的 FIFO 分配。P4 全速控制器整块 SPRAM 只有 256 words(1 KB)，而且
 * **buffer DMA 模式下还要先扣掉 2×ep_count = 14 words**（dcd_dwc2.c:257-263，
 * is_dma 成立：CONFIG_TINYUSB_MODE_DMA=y 且 P4 的 OTG11_ARCHITECTURE=2=内部 DMA）
 * ⇒ 真正可分配的只有 **242 words**。这块要装下共享 RX FIFO + 每条 IN 端点的
 * TX FIFO。不够时 dfifo_alloc() 只是 TU_ASSERT 返回 false，**默认日志等级下
 * 一个字都不打** —— 症状是 SET_INTERFACE 被 STALL、某个接口静默不工作。
 *
 * 布局（dcd_dwc2.c 顶部大注释）：地址 0 起是 RX FIFO，顶部往下依次是 EP0 IN、
 * EP1 IN… 的 TX FIFO，中间那段是空闲。空闲 = 最低的 TX 起始地址 − RX 大小。
 *
 * ⚠️ 必须等 host 完成 SET_CONFIGURATION 之后再读：端点是那时才 open、
 *    FIFO 是那时才分配的。调用点在 app_main 末尾的空转循环里，tud_mounted() 后触发。
 *
 * ⚠️ **视频流的 TX FIFO 与 alt 无关，SET_CONFIGURATION 时就分掉了。**（这一条推翻了
 *    计划 Task5 里「alt 1 才分配、所以 alt 0 下 EP4 IN 那一行不出现是正常的」的说法，
 *    以及随之而来的「已用 119→231」的两段式预期。）逐行依据：
 *      tusb_mcu.h:768-770  dwc2 没定义 TUP_DCD_EDPT_CLOSE_API ⇒ TUP_DCD_EDPT_ISO_ALLOC 成立
 *      video_device.c:1404-1422  videod_open() 里就调 usbd_edpt_iso_alloc()
 *      dcd_dwc2.c:634-637  → dfifo_alloc()，此刻写下 DIEPTXF4
 *      video_device.c:866-871  alt 1 只调 usbd_edpt_iso_activate() → edpt_activate()，
 *                              那里只写 DIEPCTL，**不碰 FIFO**
 *    UAC 的 ISO 端点同理（audio_device.c:953-965），所以下面那笔账里 0x83 与 0x84
 *    一样都是「枚举完就在」。
 *    ⇒ **EP4 IN 那一行枚举后就该出现，摄像头开不开都一样**；它不出现就是
 *      usbd_edpt_iso_alloc() 失败了 —— 而它的返回值 video_device.c 根本不检查，
 *      彻底静默：设备照样枚举、uvcvideo 照样绑、alt 1 照样成功，只是一帧都发不出来
 *      （计划 Task5 Step6 第 4 条预期的「SET_INTERFACE 被 STALL」不会发生，
 *       实际症状是 uvc_stream_report() 里「提交一直涨、完成不涨」）。
 */
static void log_usb_fifo_usage(void)
{
    usb_dwc_dev_t *dev = &USB_DWC_FS;      /* Tab5 的 USB-C 接的是全速控制器 */
    const uint16_t rx = dev->grxfsiz_reg.rxfdep;
    uint16_t lowest = 0xFFFF, used = rx;

    uint16_t sz = dev->gnptxfsiz_reg.nptxfdep, off = dev->gnptxfsiz_reg.nptxfstaddr;
    ESP_LOGI(TAG, "FIFO: RX=%u words, EP0 IN=%u@%u", rx, sz, off);
    used = (uint16_t)(used + sz);
    if (sz && off < lowest)
        lowest = off;

    for (int n = 1; n <= 4; n++) {          /* 全速控制器最多 4 条可用 IN 端点 */
        sz = dev->dieptxfi_regs[n - 1].inepntxfdep;
        off = dev->dieptxfi_regs[n - 1].inepntxfstaddr;
        if (sz == 0)
            continue;
        ESP_LOGI(TAG, "FIFO: EP%d IN=%u words @%u", n, sz, off);
        used = (uint16_t)(used + sz);
        if (off < lowest)
            lowest = off;
    }
    const unsigned free_words = (unsigned)(lowest - rx);
    ESP_LOGI(TAG, "FIFO: 已用 %u words，空闲 %u words (%u 字节)；UVC 端点占 %u words",
             used, free_words, free_words * 4, (unsigned)((UVC_EP_SIZE + 3) / 4));
    /* 静态验算（UVC 的 112 words 已含在内，见上方 ⚠️：与 alt 无关，枚举完就在）：
     *   默认档   RX 62 + EP0 16 + 0x81 16 + 0x82 16 + 0x83 9 + 0x84 112 = 已用 231 / 空闲 11
     *   UVC 调试档 RX 62 + EP0 16 + 0x81 16 + 0x82 16 + 0x83 2 + 0x84 112 = 已用 224 / 空闲 18
     * 这两个数**从枚举到拔线不变**，开不开摄像头都一样。差得多就说明账算错了，
     * 或者有人偷偷加了端点 —— 把数字打出来比断言更有用，因为断言炸了也没人看得见。 */
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
     *
     * ⓘ UVC 调试档（CONFIG_AIO_DEBUG_CDC=y ⇒ AIO_HAS_AUDIO=0）下整个音频功能不编译，
     *   本段连同下面那条 usb_pad_enable 证据日志一起消失 —— 那一档下没有人配
     *   G26/G27，也就没有那次误伤。**但 route_fsls_phy0_to_otg() 与
     *   otg_fsls_pads_repair() 一个都不要跟着去掉**：前者是 USB-C 能枚举的前提
     *   （与音频无关），后者是幂等的，留着零成本，且日后有人在调试档下手工配
     *   那两个脚时它仍是唯一的救命稻草。
     */
#if AIO_HAS_AUDIO
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
#endif /* AIO_HAS_AUDIO */

    tinyusb_config_t tusb_cfg = TINYUSB_CONFIG_FULL_SPEED(NULL, NULL);
    tusb_cfg.descriptor.device = &aio_desc_device;
    tusb_cfg.descriptor.full_speed_config = aio_desc_configuration;
    tusb_cfg.descriptor.string = aio_string_desc_arr;
    tusb_cfg.descriptor.string_count = aio_string_desc_count;
    ESP_ERROR_CHECK(tinyusb_driver_install(&tusb_cfg));
#if AIO_HAS_AUDIO
    ESP_LOGI(TAG, "tinyusb installed (GUD + HID + UAC1 + UVC)");
#else
    ESP_LOGI(TAG, "tinyusb installed (GUD + HID + UVC；UVC 调试档，无音频)");
#endif

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
     * `idf.py monitor` 即可看。代价是让出 GUD 的 IN 端点（GUD 不用它）
     * **并整体关掉音频**（0x83 要给 CDC 通知），4 条可用 IN 端点用满，
     * 而 0x84 原封不动留给 UVC（端点表与依据见 usb_descriptors.h）。
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
     * 摄像头：传感器探测（Task7）+ CSI/ISP 取流管线（Task8）。
     *
     * 排在这里而不是更早：它的结论只能从日志看，而开 CDC 调试档时日志要等
     * tinyusb_cdcacm_init() + tinyusb_console_init() 之后才有出口。放在 kbd/touch
     * 旁边，「三个可选外设各自探测」在代码上也读成一件事。
     *
     * 与键盘/触摸/音频同一处置原则：失败只降级、不拦启动 —— 摄像头探不到时
     * UVC 接口照样枚举，只是一帧都发不出来（host 侧 = 有 /dev/videoN 但取不到流，
     * 设备侧看 uvc/camera 两条自检行就知道断在哪），显示/键盘/触摸/音频四项能力
     * 一概不受影响。camera_sensor_probe() 失败时会自己把摄像头电源关掉，
     * 这里不用再管。
     */
    err = camera_sensor_probe();
    if (err != ESP_OK)
        ESP_LOGW(TAG, "摄像头传感器不可用(%s)，继续启动；UVC 将出不了图",
                 esp_err_to_name(err));
    /* 成功失败都打一遍快照：成功时它是「SCCB 通、PID 对」的正面证据，
     * 失败时它是唯一能把 NAK / PID 不符 / 组件内部失败区分开的东西。 */
    camera_sensor_report();

    if (err == ESP_OK) {
        /* CSI 控制器 + ISP + 帧缓冲。**只建对象，不开数据流** ——
         * CSI 一取流每秒就往 PSRAM 写 55 MB，与 DPI 面板刷新抢带宽，
         * 所以启停是单独一对函数，由 uvc_stream.c 的帧泵按 host 选中的
         * alt 0/1 调用：没人打开摄像头时这条链路一点带宽都不占。 */
        err = camera_csi_init();
        if (err != ESP_OK)
            ESP_LOGW(TAG, "CSI/ISP 起不来(%s)，继续启动；UVC 将出不了图",
                     esp_err_to_name(err));
        camera_csi_report();
    }

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
#if AIO_HAS_AUDIO
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
#endif

    /*
     * UVC 帧泵。必须排在 tinyusb_driver_install() 之后：任务一起来就会调
     * tud_video_*。与键盘/触摸/音频同一处置原则：失败只降级、不拦启动 ——
     * 摄像头挂了不该拖垮显示，何况本阶段的「摄像头」只是 flash 里一张静态图。
     * **两档都要有**：UVC 调试档存在的理由正是「一边跑摄像头一边看日志」。
     */
    err = uvc_stream_start();
    if (err != ESP_OK)
        ESP_LOGW(TAG, "摄像头不可用(%s)，继续启动", esp_err_to_name(err));

    bool fifo_logged = false;
    while (1) {
        vTaskDelay(pdMS_TO_TICKS(10000));

        /* FIFO 实测必须等 host 完成 SET_CONFIGURATION：端点是那时才 open、
         * FIFO 是那时才分配的。挂载后打一次，把静态验算变成现场数字。 */
        if (!fifo_logged && tud_mounted()) {
            log_usb_fifo_usage();
            fifo_logged = true;
        }

        /*
         * UVC 自检快照**两档都复读**，与上面那次性的 FIFO 快照、与
         * codec_audio_report() 都不同：那两者打的是静态事实（分配与初始化结果），
         * 而这里的计数器随 host 开/关摄像头逐拍变化 —— 「host 有没有真的在取流」
         * 「帧有没有发完」只能从它随时间的增量看出来，这是 P4 Task5 判定点在
         * 设备侧唯一的证据。默认档没有 CDC，这几行走 UART0(G37/G38)。
         *
         * camera_csi_report() 从 Task9 起一起**两档都复读**：它后半截那几个计数器
         * （帧 / 抢缓冲 / 丢弃 / 取帧超时 / 帧长不符）现在同样随取流逐拍变化，
         * 而且是 UVC 那几行往上游追责的第一站 —— 「host 没画面」到底是 CSI 压根
         * 没数据，还是数据来了但缩放/编码/USB 断了，全看这一行。
         */
        if (fifo_logged) {
            uvc_stream_report();
            camera_csi_report();
        }

#if CONFIG_AIO_DEBUG_CDC
        /*
         * 只有开了 CDC 日志串口才**复读**，理由是 CDC 独有的一个性质：
         * 它的 TX 环形缓冲只有几百字节，且要等 host 打开 ttyACM 才开始流 ——
         * 上面那一次在用户敲下 `idf.py monitor` 之前早被冲掉了，不复读等于没打。
         * UART0 控制台没有这个问题（字节直接出去、终端有回滚），所以默认档不复读。
         *
         * 复读的是 FIFO 快照而不是音频自检 —— 本档下音频整体不编译（0x83 让给了
         * CDC 通知）。
         * ⓘ 复读它**不是**为了看 alt 切换：EP4 IN 那一行在 SET_CONFIGURATION 时
         *   就定下来了，开关摄像头不会让它出现/消失（见 log_usb_fifo_usage() 的 ⚠️）。
         *   摄像头开没开看上面那条 uvc_stream_report() 的 streaming= 字段。
         */
        if (fifo_logged)
            log_usb_fifo_usage();

        /* 传感器探测快照同理：它是**开机一次性的静态事实**，上面那一遍打在
         * tinyusb_console_init() 之后没多久，早被 CDC 的 TX 环形缓冲冲掉了。
         * 默认档不复读 —— 那一档日志走 UART0，终端有回滚。
         * ⓘ camera_csi_report() 已经挪到上面无条件复读，这里不再重复。 */
        camera_sensor_report();
#endif
    }
}
