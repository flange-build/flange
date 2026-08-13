/*
 * M5Stack Tab5 显示 HAL。面板原生 720x1280 竖屏，MIPI-DSI 2 lane @ 1Gbps。
 * DSI/DPI 参数复刻自 esp-bsp bsp/m5stack_tab5/src/bsp_display.c（Apache-2.0）。
 */
#include "display_dsi.h"
#include "tab5_pins.h"
#include "board_power.h"
#include "standby_screen.h"
#include "gud_device.h"        /* gud_device_has_frame()：动画的停止条件 */
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
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
 * **已实机标定（M5Stack Tab5 + ILI9881C 批次）：1 正确**（当时的判据是四象限
 * 自检图的红色象限横持时落在左上角，与 GUD 坐标系一致）。
 * 注意「铺满全屏」验不出方向 —— 两个分支都产生 (0,0) 起 720×1280，差别只在
 * 内容转了 180°，判据必须是内容的落角。
 * 自检图已换成待机画面（display_standby_screen），**现在的判据是文字方向**：
 * 横持时 "NO SIGNAL" 正着可读即正确，上下颠倒即取值反了 —— 比色块更灵敏，
 * 文字方向一眼可辨，色块要对照记忆。与 firmware/README.md 一致。
 * （标定当时另放了一个 64×64 黄块辅助定位，=1 落在面板 (64,1024)、=0 落在
 *  (528,128)；该临时黄块已随自检图精简一并删除，用当前固件复现不出来。）
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
 * 等待点动画：副标题末尾的 . / .. / ... 循环，500ms 一步。
 *
 * 只重画点所在的 48×32 那一小块（3 KB），不重画 460 KB 整屏 —— 整屏搬运既
 * 浪费，也可能挤占 USB 收帧的时序。display_blit() 的输入是紧凑排列的 w×h，
 * 所以这里给的就是一个 48×32 的紧凑小缓冲，x/y 只决定落点。
 *
 * host 一送上第一帧就永久停止并退出：待机画面盖在 host 内容上是硬伤，
 * 而 GUD 是脏矩形刷新的，被我们盖掉的那一小块 host 未必会再画一次。
 */
static void standby_dots_task(void *arg)
{
    (void)arg;
    const size_t patch_bytes =
        (size_t)STANDBY_DOTS_W * STANDBY_DOTS_H * sizeof(uint16_t);
    uint16_t *patch = heap_caps_malloc(patch_bytes,
                                       MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    if (!patch) {
        ESP_LOGW(TAG, "等待点缓冲分配失败(%u 字节)，待机画面无动画",
                 (unsigned)patch_bytes);
        vTaskDelete(NULL);
        return;
    }

    for (int phase = 0; !gud_device_has_frame();
         phase = (phase + 1) % STANDBY_DOTS_PHASES) {
        standby_render_dots(patch, phase);
        /* 渲染期间 host 可能已经上来了，落笔前再看一眼 */
        if (gud_device_has_frame())
            break;
        display_blit(STANDBY_DOTS_X, STANDBY_DOTS_Y,
                     STANDBY_DOTS_W, STANDBY_DOTS_H, patch);
        vTaskDelay(pdMS_TO_TICKS(500));
    }

    heap_caps_free(patch);
    ESP_LOGI(TAG, "待机画面停止绘制，屏幕交给 host");
    vTaskDelete(NULL);   /* 用完即退，不空转常驻 */
}

/*
 * 待机画面（"NO SIGNAL" OSD）。host 没送帧时屏上显示它，收到第一帧后
 * 由 host 内容整幅覆盖、动画任务随之退出。
 *
 * 刻意走 display_blit()，因此顺带验证面板时序、颜色通道，以及 PPA 的缩放/
 * 旋转坐标映射 —— 三者任一错都在屏上直接看出来。它取代了此前的四象限自检图，
 * 而且**验方向比色块更灵敏**：文字上下颠倒或镜像一眼可辨，色块得对照记忆。
 *
 * 整幅 640×360×2 = 460KB 放 PSRAM（内部 DRAM 余量不够），blit 完即释放；
 * 之后常驻的只有动画任务里那 3 KB。
 */
void display_standby_screen(void)
{
    const size_t px = (size_t)GUD_W * GUD_H;
    uint16_t *buf = heap_caps_malloc(px * sizeof(uint16_t),
                                     MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    if (!buf) {
        /* 待机画面挂了不该挡住正常启动（host 的帧照样能上屏），报一声就走 */
        ESP_LOGE(TAG, "待机画面分配失败(%u KB)，跳过",
                 (unsigned)(px * sizeof(uint16_t) / 1024));
        return;
    }

    standby_render(buf);
    display_blit(0, 0, GUD_W, GUD_H, buf);

    /* PPA_TRANS_MODE_BLOCKING 保证搬运已完成，可以安全释放 */
    heap_caps_free(buf);

    if (xTaskCreate(standby_dots_task, "standby", 3072, NULL, 2, NULL) != pdPASS)
        ESP_LOGW(TAG, "等待点动画任务创建失败，待机画面为静态");
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
                  "两者都为 0 多半是上电时序不足(见 board_power_init 的稳定延时)，"
                  "都为 1 说明地址排他性假设不成立、需改读控制器 ID 寄存器",
             st7123, gt911);
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
        /*
         * 元素数 = **并发提交者数**（只用阻塞模式，每个提交者最多占 1 个）：
         *   ① TinyUSB 任务（GUD 收帧）
         *   ② 待机画面的等待点动画任务（收到第一帧后退出）
         *   ③ 音频数据泵任务（仅 CONFIG_TAB5_AUDIO_PANEL，画状态面板与电平条）
         * 池子空时 ppa_do_scale_rotate_mirror() 不等待、直接返回 ESP_FAIL
         * （ppa_srm.c "exceed maximum pending transactions"），那一次 blit 就丢了；
         * 落在 GUD 侧就是 host 的一块脏矩形永远不上屏（脏矩形不会自动重发）。
         * 窗口很窄，但代价不对称，故按提交者数量给足。
         * 退出/关闭后多出来的元素闲置，几百字节内部 RAM，不值得回收。
         *
         * ⓘ **多任务并发提交不需要额外互斥，已核实**：事务对象取自
         * ppa_client->trans_elm_ptr_queue 这个 FreeRTOS 队列（队列本身线程安全），
         * 每个事务自带独立的描述符存储，提交路径上没有共享可变状态。也就是说
         * 这个数**只**决定"同时在飞的事务上限"，不决定并发安全 —— 它等于并发
         * 提交者数即可，不必再乘系数，也不必在 display_blit() 外面加锁。
         * （CONFIG_TAB5_AUDIO_PANEL 未定义时 #if 求值为 0，两种配置下都成立。）
         */
#if CONFIG_TAB5_AUDIO_PANEL
        .max_pending_trans_num = 3,
#else
        .max_pending_trans_num = 2,
#endif
    };
    ESP_RETURN_ON_ERROR(ppa_register_client(&ppa_cfg, &s_ppa), TAG, "ppa client");

    /* 背光在此点亮，而不是 board_power_init() 里：面板 init 序列 195 条命令要跑
     * 几十到上百毫秒，期间点亮只会在开机时闪一下白屏/杂讯。不变式是
     * 「背光亮 ⟺ 面板正在输出有效视频」，属显示域，故由本函数在全部初始化
     * 成功之后负责，不交给 app_main 编排。此刻帧缓冲已清零，屏上是纯黑。 */
    board_backlight(true);

    ESP_LOGI(TAG, "panel %s %dx%d ready, fb=%p",
             kind == PANEL_ST7123 ? "ST7123" : "ILI9881C", PANEL_W, PANEL_H, s_fb);
    if (kind == PANEL_ST7123)
        ESP_LOGW(TAG, "ST7123 路径未经实机验证（开发用机是 ILI9881C 批次，"
                      "面板 ID 实测 0x98/0x81/0x5c）；若显示异常请优先怀疑本路径，"
                      "并注意上游 init 数据有两条 data_size 多算 1 字节");
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
