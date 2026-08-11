/*
 * M5Stack Tab5 显示 HAL。面板原生 720x1280 竖屏，MIPI-DSI 2 lane @ 1Gbps。
 * DSI/DPI 参数复刻自 esp-bsp bsp/m5stack_tab5/src/bsp_display.c（Apache-2.0）。
 * Tab5 随批次装 ILI9881C 或 ST7123 两种面板，两条路径都编进固件，
 * 由 panel_detect() 在运行时按内部 I2C 上的地址区分。
 */
#include "display_dsi.h"
#include "tab5_pins.h"
#include "board_power.h"
#include "esp_ldo_regulator.h"
#include "esp_lcd_mipi_dsi.h"
#include "esp_lcd_panel_dev.h"
#include "esp_lcd_panel_ops.h"
#include "esp_lcd_ili9881c.h"
#include "esp_lcd_st7123.h"
#include "esp_check.h"
#include "esp_log.h"
#include <string.h>

static const char *TAG = "disp";

static esp_ldo_channel_handle_t s_ldo;
static esp_lcd_dsi_bus_handle_t s_dsi_bus;
static esp_lcd_panel_io_handle_t s_io;
static esp_lcd_panel_handle_t s_panel;
static uint16_t *s_fb;      /* DPI 帧缓冲，720x1280 RGB565，由驱动分配在 PSRAM */

uint16_t *display_frame_buffer(void) { return s_fb; }

/* 面板/触摸控制器随 Tab5 批次而异，用内部 I2C 上的地址区分：
 *   0x55 ⇒ ST7123（显示触控一体）
 *   0x14 ⇒ GT911 触摸，面板为 ILI9881C
 * 两条初始化路径都编进固件，探到哪个走哪个。 */
typedef enum { PANEL_ILI9881C, PANEL_ST7123 } panel_kind_t;

static panel_kind_t panel_detect(void)
{
    const bool st7123 = (i2c_master_probe(board_i2c_bus(), 0x55, 100) == ESP_OK);
    const bool gt911  = (i2c_master_probe(board_i2c_bus(), 0x14, 100) == ESP_OK);

    if (st7123 && !gt911)
        return PANEL_ST7123;
    if (gt911 && !st7123)
        return PANEL_ILI9881C;

    /* 两个都探到或都没探到：探测法失效。回落到 ILI9881C 只是为了能继续启动，
     * 若实机是 ST7123 批次会表现为时序错乱的花屏 —— 所以必须大声报出来，
     * 否则这个失败模式没有任何外部症状可循。 */
    ESP_LOGE(TAG, "面板探测失败(0x55=%d 0x14=%d)，回落 ILI9881C；"
                  "若屏幕花屏请核对 i2cscan 日志", st7123, gt911);
    return PANEL_ILI9881C;
}

esp_err_t display_init(void)
{
    /* MIPI DSI PHY 供电：内部 LDO_VO3 @ 2.5V。不做这步 DSI 停在 "No Power" 态。 */
    esp_ldo_channel_config_t ldo_cfg = {
        .chan_id = DSI_PHY_LDO_CHAN,
        .voltage_mv = DSI_PHY_LDO_MV,
    };
    ESP_RETURN_ON_ERROR(esp_ldo_acquire_channel(&ldo_cfg, &s_ldo), TAG, "dsi phy ldo");

    esp_lcd_dsi_bus_config_t bus_cfg = {
        .bus_id = 0,
        .num_data_lanes = DSI_LANE_NUM,
        .phy_clk_src = MIPI_DSI_PHY_CLK_SRC_DEFAULT,
        .lane_bit_rate_mbps = DSI_LANE_MBPS,
    };
    ESP_RETURN_ON_ERROR(esp_lcd_new_dsi_bus(&bus_cfg, &s_dsi_bus), TAG, "dsi bus");

    esp_lcd_dbi_io_config_t dbi_cfg = {
        .virtual_channel = 0,
        .lcd_cmd_bits = 8,
        .lcd_param_bits = 8,
    };
    ESP_RETURN_ON_ERROR(esp_lcd_new_panel_io_dbi(s_dsi_bus, &dbi_cfg, &s_io), TAG, "dbi io");

    /*
     * DPI 配置。两种面板只有像素时钟与 porch 不同，其余一致。
     * IDF 6.0：用 in/out_color_format，没有 5.x 的 .pixel_format 字段。
     * 可以放栈上：两个面板驱动都只在 esp_lcd_new_panel_*() 内部把 dpi_config
     * 转交给 esp_lcd_new_panel_dpi()，后者按值拷走各字段，不留存指针；
     * panel_*_init() 阶段不再解引用它。
     */
    esp_lcd_dpi_panel_config_t dpi_cfg = {
        .virtual_channel = 0,
        .dpi_clk_src = MIPI_DSI_DPI_CLK_SRC_DEFAULT,
        .in_color_format = LCD_COLOR_FMT_RGB565,
        .out_color_format = LCD_COLOR_FMT_RGB565,
        .num_fbs = 1,
        .video_timing = { .h_size = PANEL_W, .v_size = PANEL_H },
    };

    const panel_kind_t kind = panel_detect();
    if (kind == PANEL_ST7123) {
        dpi_cfg.dpi_clock_freq_mhz = 70;
        dpi_cfg.video_timing.hsync_back_porch  = 40;
        dpi_cfg.video_timing.hsync_pulse_width = 2;
        dpi_cfg.video_timing.hsync_front_porch = 40;
        dpi_cfg.video_timing.vsync_back_porch  = 8;
        dpi_cfg.video_timing.vsync_pulse_width = 2;
        dpi_cfg.video_timing.vsync_front_porch = 220;
    } else {
        dpi_cfg.dpi_clock_freq_mhz = 60;
        dpi_cfg.video_timing.hsync_back_porch  = 140;
        dpi_cfg.video_timing.hsync_pulse_width = 40;
        dpi_cfg.video_timing.hsync_front_porch = 40;
        dpi_cfg.video_timing.vsync_back_porch  = 20;
        dpi_cfg.video_timing.vsync_pulse_width = 4;
        dpi_cfg.video_timing.vsync_front_porch = 20;
    }

    esp_lcd_panel_dev_config_t panel_cfg = {
        .reset_gpio_num = -1,          /* Tab5 面板无独立 reset 脚 */
        .rgb_ele_order = LCD_RGB_ELEMENT_ORDER_RGB,
        .bits_per_pixel = 16,
    };

    /*
     * 两个 vendor config 结构不同：ili9881c 的 mipi_config 有 lane_num 字段，
     * st7123 的没有（只有 dsi_bus + dpi_config）。照抄另一个会编译失败。
     */
    if (kind == PANEL_ST7123) {
        static st7123_vendor_config_t vendor_st7123;
        vendor_st7123 = (st7123_vendor_config_t){
            .mipi_config = { .dsi_bus = s_dsi_bus, .dpi_config = &dpi_cfg },
        };
        panel_cfg.vendor_config = &vendor_st7123;
        ESP_RETURN_ON_ERROR(esp_lcd_new_panel_st7123(s_io, &panel_cfg, &s_panel),
                            TAG, "new panel st7123");
    } else {
        static ili9881c_vendor_config_t vendor_ili9881c;
        vendor_ili9881c = (ili9881c_vendor_config_t){
            .mipi_config = { .dsi_bus = s_dsi_bus, .dpi_config = &dpi_cfg,
                             .lane_num = DSI_LANE_NUM },
        };
        panel_cfg.vendor_config = &vendor_ili9881c;
        ESP_RETURN_ON_ERROR(esp_lcd_new_panel_ili9881c(s_io, &panel_cfg, &s_panel),
                            TAG, "new panel ili9881c");
    }

    ESP_RETURN_ON_ERROR(esp_lcd_panel_reset(s_panel), TAG, "panel reset");
    ESP_RETURN_ON_ERROR(esp_lcd_panel_init(s_panel), TAG, "panel init");
    ESP_RETURN_ON_ERROR(esp_lcd_panel_disp_on_off(s_panel, true), TAG, "disp on");

    ESP_RETURN_ON_ERROR(esp_lcd_dpi_panel_get_frame_buffer(s_panel, 1, (void **)&s_fb),
                        TAG, "get fb");
    memset(s_fb, 0, (size_t)PANEL_W * PANEL_H * 2);

    ESP_LOGI(TAG, "panel %s %dx%d ready, fb=%p",
             kind == PANEL_ST7123 ? "ST7123" : "ILI9881C", PANEL_W, PANEL_H, s_fb);
    return ESP_OK;
}

void display_blit(int x, int y, int w, int h, const void *pixels)
{
    /* Task 3 用 PPA 实现（2× 缩放 + 90° 旋转写进 s_fb）。 */
    (void)x; (void)y; (void)w; (void)h; (void)pixels;
}
