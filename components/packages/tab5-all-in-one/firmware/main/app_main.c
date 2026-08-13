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
#include "hal/usb_wrap_ll.h"   /* usb_wrap_ll_phy_select：把内部 FSLS PHY 0 判给 OTG1.1 */

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

    display_test_pattern();

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

    ESP_ERROR_CHECK(kbd_start());

    ESP_ERROR_CHECK(touch_start());

    while (1) vTaskDelay(pdMS_TO_TICKS(1000));
}
