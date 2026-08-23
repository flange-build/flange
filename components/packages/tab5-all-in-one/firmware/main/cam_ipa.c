/*
 * 官方 esp_ipa 的消费侧实现。设计意图、数据流与边界见 cam_ipa.h。
 *
 * 本文件的每一段分发逻辑都对应 esp_video/src/esp_video_isp_pipeline.c 里的一个
 * config_xxx() 函数；差异只有两处，且都写了理由（增益查表用线性扫描而非官方那个
 * 只在精确命中时才收敛的二分；曝光的 µs↔行 换算自己算而不走 V4L2 那层）。
 */
#include "cam_ipa.h"

#include "esp_check.h"
#include "esp_log.h"
#include "sdkconfig.h"
#include "tab5_pins.h"

#include "driver/isp_bf.h"
#include "driver/isp_ccm.h"
#include "driver/isp_color.h"
#include "driver/isp_demosaic.h"
#include "driver/isp_gamma.h"
#include "driver/isp_lsc.h"
#include "driver/isp_sharpen.h"

#include <inttypes.h>
#include <string.h>

static const char *TAG = "cam_ipa";

/*
 * ══ rev v1.0 硬件能力门 ═══════════════════════════════════════════════
 *
 * 与 esp_video 的 ESP_VIDEO_ISP_DEVICE_BLC / _LSC 逐条对应。取值依据是 IDF v6.0
 * 各子模块驱动里的版本门（都在各自 .c 文件的开头几十行）：
 *
 *   isp_blc.c:30   BLC   ESP_CHIP_REV_ABOVE(rev, 300)  ⇒ rev v1.0 **没有**
 *   isp_wbg.c:30   WBG   ESP_CHIP_REV_ABOVE(rev, 300)  ⇒ rev v1.0 **没有**
 *   isp_crop.c:30  crop  ESP_CHIP_REV_ABOVE(rev, 300)  ⇒ rev v1.0 **没有**
 *   isp_lsc.c:58   LSC   ESP_CHIP_REV_ABOVE(rev, 100)  ⇒ 该宏是 `(min)<=(rev)`
 *                                                        （soc/chip_revision.h:31）
 *                                                        100<=100 为真 ⇒ **有**
 *   isp_ccm.c      CCM   全文无版本门                    ⇒ **有**（只是 rev<3.0
 *                                                        的定点是 S2.10，上限 4.0）
 *
 * ⚠️ 这里写成常量 0/1 而不是运行期查 efuse：这是**编译目标**的属性
 *   （sdkconfig.defaults 里 CONFIG_ESP32P4_SELECTS_REV_LESS_V3=y 已经把整个固件
 *   钉死在 rev < 3.0 上，那两档是互斥的、不能运行时兼容），运行期再查一遍
 *   只会让「这段代码到底编不编」变成一个看两处才知道的问题。
 */
#define CAM_IPA_HAS_BLC   0    /* rev v1.0 无 ISP BLC，metadata 的 BLC 位直接忽略 */
#define CAM_IPA_HAS_WBG   0    /* rev v1.0 无 WBG，白平衡增益折进 CCM，见 config_ccm */
#define CAM_IPA_HAS_LSC   1

/*
 * 传感器名。**必须与官方标定文件顶层的那个键逐字符相同** ——
 * sc202cs_default.json 的结构是 { "version": 1, "SC202CS": { … } }，
 * 构建期生成的 esp_video_ipa_config.c 里那张索引表就是按这个字符串查的
 * （esp_ipa_pipeline_get_config() 用 strcmp）。
 *
 * ⓘ 不用 s_sensor->name：那是模式名（"MIPI_1lane_24Minput_RAW8_1280x720_30fps"），
 *   与 JSON 的键完全是两回事。查不到时 get_config() 返回 NULL，
 *   自检行会打「配置=没找到」，而不是安静地跑一个空 pipeline。
 */
#define CAM_IPA_SENSOR_NAME  "SC202CS"

static esp_ipa_pipeline_handle_t s_pipe;
static isp_proc_handle_t         s_isp;
static esp_cam_sensor_device_t  *s_sensor;

/* 送进 blob 的传感器状态。cur_* 三个字段由本文件在每次成功下发之后更新 ——
 * blob 的控制律是**增量式**的（它拿 cur 与算出来的目标比），喂陈旧的 cur
 * 会让它每拍都以为「还没到位」而持续加码，表现为曝光震荡。 */
static esp_ipa_sensor_t   s_info;
static esp_ipa_metadata_t s_md;

/* ── 传感器可调范围（开机查一次，之后只读）───────────────────────── */
static uint32_t        s_exp_min_lines, s_exp_max_lines;
static const uint32_t *s_gain_map;          /* ×1000 定点，升序 */
static uint32_t        s_gain_count;
static uint32_t        s_tline_ns;          /* 一行的时间，纳秒 */

/* 此刻硬件里的值，用来做「没变就不下发」的去抖（官方同款：esp_video 用
 * prev_exposure_val / prev_gain_index 做完全一样的事）。 */
static uint32_t s_cur_exp_lines;
static uint32_t s_cur_gain_idx;

/* ── 自检计数器 ─────────────────────────────────────────────────── */
#define STEP_NOT_RUN  INT32_MIN
static int32_t  s_st_cfg    = STEP_NOT_RUN;  /* esp_ipa_pipeline_get_config() */
static int32_t  s_st_create = STEP_NOT_RUN;  /* esp_ipa_pipeline_create() */
static int32_t  s_st_init   = STEP_NOT_RUN;  /* esp_ipa_pipeline_init() */
static int32_t  s_st_range  = STEP_NOT_RUN;  /* 曝光/增益可调范围查询 */
static int32_t  s_st_proc   = STEP_NOT_RUN;  /* 最近一次 process() 的返回值 */
static int32_t  s_st_exp    = STEP_NOT_RUN;  /* 最近一次曝光/增益下发的返回值 */
static uint32_t s_ticks;                     /* process() 累计调用次数 */
static uint32_t s_flags_seen;                /* 至今**见过**的 metadata flags 并集 */
static uint32_t s_flags_last;                /* 最近一拍的 metadata flags */
static uint32_t s_n_exp, s_n_gain, s_n_ccm, s_n_gamma, s_n_lsc;

/* LSC 的增益数组由驱动分配（273 格 × 4 通道），只在 metadata 给出 LSC 时填。 */
#if CAM_IPA_HAS_LSC
static esp_isp_lsc_gain_array_t s_lsc_gain;
static size_t  s_lsc_n;
static int32_t s_st_lsc = STEP_NOT_RUN;
static bool    s_lsc_ready;
static bool    s_lsc_enabled;
#endif

/* 各 ISP 子块的 enable 都有 FSM 门（重复调直接 ESP_ERR_INVALID_STATE），
 * 整个生命周期只能成功一次 —— 用这几个布尔记住「已经开过了」。 */
static bool s_bf_en, s_sharp_en, s_color_en, s_ccm_en, s_gamma_en;
static int32_t s_st_bf = STEP_NOT_RUN, s_st_sharp = STEP_NOT_RUN;
static int32_t s_st_color = STEP_NOT_RUN, s_st_ccm = STEP_NOT_RUN;
static int32_t s_st_gamma = STEP_NOT_RUN, s_st_dm = STEP_NOT_RUN;

/* ══════════════════════════════════════════════════════════════════
 *  ISP 侧的分发
 * ══════════════════════════════════════════════════════════════════ */

static void config_bf(const esp_ipa_metadata_t *md)
{
    if (!(md->flags & IPA_METADATA_FLAGS_BF))
        return;

    esp_isp_bf_config_t cfg = { .denoising_level = md->bf.level, .padding_mode =
                                ISP_BF_EDGE_PADDING_MODE_SRND_DATA, .padding_data = 0 };
    memcpy(cfg.bf_template, md->bf.matrix, sizeof cfg.bf_template);
    s_st_bf = esp_isp_bf_configure(s_isp, &cfg);
    if (s_st_bf == ESP_OK && !s_bf_en) {
        s_st_bf  = esp_isp_bf_enable(s_isp);
        s_bf_en  = (s_st_bf == ESP_OK);
    }
}

static void config_demosaic(const esp_ipa_metadata_t *md)
{
    if (!(md->flags & IPA_METADATA_FLAGS_DM))
        return;

    /* grad_ratio 是 2 整数位 + 4 小数位（soc_caps.h）⇒ 步长 1/16。
     * blob 给的是 float，这里做**四舍五入**而不是截断：1.05 截断成 1.0000
     * （−4.8%），四舍五入成 1.0625（+1.2%）。 */
    const float r  = md->demosaic.gradient_ratio;
    uint32_t    ip = (uint32_t)r;
    uint32_t    dp = (uint32_t)((r - (float)ip) * 16.0f + 0.5f);
    if (dp >= 16) { ip++; dp = 0; }        /* 舍入把小数部推满 ⇒ 进位 */

    const esp_isp_demosaic_config_t cfg = {
        .grad_ratio   = { .integer = ip, .decimal = dp },
        .padding_mode = ISP_DEMOSAIC_EDGE_PADDING_MODE_SRND_DATA,
        .padding_data = 0,
        .padding_line_tail_valid_start_pixel = 0,
        .padding_line_tail_valid_end_pixel   = 0,
    };
    /* ⚠️ 只 configure、**不要** esp_isp_demosaic_enable()：去马赛克已经被
     *   output = RGB565 隐式打开了（isp_ll_set_output_data_color_format()
     *   顺手置了 demosaic_en），而 enable 有 FSM 门 —— 调它会拿到
     *   ESP_ERR_INVALID_STATE，那个错误码会让人误以为参数根本没配上。 */
    s_st_dm = esp_isp_demosaic_configure(s_isp, &cfg);
}

static void config_sharpen(const esp_ipa_metadata_t *md)
{
    if (!(md->flags & IPA_METADATA_FLAGS_SH))
        return;

    /* 两个系数是 3 整数位 + 5 小数位（soc_caps.h）⇒ 步长 1/32，同样四舍五入。 */
    const float hc = md->sharpen.h_coeff, mc = md->sharpen.m_coeff;
    uint32_t hi = (uint32_t)hc, hd = (uint32_t)((hc - (float)hi) * 32.0f + 0.5f);
    uint32_t mi = (uint32_t)mc, md_ = (uint32_t)((mc - (float)mi) * 32.0f + 0.5f);
    if (hd >= 32) { hi++; hd  = 0; }
    if (md_ >= 32) { mi++; md_ = 0; }

    esp_isp_sharpen_config_t cfg = {
        .h_freq_coeff = { .integer = hi, .decimal = hd },
        .m_freq_coeff = { .integer = mi, .decimal = md_ },
        .h_thresh     = md->sharpen.h_thresh,
        .l_thresh     = md->sharpen.l_thresh,
        .padding_mode = ISP_SHARPEN_EDGE_PADDING_MODE_SRND_DATA,
        .padding_data = 0,
        .padding_line_tail_valid_start_pixel = 0,
        .padding_line_tail_valid_end_pixel   = 0,
        .flags = { .update_once_configured = 1 },
    };
    memcpy(cfg.sharpen_template, md->sharpen.matrix, sizeof cfg.sharpen_template);
    s_st_sharp = esp_isp_sharpen_configure(s_isp, &cfg);
    if (s_st_sharp == ESP_OK && !s_sharp_en) {
        s_st_sharp = esp_isp_sharpen_enable(s_isp);
        s_sharp_en = (s_st_sharp == ESP_OK);
    }
}

/*
 * 对比度 / 饱和度 / 色调 / 亮度共用**一次** Color configure —— 四个字段在同一个
 * 寄存器组里，分四次写会有三次是拿旧值覆盖新值。所以四个 flag 任意一位置起就
 * 重发整组，没置起的沿用此刻的值（s_color_* 记着）。
 *
 * ⓘ 128 就是 1.0×（1 整数位 + 7 小数位）；blob 给的 brightness/contrast/
 *   saturation/hue 就是这个 val 的原值，**直接写、不换算**。
 */
static uint8_t s_color_contrast = 128, s_color_saturation = 128;
static uint8_t s_color_hue, s_color_brightness;

static void config_color(const esp_ipa_metadata_t *md)
{
    const uint32_t any = IPA_METADATA_FLAGS_BR | IPA_METADATA_FLAGS_CN |
                         IPA_METADATA_FLAGS_ST | IPA_METADATA_FLAGS_HUE;
    if (!(md->flags & any))
        return;

    if (md->flags & IPA_METADATA_FLAGS_BR)  s_color_brightness = (uint8_t)md->brightness;
    if (md->flags & IPA_METADATA_FLAGS_CN)  s_color_contrast   = (uint8_t)md->contrast;
    if (md->flags & IPA_METADATA_FLAGS_ST)  s_color_saturation = (uint8_t)md->saturation;
    if (md->flags & IPA_METADATA_FLAGS_HUE) s_color_hue        = (uint8_t)md->hue;

    const esp_isp_color_config_t cfg = {
        .color_contrast   = { .val = s_color_contrast },
        .color_saturation = { .val = s_color_saturation },
        .color_hue        = s_color_hue,
        .color_brightness = s_color_brightness,
        .flags = { .update_once_configured = 1 },
    };
    s_st_color = esp_isp_color_configure(s_isp, &cfg);
    if (s_st_color == ESP_OK && !s_color_en) {
        /* ⓘ isp_core.c 那处 isp_ll_color_enable(true) 的 workaround（DIG-474）
         *   只在 **DVP** 输入时触发，我们是 CSI 输入 ⇒ 不触发，所以 color 块
         *   此刻确实停在 FSM 的 INIT 态。 */
        s_st_color = esp_isp_color_enable(s_isp);
        s_color_en = (s_st_color == ESP_OK);
    }
}

static void config_gamma(const esp_ipa_metadata_t *md)
{
    if (!(md->flags & IPA_METADATA_FLAGS_GAMMA))
        return;

    /* 三个通道各有独立的 flag 位（IPA_GAMMA_FLAGS_RED/GREEN/BLUE）——
     * 官方 SC202CS 标定每档只有一个 gamma_param、三通道同曲线，所以实际上三位
     * 总是一起置；但按位判断是 blob 的契约，不能假设它们同步。 */
    static const struct { uint32_t bit; color_component_t comp; } chans[3] = {
        { IPA_GAMMA_FLAGS_RED,   COLOR_COMPONENT_R },
        { IPA_GAMMA_FLAGS_GREEN, COLOR_COMPONENT_G },
        { IPA_GAMMA_FLAGS_BLUE,  COLOR_COMPONENT_B },
    };
    const esp_ipa_gamma_channel_t *src[3] = { &md->gamma.red, &md->gamma.green, &md->gamma.blue };

    for (int c = 0; c < 3; c++) {
        if (!(md->gamma.flags & chans[c].bit))
            continue;
        isp_gamma_curve_points_t pts = {0};
        for (int i = 0; i < ISP_GAMMA_CURVE_POINTS_NUM; i++) {
            pts.pt[i].x = src[c]->x[i];
            pts.pt[i].y = src[c]->y[i];
        }
        s_st_gamma = esp_isp_gamma_configure(s_isp, chans[c].comp, &pts);
        if (s_st_gamma != ESP_OK)
            return;
    }
    if (!s_gamma_en) {
        /* enable 有 FSM 门，整个生命周期只调一次。 */
        s_st_gamma = esp_isp_gamma_enable(s_isp);
        s_gamma_en = (s_st_gamma == ESP_OK);
    }
    s_n_gamma++;
}

/*
 * CCM。**本板白平衡的唯一施加点** —— rev v1.0 没有 WBG（CAM_IPA_HAS_WBG = 0），
 * 而 blob 的 AWB 结果是通过 IPA_METADATA_FLAGS_RG/BG 两个**通道增益**给出来的。
 *
 * ⚠️ 官方 esp_video 在有 WBG 的芯片上是把 red_gain/blue_gain 写进 WBG、CCM 只管
 *   色彩校正；没有 WBG 时**必须把增益右乘进 CCM 的对角线**：
 *       CCM' = CCM × diag(red_gain, 1, blue_gain)
 *   数学上与「先做通道增益再做 CCM」完全等价（矩阵乘法结合律），而这正是
 *   WBG 在管线里的位置（WBG 在 CCM 上游）。顺序**不能反**：先乘 CCM 再乘增益
 *   等于把增益作用在已经混过色的通道上，那是另一件事。
 *
 * ⚠️ rev < 3.0 的 CCM 定点是「符号 + 2 整数位 + 10 小数位」（hal/isp_ll.h:138-144）
 *   ⇒ 系数绝对值上限 4.0，超了 esp_isp_ccm_configure() 直接 ESP_ERR_INVALID_ARG。
 *   `.saturation = true` 让驱动在越界时饱和而不是整个拒绝 —— 失败等于**一点
 *   白平衡都没有**（画面整体发绿），比略微不准坏得多。
 */
static void config_ccm(const esp_ipa_metadata_t *md)
{
    const bool has_ccm = md->flags & IPA_METADATA_FLAGS_CCM;
    const bool has_rg  = md->flags & IPA_METADATA_FLAGS_RG;
    const bool has_bg  = md->flags & IPA_METADATA_FLAGS_BG;
    if (!has_ccm && !has_rg && !has_bg)
        return;

    /* 三者任意一个变了都要重算整个矩阵 ⇒ 三个输入都记在 static 里。
     * 初值：单位阵 + 增益 1.0（= 什么都不做），与 ISP 复位态一致。 */
    static float ccm[3][3] = { {1, 0, 0}, {0, 1, 0}, {0, 0, 1} };
    static float rg = 1.0f, bg = 1.0f;

    if (has_ccm) memcpy(ccm, md->ccm.matrix, sizeof ccm);
    if (has_rg)  rg = md->red_gain;
    if (has_bg)  bg = md->blue_gain;

#if CAM_IPA_HAS_WBG
#error "本板 rev v1.0 没有 WBG。真要支持 rev>=3.0 得另出一份固件（两档互斥），届时这里改成把 rg/bg 写进 WBG。"
#endif
    /* 右乘 diag(rg, 1, bg)：第 0 列 × rg，第 2 列 × bg，第 1 列不动。 */
    esp_isp_ccm_config_t cfg = {
        .saturation = true,
        .flags = { .update_once_configured = 1 },
    };
    for (int i = 0; i < 3; i++) {
        cfg.matrix[i][0] = ccm[i][0] * rg;
        cfg.matrix[i][1] = ccm[i][1];
        cfg.matrix[i][2] = ccm[i][2] * bg;
    }

    s_st_ccm = esp_isp_ccm_configure(s_isp, &cfg);
    if (s_st_ccm == ESP_OK && !s_ccm_en) {
        /* enable 有 FSM 门，只调一次；configure 本身没有 FSM/版本门，随时可调。 */
        s_st_ccm = esp_isp_ccm_enable(s_isp);
        s_ccm_en = (s_st_ccm == ESP_OK);
    }
    if (s_st_ccm == ESP_OK)
        s_n_ccm++;
}

#if CAM_IPA_HAS_LSC
static void config_lsc(const esp_ipa_metadata_t *md)
{
    if (!(md->flags & IPA_METADATA_FLAGS_LSC) || !s_lsc_ready)
        return;
    if (!md->lsc.enable)
        return;              /* blob 要求关掉 LSC：保持上一档，别写半张表 */

    /* ⚠️ 格数必须与驱动分配的一致。blob 给的 lsc_gain_array_size 来自标定文件的
     *   lsc_tbl_size（官方也是 1280×720 ⇒ 273），而驱动的格数由 ISP 的 h_res/v_res
     *   算出（(res−1)/2/32 + 2 ⇒ 21×13 = 273）。哪天换了传感器模式两者会分家，
     *   不比对的话表会被错位填进 LUT —— 现象是「暗角修正的位置整体偏了」，
     *   几乎不可能反查到这里。 */
    if (md->lsc.lsc_gain_array_size != s_lsc_n) {
        s_st_lsc = ESP_ERR_INVALID_SIZE;
        return;
    }
    memcpy(s_lsc_gain.gain_r,  md->lsc.gain_r,  s_lsc_n * sizeof(isp_lsc_gain_t));
    memcpy(s_lsc_gain.gain_gr, md->lsc.gain_gr, s_lsc_n * sizeof(isp_lsc_gain_t));
    memcpy(s_lsc_gain.gain_gb, md->lsc.gain_gb, s_lsc_n * sizeof(isp_lsc_gain_t));
    memcpy(s_lsc_gain.gain_b,  md->lsc.gain_b,  s_lsc_n * sizeof(isp_lsc_gain_t));

    const esp_isp_lsc_config_t cfg = { .gain_array = &s_lsc_gain };
    s_st_lsc = esp_isp_lsc_configure(s_isp, &cfg);
    if (s_st_lsc == ESP_OK && !s_lsc_enabled) {
        s_st_lsc = esp_isp_lsc_enable(s_isp);
        s_lsc_enabled = (s_st_lsc == ESP_OK);
    }
    if (s_st_lsc == ESP_OK)
        s_n_lsc++;
}
#endif  /* CAM_IPA_HAS_LSC */

/* ══════════════════════════════════════════════════════════════════
 *  传感器侧的分发：曝光 + 增益
 * ══════════════════════════════════════════════════════════════════ */

/*
 * blob 给的 gain 是**相对最小档的倍率**（esp_video 里 base_gain 取的就是增益
 * 菜单第 0 项）。SC202CS 的 sc202cs_abs_gain_val_map[] 是 ×1000 定点且
 * 第 0 项恰好 = 1000 ⇒ 目标定点值 = gain × 1000，直接在表里找。
 *
 * ⓘ **这里用线性扫描而不是照抄 esp_video 的二分**：那段二分只在**精确命中**
 *   某一档时才 break，命中不了就一直循环到 max_inter 耗尽、然后报
 *   "failed to search target gain" 并整个放弃这次增益下发。而 blob 给的是连续
 *   浮点倍率，精确命中是小概率事件 —— 也就是说那条路在多数拍上是失效的。
 *   取「不超过目标的最大一档」是这张升序表上唯一有物理意义的语义（宁可暗一点
 *   也不要过曝），表长不过百余项，每拍一次线性扫描的代价可以忽略。
 */
static uint32_t gain_to_index(float gain)
{
    if (!s_gain_map || s_gain_count == 0)
        return 0;
    const uint32_t want = (uint32_t)(gain * 1000.0f + 0.5f);
    uint32_t idx = 0;
    for (uint32_t i = 0; i < s_gain_count; i++) {
        if (s_gain_map[i] <= want)
            idx = i;
        else
            break;                 /* 表是升序的，后面只会更大 */
    }
    return idx;
}

static void config_sensor(esp_ipa_metadata_t *md)
{
    if (!s_sensor || s_st_range != ESP_OK) {
        /* 可调范围没查到 ⇒ 传感器停在模式表的默认曝光/增益上。把两位清掉，
         * 让自检行打出来的 flags 反映**实际生效**的那些，而不是 blob 想要的。 */
        md->flags &= ~(IPA_METADATA_FLAGS_ET | IPA_METADATA_FLAGS_GN);
        return;
    }

    uint32_t exp_lines = s_cur_exp_lines;
    uint32_t gain_idx  = s_cur_gain_idx;

    if (md->flags & IPA_METADATA_FLAGS_ET) {
        /* µs → 行。t_line 由模式表的 fps × vts 算出（与 sc202cs.c 的
         * EXPOSURE_V4L2_TO_SC202CS 同一条式子，只是我们用纳秒避免整数除法丢精度）。 */
        uint64_t lines = ((uint64_t)md->exposure * 1000u + s_tline_ns / 2) / s_tline_ns;
        if (lines < s_exp_min_lines) lines = s_exp_min_lines;
        if (lines > s_exp_max_lines) lines = s_exp_max_lines;
        exp_lines = (uint32_t)lines;
        if (exp_lines == s_cur_exp_lines)
            md->flags &= ~IPA_METADATA_FLAGS_ET;    /* 没变就别占 I2C 总线 */
    }

    if (md->flags & IPA_METADATA_FLAGS_GN) {
        gain_idx = gain_to_index(md->gain);
        if (gain_idx == s_cur_gain_idx)
            md->flags &= ~IPA_METADATA_FLAGS_GN;
    }

    const bool set_exp  = md->flags & IPA_METADATA_FLAGS_ET;
    const bool set_gain = md->flags & IPA_METADATA_FLAGS_GN;
    if (!set_exp && !set_gain)
        return;

    /*
     * ⚠️ 两者都要改时**必须一次性下发**（ESP_CAM_SENSOR_GROUP_EXP_GAIN）。
     * 分两次发的话，两次之间会漏出一帧「新曝光 + 旧增益」的画面 —— 亮度跳一下，
     * 而 blob 下一拍恰好会把这一帧的统计当成反馈，等于自己给自己注入扰动。
     * 官方 esp_video 在 sensor_attr.group 可用时走的也是这条路。
     *
     * ⓘ exposure_us 传 0 表示「用 exposure_val 这个原始寄存器值」（组件约定，
     *   esp_cam_sensor_types.h:466-470）。我们的控制量本来就换算到行域了，
     *   走 us 会让驱动再换算一次，白白多一次舍入。
     */
    if (set_exp && set_gain) {
        const esp_cam_sensor_gh_exp_gain_t v = {
            .exposure_us = 0, .exposure_val = exp_lines, .gain_index = gain_idx,
        };
        s_st_exp = esp_cam_sensor_set_para_value(s_sensor, ESP_CAM_SENSOR_GROUP_EXP_GAIN,
                                                 &v, sizeof v);
    } else if (set_exp) {
        s_st_exp = esp_cam_sensor_set_para_value(s_sensor, ESP_CAM_SENSOR_EXPOSURE_VAL,
                                                 &exp_lines, sizeof exp_lines);
    } else {
        s_st_exp = esp_cam_sensor_set_para_value(s_sensor, ESP_CAM_SENSOR_GAIN,
                                                 &gain_idx, sizeof gain_idx);
    }

    if (s_st_exp != ESP_OK) {
        ESP_LOGW(TAG, "曝光/增益下发失败(%s)", esp_err_to_name((esp_err_t)s_st_exp));
        return;
    }

    /* 下发成功了才更新「此刻是多少」—— 这两个数会在下一拍作为 cur 喂回 blob，
     * 写早了会让它以为已经到位而停止调整。 */
    if (set_exp) {
        s_cur_exp_lines   = exp_lines;
        s_info.cur_exposure = (uint32_t)(((uint64_t)exp_lines * s_tline_ns + 500) / 1000);
        s_n_exp++;
    }
    if (set_gain) {
        s_cur_gain_idx  = gain_idx;
        s_info.cur_gain = (float)s_gain_map[gain_idx] / 1000.0f;
        s_n_gain++;
    }
}

/* ══════════════════════════════════════════════════════════════════
 *  对外接口
 * ══════════════════════════════════════════════════════════════════ */

static void dispatch(esp_ipa_metadata_t *md)
{
    s_flags_last  = md->flags;
    s_flags_seen |= md->flags;

    /* ISP 侧先、传感器侧后：ISP 的参数在本帧就生效，而曝光/增益要一两帧之后才
     * 反映到统计里。顺序对结果没有影响（两者互不依赖），这样排只是让「本拍改了
     * 什么」在日志里按管线次序读下来。 */
    config_bf(md);
    config_demosaic(md);
    config_sharpen(md);
    config_gamma(md);
    config_ccm(md);
    config_color(md);
#if CAM_IPA_HAS_LSC
    config_lsc(md);
#endif
    /*
     * ── 本板拿不到的那几位：**只记录，不写硬件** ─────────────────
     *
     * IPA_METADATA_FLAGS_BLC —— 官方 sc202cs_default.json 里带着 acc.blc
     *   （model 0、stretch false、四个通道偏移都是 16），所以 blob 会稳定地
     *   置起这一位。rev v1.0 的 ISP 没有 BLC 块（isp_blc.c 的版本门要 rev>=3.0，
     *   连 esp_isp_blc_configure() 这个符号在本目标上都不会被链进来），
     *   于是这一位在本板上**只能忽略**。
     *   ⓘ 忽略它的代价是「黑电平基座 16/255 不被扣掉」—— 表现为暗部略微发灰、
     *     且这个基座会被 CCM 的负非对角项放大成轻微的品红黑位。传感器自身的
     *     BLC（寄存器 0x3902）能顶掉一部分，那是另一条独立的路。
     * IPA_METADATA_FLAGS_SR / _AF / _FP / _AETL —— 分别是统计区域、自动对焦、
     *   对焦位置、传感器 AE 目标电平。SC202CS 是定焦模组、标定文件里也没有
     *   af/atc 两节（JSON 只有 ian/awb/agc/adn/acc/aen 六个），所以这三位
     *   预期**永远不会置起**；真在自检行里看到它们，说明换了标定文件。
     * IPA_METADATA_FLAGS_AWB —— AWB 统计框（白点筛选的 rg/bg/green 上下界）。
     *   我们在 camera_csi.c 建 AWB 控制器时已经用官方标定的框配死了，
     *   而 esp_isp_awb_controller 的窗口/白点框只能在创建时给定 ⇒ 本位忽略。
     *
     * 这几位**一个字都不写硬件**，只经 s_flags_seen 进自检行 —— 「blob 要求了
     * 什么」与「我们做到了什么」必须在日志里分得开。
     */
    config_sensor(md);
}

esp_err_t cam_ipa_init(isp_proc_handle_t isp, esp_cam_sensor_device_t *sensor)
{
    ESP_RETURN_ON_FALSE(isp && sensor, ESP_ERR_INVALID_ARG, TAG, "句柄为空");
    if (s_pipe)
        return ESP_OK;                       /* 幂等 */

    s_isp    = isp;
    s_sensor = sensor;

    /*
     * ── 传感器可调范围：**一律运行时查，不写死** ──────────────────
     *
     * 曝光上限跟着模式表的 VTS 走，增益表的长度与内容跟着 menuconfig 的
     * CONFIG_CAMERA_SC202CS_ABSOLUTE_GAIN_LIMIT 与增益优先策略走。抄成常量
     * 必然在某次改配置时悄悄过期，而症状是「曝光调不动」或者更坏 —— 越界下标。
     *
     * ⚠️ 必须排在 esp_cam_sensor_set_format() **之后**（调用方保证）：
     *    传感器驱动是在那里才把 exposure_max / 默认曝光/增益填好的。
     */
    esp_cam_sensor_param_desc_t d_exp  = { .id = ESP_CAM_SENSOR_EXPOSURE_VAL };
    esp_cam_sensor_param_desc_t d_gain = { .id = ESP_CAM_SENSOR_GAIN };
    s_st_range = esp_cam_sensor_query_para_desc(sensor, &d_exp);
    if (s_st_range == ESP_OK)
        s_st_range = esp_cam_sensor_query_para_desc(sensor, &d_gain);

    const esp_cam_sensor_format_t *fmt = sensor->cur_format;
    if (s_st_range == ESP_OK &&
        (!fmt || !fmt->isp_info || fmt->fps == 0 ||
         fmt->isp_info->isp_v1_info.vts == 0 ||
         !d_gain.enumeration.elements || d_gain.enumeration.count == 0 ||
         d_exp.number.minimum <= 0 || d_exp.number.maximum < d_exp.number.minimum))
        s_st_range = ESP_ERR_INVALID_RESPONSE;   /* 查成功了但内容不可用 */

    if (s_st_range == ESP_OK) {
        s_exp_min_lines = (uint32_t)d_exp.number.minimum;
        s_exp_max_lines = (uint32_t)d_exp.number.maximum;
        s_gain_map      = d_gain.enumeration.elements;
        s_gain_count    = d_gain.enumeration.count;
        /* 一行的时间：一帧 = vts 行、一秒 = fps 帧 ⇒ t_line = 1e9/(fps·vts) ns。 */
        s_tline_ns = (uint32_t)(1000000000ull / ((uint64_t)fmt->fps *
                                                 fmt->isp_info->isp_v1_info.vts));
        /* 状态机的初值就是**芯片此刻的实际值** —— set_format 刚把这两个默认值
         * 写进去，所以状态与硬件天然一致，不必再多发一次 SCCB 去同步。 */
        s_cur_exp_lines = (uint32_t)d_exp.default_value;
        s_cur_gain_idx  = (uint32_t)d_gain.default_value;
        if (s_cur_gain_idx >= s_gain_count)
            s_cur_gain_idx = 0;

        s_info.width          = CAM_SENSOR_W;
        s_info.height         = CAM_SENSOR_H;
        s_info.min_exposure   = (uint32_t)(((uint64_t)s_exp_min_lines * s_tline_ns + 500) / 1000);
        s_info.max_exposure   = (uint32_t)(((uint64_t)s_exp_max_lines * s_tline_ns + 500) / 1000);
        s_info.cur_exposure   = (uint32_t)(((uint64_t)s_cur_exp_lines * s_tline_ns + 500) / 1000);
        s_info.step_exposure  = (s_tline_ns + 500) / 1000;   /* 一行 */
        s_info.min_gain       = (float)s_gain_map[0] / 1000.0f;
        s_info.max_gain       = (float)s_gain_map[s_gain_count - 1] / 1000.0f;
        s_info.cur_gain       = (float)s_gain_map[s_cur_gain_idx] / 1000.0f;
        /* step_gain = 0.0 表示「步长不均匀」（esp_ipa_types.h 的约定）——
         * SC202CS 的增益表确实是不等距的，别填成某个平均步长。 */
        s_info.step_gain      = 0.0f;
        s_info.focus_info     = NULL;         /* 定焦模组，没有 VCM */
        ESP_LOGI(TAG, "传感器范围：曝光 %" PRIu32 "~%" PRIu32 " 行（%" PRIu32 "~%" PRIu32
                      " µs，行时 %" PRIu32 " ns），增益 %" PRIu32 " 档（%.3f×~%.3f×）",
                 s_exp_min_lines, s_exp_max_lines, s_info.min_exposure, s_info.max_exposure,
                 s_tline_ns, s_gain_count, s_info.min_gain, s_info.max_gain);
    } else {
        ESP_LOGW(TAG, "拿不到曝光/增益的可调范围(%s)，AE 不会动，"
                      "画面固定在模式表的默认曝光上", esp_err_to_name((esp_err_t)s_st_range));
    }

#if CAM_IPA_HAS_LSC
    /*
     * LSC 的增益数组必须在 esp_isp_lsc_enable() **之前**分配
     * （esp_isp_lsc_allocate_gain_array() 要求 lsc_fsm == INIT，isp_lsc.c），
     * 所以这一步放在这里而不是等 metadata 第一次给出 LSC。
     * 失败只降级：画面保留四角暗角，其余一切照常。
     */
    s_st_lsc = esp_isp_lsc_allocate_gain_array(s_isp, &s_lsc_gain, &s_lsc_n);
    s_lsc_ready = (s_st_lsc == ESP_OK);
    if (!s_lsc_ready)
        ESP_LOGW(TAG, "LSC 增益数组没分配上(%s)，画面保留四角暗角，其余一切照常",
                 esp_err_to_name((esp_err_t)s_st_lsc));
#endif

    /*
     * 官方配置。**构建期**由 esp_ipa 的 tools/config/esp_ipa_config.py 从
     * sc202cs_default.json 生成成 esp_video_ipa_config.c 编进固件里 ——
     * 运行期没有任何 JSON 解析。那个 JSON 的路径由 esp_cam_sensor 的
     * project_include.cmake 按 CONFIG_CAMERA_SC202CS_DEFAULT_IPA_JSON_
     * CONFIGURATION_FILE（默认 y）自动设进 ESP_IPA_JSON_CONFIG_FILE_PATH
     * 这个 build property，**我们一行 CMake 都不用写**。
     *
     * 返回 NULL = 名字对不上（见 CAM_IPA_SENSOR_NAME 那段），此时整条 IPA 路
     * 不启动，画面停在 ISP 基础配置上。
     */
    const esp_ipa_config_t *cfg = esp_ipa_pipeline_get_config(CAM_IPA_SENSOR_NAME);
    if (!cfg) {
        s_st_cfg = ESP_ERR_NOT_FOUND;
        ESP_LOGE(TAG, "官方配置里没有「%s」—— 标定 JSON 没编进来，或顶层键名变了",
                 CAM_IPA_SENSOR_NAME);
        return ESP_ERR_NOT_FOUND;
    }
    s_st_cfg = ESP_OK;
    ESP_LOGI(TAG, "官方配置就绪：%u 个算法模块，参数版本 %" PRIu32,
             (unsigned)cfg->nums, cfg->version);
    for (uint8_t i = 0; i < cfg->nums; i++)
        ESP_LOGI(TAG, "  [%u] %s", (unsigned)i, cfg->names[i]);

    s_st_create = esp_ipa_pipeline_create(cfg, &s_pipe);
    if (s_st_create != ESP_OK) {
        ESP_LOGE(TAG, "IPA pipeline 建不起来(%s)", esp_err_to_name((esp_err_t)s_st_create));
        s_pipe = NULL;
        return (esp_err_t)s_st_create;
    }

    /*
     * init 会给出一批**初值** metadata（gamma 曲线、初始 CCM、BF/锐化模板…），
     * 官方要求「这些参数应当在跑 process() 之前就写进 ISP/传感器」。
     * 与 process() 走同一条分发路径 —— 两处若各写一份，迟早会分家。
     */
    memset(&s_md, 0, sizeof s_md);
    s_st_init = esp_ipa_pipeline_init(s_pipe, &s_info, &s_md);
    if (s_st_init != ESP_OK) {
        ESP_LOGE(TAG, "IPA pipeline 初始化失败(%s)", esp_err_to_name((esp_err_t)s_st_init));
        return (esp_err_t)s_st_init;
    }
    dispatch(&s_md);
    ESP_LOGI(TAG, "IPA 初值已下发（flags=0x%05" PRIx32 "）", s_flags_last);
    return ESP_OK;
}

void cam_ipa_process(const esp_ipa_stats_t *stats)
{
    if (!s_pipe || !stats)
        return;

    /* ⚠️ flags 必须每拍清零再交给 blob：它是**输出**参数，blob 只置位、不清位。
     *   不清的话上一拍的位会一直留着，分发层会拿陈旧的字段反复写硬件。
     *   官方 esp_video 在 isp_task 里也是每拍 `isp->metadata.flags = 0`。 */
    s_md.flags = 0;
    s_st_proc  = esp_ipa_pipeline_process(s_pipe, stats, &s_info, &s_md);
    s_ticks++;
    if (s_st_proc != ESP_OK)
        return;

    dispatch(&s_md);
}

uint32_t cam_ipa_gain_milli(void)
{
    if (!s_gain_map || s_cur_gain_idx >= s_gain_count)
        return 1000;
    return s_gain_map[s_cur_gain_idx];
}

/* 把 flags 位翻译成一串短名，自检行用。 */
static void flags_str(uint32_t f, char *buf, size_t n)
{
    static const struct { uint32_t bit; const char *name; } tbl[] = {
        { IPA_METADATA_FLAGS_AWB,   "AWB"   }, { IPA_METADATA_FLAGS_RG,    "RG"    },
        { IPA_METADATA_FLAGS_BG,    "BG"    }, { IPA_METADATA_FLAGS_ET,    "ET"    },
        { IPA_METADATA_FLAGS_GN,    "GN"    }, { IPA_METADATA_FLAGS_BF,    "BF"    },
        { IPA_METADATA_FLAGS_SH,    "SH"    }, { IPA_METADATA_FLAGS_GAMMA, "GAMMA" },
        { IPA_METADATA_FLAGS_CCM,   "CCM"   }, { IPA_METADATA_FLAGS_BR,    "BR"    },
        { IPA_METADATA_FLAGS_CN,    "CN"    }, { IPA_METADATA_FLAGS_ST,    "ST"    },
        { IPA_METADATA_FLAGS_HUE,   "HUE"   }, { IPA_METADATA_FLAGS_DM,    "DM"    },
        { IPA_METADATA_FLAGS_LSC,   "LSC"   }, { IPA_METADATA_FLAGS_AETL,  "AETL"  },
        { IPA_METADATA_FLAGS_SR,    "SR"    }, { IPA_METADATA_FLAGS_AF,    "AF"    },
        { IPA_METADATA_FLAGS_FP,    "FP"    }, { IPA_METADATA_FLAGS_BLC,   "BLC"   },
    };
    size_t off = 0;
    buf[0] = '\0';
    for (size_t i = 0; i < sizeof tbl / sizeof tbl[0]; i++) {
        if (!(f & tbl[i].bit))
            continue;
        const int w = snprintf(buf + off, n - off, "%s%s", off ? "," : "", tbl[i].name);
        if (w <= 0 || (size_t)w >= n - off)
            break;
        off += (size_t)w;
    }
    if (!off)
        snprintf(buf, n, "(无)");
}

static const char *step_str(int32_t v)
{
    return v == STEP_NOT_RUN ? "未运行" : esp_err_to_name((esp_err_t)v);
}

/*
 * IPA 自检快照。
 *
 * 判读：
 *   配置=ESP_ERR_NOT_FOUND  → 标定 JSON 没编进来。回去看 sdkconfig 里
 *                             CONFIG_CAMERA_SC202CS_DEFAULT_IPA_JSON_CONFIGURATION_FILE
 *                             是不是 y，以及 build 目录下有没有 esp_video_ipa_config.c。
 *   建立/初始化 非 OK       → blob 拒了。多半是 .names 里某个算法没被链进来
 *                             （CONFIG_ESP_IPA_*_ALGORITHM 被关掉了）。
 *   拍数=0 而在取流         → 统计一份都没送进来，回去看 camera_csi.c 的
 *                             camera_csi_tune_tick()。
 *   flags 里**始终没有 ET/GN** → 范围= 那格非 OK（查不到曝光/增益可调范围），
 *                             或者 blob 认为已经收敛（正常，遮挡镜头应当立刻出现）。
 *   flags 里有 BLC          → **预期如此**，本板忽略它，见 dispatch() 的注释。
 *   flags 里有 AF/FP/AETL/SR → 不该出现（标定文件没有 af/atc 两节）。出现了说明
 *                             换过标定文件，回去看 dispatch() 里那段的假设还成不成立。
 *   曝光=/增益= 一直不涨      → blob 在死区里。用手电或遮挡制造 3 档以上的亮度变化
 *                             再看，两个数应当在几拍之内动起来。
 */
void cam_ipa_report(void)
{
    char last[128], seen[128];
    flags_str(s_flags_last, last, sizeof last);
    flags_str(s_flags_seen, seen, sizeof seen);

    ESP_LOGI(TAG, "IPA：配置=%s 建立=%s 初始化=%s 范围=%s 处理=%s 拍数=%" PRIu32,
             step_str(s_st_cfg), step_str(s_st_create), step_str(s_st_init),
             step_str(s_st_range), step_str(s_st_proc), s_ticks);
    ESP_LOGI(TAG, "IPA：本拍 flags=[%s]  至今见过=[%s]", last, seen);
    ESP_LOGI(TAG, "IPA：下发 曝光=%" PRIu32 " 次（当前 %" PRIu32 " 行 = %" PRIu32
                  " µs）增益=%" PRIu32 " 次（当前 %u.%03u×）下发码=%s",
             s_n_exp, s_cur_exp_lines, s_info.cur_exposure, s_n_gain,
             (unsigned)(cam_ipa_gain_milli() / 1000), (unsigned)(cam_ipa_gain_milli() % 1000),
             step_str(s_st_exp));
    ESP_LOGI(TAG, "IPA：ISP 重配 CCM=%" PRIu32 " gamma=%" PRIu32 " LSC=%" PRIu32
                  "；块状态 BF=%s DM=%s SHARP=%s COLOR=%s CCM=%s GAMMA=%s LSC=%s",
             s_n_ccm, s_n_gamma, s_n_lsc,
             step_str(s_st_bf), step_str(s_st_dm), step_str(s_st_sharp),
             step_str(s_st_color), step_str(s_st_ccm), step_str(s_st_gamma),
#if CAM_IPA_HAS_LSC
             step_str(s_st_lsc));
#else
             "未编译");
#endif
    ESP_LOGI(TAG, "IPA：色彩 对比度=%u 饱和度=%u 色调=%u 亮度=%u"
                  "（128 = 1.0×）；BLC 位本板忽略（rev v1.0 无 ISP BLC）",
             s_color_contrast, s_color_saturation, s_color_hue, s_color_brightness);
}
