/*
 * M5Stack Tab5 显示 HAL。面板原生 720x1280 竖屏，MIPI-DSI 2 lane @ 1Gbps。
 * DSI/DPI 参数复刻自 esp-bsp bsp/m5stack_tab5/src/bsp_display.c（Apache-2.0）。
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
#include "esp_cache.h"
#include "esp_log.h"
#include <stdint.h>
#include <string.h>

static const char *TAG = "disp";

#define PANEL_FB_BYTES ((size_t)PANEL_W * PANEL_H * sizeof(uint16_t))

static esp_ldo_channel_handle_t s_ldo;
static esp_lcd_dsi_bus_handle_t s_dsi_bus;
static esp_lcd_panel_io_handle_t s_io;
static esp_lcd_panel_handle_t s_panel;
static uint16_t *s_fb;      /* DPI 帧缓冲，720x1280 RGB565，由驱动分配在 PSRAM */

/*
 * 把 CPU 对帧缓冲的写入回写到 PSRAM。P4 的 DMA 不侦听 cache，DSI 桥直接从
 * PSRAM 取像素，CPU 改完 s_fb 不回写则末尾若干行可能还脏在 L2 里没落盘，
 * 表现为屏幕底部杂色带。
 *
 * 刻意不加 ESP_CACHE_MSYNC_FLAG_UNALIGNED：C2M 方向不带该 flag 时地址与
 * size 都必须按 cache line 对齐，否则 esp_cache_msync 返回 ESP_ERR_INVALID_ARG
 * 而 abort。整幅回写满足这两点——地址由 heap_caps_calloc 保证对齐（见 IDF
 * esp_lcd_panel_dpi.c:232 的断言注释），size = 1,843,200 = 128 × 14400，
 * 64B/128B 两种 line size 都整除。将来若有人拿它去刷部分行区间，我们希望
 * 那个断言大声炸掉，而不是被 UNALIGNED 静默放过。
 */
static void frame_buffer_flush(void)
{
    ESP_ERROR_CHECK(esp_cache_msync(s_fb, PANEL_FB_BYTES,
                                    ESP_CACHE_MSYNC_FLAG_DIR_C2M));
}

void display_test_pattern(void)
{
    /* 4 条竖直色条（面板竖屏坐标系，x 是短边 720） */
    const uint16_t bars[] = {0xF800, 0x07E0, 0x001F, 0xFFFF}; /* R G B W (RGB565) */
    const int n = sizeof(bars) / sizeof(bars[0]);
    for (int y = 0; y < PANEL_H; y++)
        for (int x = 0; x < PANEL_W; x++)
            s_fb[y * PANEL_W + x] = bars[(x * n) / PANEL_W];
    frame_buffer_flush();
}

/* 面板/触摸控制器随 Tab5 批次而异，用内部 I2C 上的地址区分：
 *   0x55 ⇒ ST7123（显示触控一体）
 *   0x14 ⇒ GT911 触摸，面板为 ILI9881C
 * 两条初始化路径都编进固件，探到哪个走哪个。 */
typedef enum { PANEL_ILI9881C, PANEL_ST7123 } panel_kind_t;

/* 两套 DPI 时序，均复刻自 esp-bsp bsp/m5stack_tab5/src/bsp_display.c（Apache-2.0）。
 * 用 designated initializer 按 panel_kind_t 索引，把枚举与表绑死。 */
typedef struct { uint32_t clk_mhz; esp_lcd_video_timing_t timing; } panel_timing_t;

static const panel_timing_t s_panel_timings[] = {
    [PANEL_ILI9881C] = { 60, { .h_size = PANEL_W, .v_size = PANEL_H,
                               .hsync_back_porch = 140, .hsync_pulse_width = 40, .hsync_front_porch = 40,
                               .vsync_back_porch = 20,  .vsync_pulse_width = 4,  .vsync_front_porch = 20 } },
    [PANEL_ST7123]   = { 70, { .h_size = PANEL_W, .v_size = PANEL_H,
                               .hsync_back_porch = 40,  .hsync_pulse_width = 2,  .hsync_front_porch = 40,
                               .vsync_back_porch = 8,   .vsync_pulse_width = 2,  .vsync_front_porch = 220 } },
};

static panel_kind_t panel_detect(void)
{
    const bool st7123 = (i2c_master_probe(board_i2c_bus(), ST7123_I2C_ADDR, 100) == ESP_OK);
    const bool gt911  = (i2c_master_probe(board_i2c_bus(), GT911_I2C_ADDR, 100) == ESP_OK);

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

/* 须在 board_power_init() 之后调用：panel_detect() 依赖内部 I2C 总线。 */
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
     * DPI 配置。两种面板只有像素时钟与 porch 不同（见 s_panel_timings），其余一致。
     * IDF 6.0：用 in/out_color_format，没有 5.x 的 .pixel_format 字段。
     * 可以放栈上：两个面板驱动都只在 esp_lcd_new_panel_*() 内部把 dpi_config
     * 转交给 esp_lcd_new_panel_dpi()，后者按值拷走各字段，不留存指针；
     * panel_*_init() 阶段不再解引用它。
     */
    const panel_kind_t kind = panel_detect();
    esp_lcd_dpi_panel_config_t dpi_cfg = {
        .virtual_channel = 0,
        .dpi_clk_src = MIPI_DSI_DPI_CLK_SRC_DEFAULT,
        .in_color_format = LCD_COLOR_FMT_RGB565,
        .out_color_format = LCD_COLOR_FMT_RGB565,
        .num_fbs = 1,
        .dpi_clock_freq_mhz = s_panel_timings[kind].clk_mhz,
        .video_timing = s_panel_timings[kind].timing,
    };

    esp_lcd_panel_dev_config_t panel_cfg = {
        .reset_gpio_num = -1,          /* Tab5 面板无独立 reset 脚 */
        .rgb_ele_order = LCD_RGB_ELEMENT_ORDER_RGB,
        .bits_per_pixel = 16,
    };

    /*
     * 两个 vendor config 结构不同：ili9881c 的 mipi_config 有 lane_num 字段，
     * st7123 的没有（只有 dsi_bus + dpi_config）。照抄另一个会编译失败。
     * 与 dpi_cfg 同理可以放栈上：两个驱动的私有结构体(ili9881c_panel_t /
     * st7123_panel_t)都只按值拷走 init_cmds / init_cmds_size / lane_num，
     * 不保存 vendor_config 指针本身。
     */
    if (kind == PANEL_ST7123) {
        st7123_vendor_config_t vendor_st7123 = {
            .mipi_config = { .dsi_bus = s_dsi_bus, .dpi_config = &dpi_cfg },
        };
        panel_cfg.vendor_config = &vendor_st7123;
        ESP_RETURN_ON_ERROR(esp_lcd_new_panel_st7123(s_io, &panel_cfg, &s_panel),
                            TAG, "new panel st7123");
    } else {
        ili9881c_vendor_config_t vendor_ili9881c = {
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
    memset(s_fb, 0, PANEL_FB_BYTES);
    frame_buffer_flush();

    ESP_LOGI(TAG, "panel %s %dx%d ready, fb=%p",
             kind == PANEL_ST7123 ? "ST7123" : "ILI9881C", PANEL_W, PANEL_H, s_fb);
    return ESP_OK;
}

void display_blit(int x, int y, int w, int h, const void *pixels)
{
    /* Task 3 用 PPA 实现（2× 缩放 + 90° 旋转写进 s_fb）。 */
    (void)x; (void)y; (void)w; (void)h; (void)pixels;
}
