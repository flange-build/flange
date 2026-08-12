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
#include "panel_init_data.h"   /* 须在上面两个面板头之后：依赖它们定义的元素类型 */
#include "driver/ppa.h"
#include "esp_check.h"
#include "esp_cache.h"
#include "esp_heap_caps.h"
#include "esp_log.h"
#include <stdint.h>
#include <string.h>

static const char *TAG = "disp";

#define PANEL_FB_BYTES ((size_t)PANEL_W * PANEL_H * sizeof(uint16_t))

/*
 * 旋转方向：1 = 90° CCW，0 = 270° CCW。两者相差 180°。
 * **已实机标定（M5Stack Tab5 + ILI9881C 批次）：1 正确** ——
 * 横持时红色象限落在左上角，与 GUD 坐标系一致。
 * 面板坐标落点：=1 时整帧 (0,0) 起 720×1280、64×64 黄块在 (64,1024)；
 *              =0 时整帧同样 (0,0)，黄块在 (528,128)。
 * 注意「铺满全屏」验不出方向 —— 两个分支都产生 (0,0) 起 720×1280，
 * 差别只在内容转了 180°。判据是红色象限的落角。
 */
#define DISPLAY_ROT_CCW90 1

static esp_ldo_channel_handle_t s_ldo;
static ppa_client_handle_t s_ppa;
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

/*
 * 面板自检。刻意走 display_blit()，因此同时验证面板时序、颜色通道，
 * 以及 PPA 的缩放/旋转坐标映射——三者任一错都会在屏上直接看出来。
 * 测试图 640×360×2 = 460KB 放 PSRAM（内部 DRAM 余量不够），用完即释放：
 * 这是开机期一次性自检，不该常驻。
 *
 * 保留它还有第二个用途：它是「显示链路还活着」的基准信号。host 的 GUD 帧
 * 一送上来就会覆盖它，屏幕从四象限图变成 host 画面，这个变化本身即是
 * GUD 打通的证据；若开机就黑屏，则可区分「显示坏了」与「GUD 没送帧」。
 */
void display_test_pattern(void)
{
    const size_t probe_px = (size_t)GUD_W * GUD_H;
    uint16_t *probe = heap_caps_malloc(probe_px * sizeof(uint16_t),
                                       MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    if (!probe) {
        /* 自检失败不该挡住正常启动，报一声就走 */
        ESP_LOGE(TAG, "自检图分配失败(%u KB)，跳过自检",
                 (unsigned)(probe_px * sizeof(uint16_t) / 1024));
        return;
    }

    /* 四象限用于辨认方向，正中 40×40 黑方块用于确认居中与无裁切 */
    for (int y = 0; y < GUD_H; y++)
        for (int x = 0; x < GUD_W; x++)
            probe[y * GUD_W + x] = (y < GUD_H / 2)
                ? (x < GUD_W / 2 ? 0xF800 : 0x07E0)    /* 上：左红 右绿 */
                : (x < GUD_W / 2 ? 0x001F : 0xFFFF);   /* 下：左蓝 右白 */

    const int cx = GUD_W / 2, cy = GUD_H / 2, half = 20;   /* 40×40 */
    for (int y = cy - half; y < cy + half; y++)
        for (int x = cx - half; x < cx + half; x++)
            probe[y * GUD_W + x] = 0x0000;

    display_blit(0, 0, GUD_W, GUD_H, probe);

    /* PPA_TRANS_MODE_BLOCKING 保证搬运已完成，可以安全释放 */
    heap_caps_free(probe);
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
            .init_cmds      = disp_init_data_st7123,
            .init_cmds_size = sizeof(disp_init_data_st7123) / sizeof(disp_init_data_st7123[0]),
            .mipi_config = { .dsi_bus = s_dsi_bus, .dpi_config = &dpi_cfg },
        };
        panel_cfg.vendor_config = &vendor_st7123;
        ESP_RETURN_ON_ERROR(esp_lcd_new_panel_st7123(s_io, &panel_cfg, &s_panel),
                            TAG, "new panel st7123");
    } else {
        ili9881c_vendor_config_t vendor_ili9881c = {
            .init_cmds      = disp_init_data_ili9881c,
            .init_cmds_size = sizeof(disp_init_data_ili9881c) / sizeof(disp_init_data_ili9881c[0]),
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

    ppa_client_config_t ppa_cfg = {
        .oper_type = PPA_OPERATION_SRM,
        .max_pending_trans_num = 1,   /* 只用阻塞模式，1 即可 */
    };
    ESP_RETURN_ON_ERROR(ppa_register_client(&ppa_cfg, &s_ppa), TAG, "ppa client");

    ESP_LOGI(TAG, "panel %s %dx%d ready, fb=%p",
             kind == PANEL_ST7123 ? "ST7123" : "ILI9881C", PANEL_W, PANEL_H, s_fb);
    if (kind == PANEL_ST7123)
        ESP_LOGW(TAG, "ST7123 路径未经实机验证（本项目实机为 ILI9881C 批次，"
                      "i2cscan 见 0x14 无 0x55）；若显示异常请优先怀疑本路径");
    return ESP_OK;
}

/*
 * 把 GUD 坐标系(640×360 横向)的一块 RGB565 送上面板(720×1280 竖向)。
 * PPA 的 SRM 引擎在一次操作里同时完成 2× 缩放与 90° 旋转，无需两遍搬运。
 * 输入输出的 cache 同步由 PPA 驱动自己做(ppa_srm.c:254/:260)，此处不用管。
 * 注意 PPA 的 rotation_angle 是逆时针(CCW)。
 *
 * 输入契约：pixels 是紧凑排列的 w×h 个 RGB565（stride = w，无 padding），
 * 亦即 gud_device.c 收帧后交过来的样子——脏矩形数据从缓冲偏移 0 起连续存放。
 * x/y 只用于算输出落点，不参与输入寻址。整帧 (0,0,640,360) 时紧凑解读与
 * 「整帧基址 + 偏移」解读恰好重合，所以只有非整帧的脏矩形能区分二者。
 */
void display_blit(int x, int y, int w, int h, const void *pixels)
{
    /* 旋转后输出块的尺寸：宽高互换再各乘 2 */
    const uint32_t out_w = (uint32_t)h * GUD_SCALE;
    const uint32_t out_h = (uint32_t)w * GUD_SCALE;

#if DISPLAY_ROT_CCW90
    const uint32_t out_x = (uint32_t)y * GUD_SCALE;
    const uint32_t out_y = (uint32_t)(PANEL_H - (x + w) * GUD_SCALE);
    const ppa_srm_rotation_angle_t rot = PPA_SRM_ROTATION_ANGLE_90;
#else
    const uint32_t out_x = (uint32_t)(PANEL_W - (y + h) * GUD_SCALE);
    const uint32_t out_y = (uint32_t)x * GUD_SCALE;
    const ppa_srm_rotation_angle_t rot = PPA_SRM_ROTATION_ANGLE_270;
#endif

    ppa_srm_oper_config_t op = {
        .in = {
            .buffer = pixels,
            .pic_w = (uint32_t)w,
            .pic_h = (uint32_t)h,
            .block_w = (uint32_t)w,
            .block_h = (uint32_t)h,
            .block_offset_x = 0,
            .block_offset_y = 0,
            .srm_cm = PPA_SRM_COLOR_MODE_RGB565,
        },
        .out = {
            .buffer = s_fb,
            .buffer_size = PANEL_FB_BYTES,
            .pic_w = PANEL_W,
            .pic_h = PANEL_H,
            .block_offset_x = out_x,
            .block_offset_y = out_y,
            .srm_cm = PPA_SRM_COLOR_MODE_RGB565,
        },
        .rotation_angle = rot,
        .scale_x = (float)GUD_SCALE,
        .scale_y = (float)GUD_SCALE,
        .mirror_x = false,
        .mirror_y = false,
        .byte_swap = false,
        .mode = PPA_TRANS_MODE_BLOCKING,
    };

    esp_err_t err = ppa_do_scale_rotate_mirror(s_ppa, &op);
    if (err != ESP_OK)
        ESP_LOGW(TAG, "ppa srm 失败 %s: %dx%d @(%d,%d) → (%u,%u) %ux%u",
                 esp_err_to_name(err), w, h, x, y,
                 (unsigned)out_x, (unsigned)out_y, (unsigned)out_w, (unsigned)out_h);
}
