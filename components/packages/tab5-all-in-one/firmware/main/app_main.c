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
#include "hal/usb_wrap_ll.h"   /* usb_wrap_ll_phy_select：把内部 FSLS PHY 0 判给 OTG1.1 */
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
    ESP_LOGI(TAG, "内部 FSLS PHY 0 已划给 OTG1.1（USB-C 从 USB-Serial/JTAG 收回）");
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

    tinyusb_config_t tusb_cfg = TINYUSB_CONFIG_FULL_SPEED(NULL, NULL);
    tusb_cfg.descriptor.device = &aio_desc_device;
    tusb_cfg.descriptor.full_speed_config = aio_desc_configuration;
    tusb_cfg.descriptor.string = aio_string_desc_arr;
    tusb_cfg.descriptor.string_count = aio_string_desc_count;
    ESP_ERROR_CHECK(tinyusb_driver_install(&tusb_cfg));
    ESP_LOGI(TAG, "tinyusb installed (GUD only)");

#if CONFIG_TINYUSB_CDC_ENABLED
    /*
     * 可选的 USB CDC 调试串口（默认关闭，开关在 sdkconfig.defaults 末尾）。
     *
     * 这块板现场没有可用串口：USB-Serial/JTAG 被关掉了（TinyUSB 要占那条 FSLS PHY），
     * UART0 只在 M5-Bus 排针上。开启本段后 ESP_LOG* 直接从 USB-C 出来，
     * `idf.py monitor` 即可看，代价是把 4 条可用 IN 端点用满（见 usb_descriptors.h）。
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
     * UAC1 全双工音频。与键盘/触摸同一处置原则：失败只降级、不拦启动。
     * 描述符是静态的，所以即便这里失败，host 侧照样枚举出声卡，只是收发到静音 ——
     * 而显示(GUD)才是这个产品的核心形态，不该被一颗 codec 拖垮。
     *
     * 必须排在 tinyusb_driver_install() 之后：数据泵任务一起来就会调 tud_audio_*。
     */
    err = codec_audio_start();
    if (err != ESP_OK)
        ESP_LOGW(TAG, "音频不可用(%s)，继续启动", esp_err_to_name(err));

    while (1) vTaskDelay(pdMS_TO_TICKS(1000));
}
