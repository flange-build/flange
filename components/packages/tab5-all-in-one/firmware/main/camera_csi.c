/*
 * SC202CS 的 SCCB 探测 + MIPI-CSI/ISP 取流。实现说明见 camera_csi.h。
 */
#include "camera_csi.h"
#include "board_power.h"
#include "cam_tune.h"
#include "tab5_pins.h"
#include "esp_log.h"
#include "esp_check.h"
#include <inttypes.h>
#include <stdio.h>
#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/queue.h"
#include "esp_sccb_intf.h"
#include "esp_sccb_i2c.h"
#include "sc202cs.h"
#include "esp_cam_sensor.h"
#include "esp_cam_ctlr.h"
#include "esp_cam_ctlr_csi.h"
#include "driver/isp.h"
#include "driver/isp_ccm.h"     /* 白平衡走 CCM：本板 rev v1.0 没有 WBG，见 cam_tune.h */
#if CAM_AE_STAT_ENABLE
#include "driver/isp_ae.h"      /* 硬件 5×5 分块测光（isp_ae.c 全文无 ESP_CHIP_REV_ABOVE） */
#endif
#if CAM_ADN_ENABLE
#include "driver/isp_bf.h"
#include "driver/isp_demosaic.h"
#endif
#if CAM_LSC_ENABLE
#include "driver/isp_lsc.h"
#endif
#if CAM_AEN_ENABLE
#include "driver/isp_sharpen.h"
#include "driver/isp_color.h"
#endif
#if CAM_GAMMA_ENABLE
#include "driver/isp_gamma.h"   /* 无芯片版本门（isp_gamma.c 全文无 ESP_CHIP_REV_ABOVE） */
#endif
#if CAM_ADN_ENABLE || CAM_LSC_ENABLE || CAM_AEN_ENABLE || CAM_GAMMA_ENABLE || CAM_AE_STAT_ENABLE
#include "cam_isp_cal.h"        /* 官方标定表（机械生成，别手改） */
#include "cam_isp_map.h"        /* 查表/定点/迟滞的纯逻辑，宿主机可测 */
#endif
#include "esp_cache.h"
#include "esp_heap_caps.h"
#include "esp_timer.h"

static const char *TAG = "camera";

/*
 * 开机自检快照。与 codec_audio.c 那份同构，理由也一样：探测跑在 CDC 日志串口
 * 真正开始出字节之前（host 要先打开 ttyACM，那之前的字节被环形缓冲冲掉），
 * 现场看不到这里的 ESP_LOG*，所以「卡在哪一步」必须记下来由
 * camera_sensor_report() 周期性复读。
 *
 * ⚠️ 哨兵与真实错误码严格分开（音频那边的教训）：STEP_NOT_RUN 表示**这一步压根
 * 没跑**，与「跑了但返回 ESP_OK/某错误」是三种不同的结论，不能共用一个值。
 * PID 同理：读都没读到与读回 0x0000 是两回事，所以用 int32_t 存，−1 = 未读取。
 */
#define STEP_NOT_RUN  INT32_MIN

static int32_t s_st_sccb   = STEP_NOT_RUN;  /* sccb_new_i2c_io() 返回值 */
static int32_t s_st_pid_rd = STEP_NOT_RUN;  /* 我们自己那两次 PID 寄存器读的返回值 */
static int32_t s_pid       = -1;            /* 读回的 PID，−1 = 一个字节都没读到 */
static bool    s_detected;                  /* sc202cs_detect() 是否返回了非 NULL */

/* 探到的传感器句柄。本任务只探测不取流，留着给 Task 8 的 CSI 编排用；
 * 探测失败时保持 NULL，且摄像头电源已被断开。 */
static esp_cam_sensor_device_t *s_sensor;

esp_err_t camera_sensor_probe(void)
{
    /* 上电 → 等稳。esp-bsp 的 bsp_camera_start() 在 feature_enable 之后
     * vTaskDelay(100ms)，照抄这个数：SC202CS 的内部 LDO 与板上 24 MHz 晶振起振
     * 都需要时间，探早了 SCCB 要么 NAK、要么读回 0。 */
    board_camera_enable(true);
    vTaskDelay(pdMS_TO_TICKS(100));

    /* SCCB 就是 I2C。复用内部总线句柄（G31/G32），**绝不新建 master** ——
     * 与 touch_hid.c / codec_audio.c 同一处置：这条总线上已经挂着触摸(20ms 轮询)、
     * 两颗 IO 扩展与两颗音频 codec，再建一个 master 会两套驱动抢同一组引脚。
     *
     * 字段名以 managed_components/espressif__esp_sccb_intf/sccb_i2c/include/
     * esp_sccb_i2c.h 的 sccb_i2c_config_t 为准（2.4.0 拉下来后逐字核对过）：
     *   device_address 收的是**不含读写位的 7 bit 原始地址**，与 esp_codec_dev
     *   那两颗要 8 bit 的处置相反，别混用。
     *   dev_addr_length 计划里没写，是本结构体的第一个字段，必须显式给
     *   I2C_ADDR_BIT_LEN_7（零值恰好也是它，但依赖零值等于把正确性寄托在枚举
     *   顺序上）。
     *   addr_bits_width/val_bits_width = 16/8：SC202CS 的寄存器地址是 16 位
     *   （0x3107 这种），值是 8 位。 */
    const sccb_i2c_config_t sccb_cfg = {
        .dev_addr_length = I2C_ADDR_BIT_LEN_7,
        .device_address  = SC202CS_I2C_ADDR7,
        .scl_speed_hz    = SC202CS_SCCB_HZ,
        .addr_bits_width = 16,
        .val_bits_width  = 8,
    };
    esp_sccb_io_handle_t sccb = NULL;
    s_st_sccb = sccb_new_i2c_io(board_i2c_bus(), &sccb_cfg, &sccb);
    if (s_st_sccb != ESP_OK) {
        board_camera_enable(false);
        ESP_LOGE(TAG, "SCCB 挂到内部 I2C 失败(%s)", esp_err_to_name(s_st_sccb));
        return s_st_sccb;
    }

    /*
     * **先自己读一次 PID，再交给组件。**
     *
     * 为什么多此一举：sc202cs_detect() 的三条失败路径（内存不够 / 读 ID 失败 /
     * PID 不匹配）**全都只返回 NULL**，调用方无从分辨。而这三者的排查方向完全
     * 不同 —— 前者查堆，中间那条查供电与走线，最后一条说明板上装的根本不是
     * SC202CS。多发两个 I2C 事务换来一个能直接定位的结论，很划算。
     *
     * 读到的两种「坏」结果也要能互相区分：
     *   返回 ESP_ERR_NOT_FOUND / ESP_ERR_TIMEOUT → 从机不应答（NAK），
     *       芯片没电或不在总线上，别再去查寄存器。
     *   返回 ESP_OK 但 PID != 0xeb52 → 总线通、芯片应答，只是它不是 SC202CS。
     */
    uint8_t pid_h = 0, pid_l = 0;
    s_st_pid_rd = esp_sccb_transmit_receive_reg_a16v8(sccb, SC202CS_REG_PID_H, &pid_h);
    if (s_st_pid_rd == ESP_OK)
        s_st_pid_rd = esp_sccb_transmit_receive_reg_a16v8(sccb, SC202CS_REG_PID_L, &pid_l);
    if (s_st_pid_rd == ESP_OK)
        s_pid = (int32_t)(((uint16_t)pid_h << 8) | pid_l);

    esp_cam_sensor_config_t cfg = {
        .sccb_handle  = sccb,
        .reset_pin    = -1,      /* Tab5 没有 RESET 引脚（esp-bsp: BSP_CAMERA_RST = NC） */
        .pwdn_pin     = -1,
        .xclk_pin     = -1,      /* 24 MHz 由板上晶振提供（BSP_CAMERA_GPIO_XCLK = NC） */
        .xclk_freq_hz = 0,       /* xclk_pin = -1 时组件不看这一项 */
        .sensor_port  = ESP_CAM_SENSOR_MIPI_CSI,
    };
    s_sensor = sc202cs_detect(&cfg);
    s_detected = (s_sensor != NULL);
    if (!s_detected) {
        /* 探测失败：立刻断电，守住 board_camera_enable() 的不变式。
         * SCCB 句柄留着不删 —— 它是纯软件对象，占十几字节，删掉反而让
         * camera_sensor_report() 少一件能复查的东西。 */
        board_camera_enable(false);
        ESP_LOGE(TAG, "SC202CS 探测失败（摄像头已断电）；具体卡在哪一步看下面的 [自检] 行");
        return ESP_ERR_NOT_FOUND;
    }

    ESP_LOGI(TAG, "SC202CS 探测成功 PID=0x%04x（期望 0x%04x）",
             s_sensor->id.pid, SC202CS_PID_EXPECT);

    /* 把组件挑中的默认模式打出来，作为「sdkconfig 那几行裁剪真的生效了」的现场
     * 证据：这里必须是 1280×720 / 30fps / 1 lane / 576 Mbps。数字对不上就说明
     * CONFIG_CAMERA_SC202CS_MIPI_DEFAULT_FMT_* 选错了，而那要到 Task 8 配 CSI
     * 控制器时才会以「花屏/收不到帧」的形式暴露出来 —— 太晚了。 */
    const esp_cam_sensor_format_t *f = s_sensor->cur_format;
    if (f)
        ESP_LOGI(TAG, "默认模式 %s：%ux%u @%ufps，MIPI %" PRIu32 " lane / %" PRIu32 " Mbps",
                 f->name ? f->name : "(无名)", f->width, f->height, f->fps,
                 f->mipi_info.lane_num, f->mipi_info.mipi_clk / 1000000);
    else
        ESP_LOGW(TAG, "组件没给默认模式（cur_format = NULL）");
    return ESP_OK;
}

/* 把一个快照槽打成人话。哨兵与真实错误码严格分开 —— 见 STEP_NOT_RUN 的声明。 */
static const char *step_str(int32_t v)
{
    return v == STEP_NOT_RUN ? "未运行" : esp_err_to_name((esp_err_t)v);
}

void camera_sensor_report(void)
{
    /*
     * 读法（从上往下，第一条不对的就是根因）：
     *   sccb=未运行            → camera_sensor_probe() 压根没被调用（编排问题）。
     *   sccb!=ESP_OK           → SCCB io 对象都没建起来，多半是 I2C 总线句柄为空
     *                            （board_power_init() 失败），与摄像头无关。
     *   pid_rd=ESP_ERR_NOT_FOUND / ESP_ERR_TIMEOUT
     *                          → 0x36 **不应答（NAK）**：查 CAMERA_EN(0x43 PIN6)
     *                            有没有真的拉高、100ms 延时够不够、排线接没接好。
     *                            此时 pid= 一定是「未读到」。
     *   pid_rd=ESP_OK 但 pid!=eb52
     *                          → 总线通、芯片应答，但板上装的不是 SC202CS。
     *                            别再查供电，去查这块板的摄像头模组型号。
     *   pid_rd=ESP_OK 且 pid=eb52 但 detect=0
     *                          → SCCB 一切正常，罪在组件内部（唯一剩下的路径是
     *                            calloc 失败）。看它自己那条 "No memory for camera"。
     *   detect=1               → 探到了。本阶段到此为止：不取流、不出图。
     */
    /* pid 打成字符串而不是数字：「一个字节都没读到」必须与任何一个具体数值
     * （含 0x0000）长得不一样，否则又回到音频那边「同一个哨兵值表达两件事」
     * 的老路上。缓冲开 16 而不是刚好够：GCC 的 -Wformat-truncation 只按
     * %04"PRIx32" 的类型上界（8 位十六进制）估算，开小了会被 -Werror 打回。 */
    char pid[16] = "未读到";
    if (s_pid >= 0)
        snprintf(pid, sizeof(pid), "0x%04" PRIx32, (uint32_t)s_pid);

    ESP_LOGI(TAG, "[自检] SCCB(0x%02x)=%s pid_rd=%s pid=%s(期望 0x%04x) detect=%d",
             SC202CS_I2C_ADDR7, step_str(s_st_sccb), step_str(s_st_pid_rd),
             pid, SC202CS_PID_EXPECT, s_detected);
}

/* ══ P4 Task8：MIPI-CSI + ISP 取流 ════════════════════════════════════ */

/*
 * 一帧 = 1280×720 个 RGB565 = 1 843 200 字节 ≈ 1.84 MB。
 *
 * 缓冲数取 **3**，不是双缓冲。理由是本驱动关掉了 CSI 的备份缓冲
 * （bk_buffer_dis = true，见 camera_csi_init()），此时**每帧结束的中断里必须
 * 拿得出一块空闲缓冲**，拿不出来 IDF 的 CSI 驱动会直接 assert(false) 崩掉。
 * 双缓冲下的稳态是「一块在 DMA、一块在调用方手里」⇒ 空闲数恰好为 0，
 * 调用方只要有一帧（33 ms）的抖动就会撞上抢缓冲的降级路径。第三块只多花
 * 1.84 MB PSRAM 空间、**不多花一点带宽**（DMA 同一时刻只写一块），
 * 换来「帧率/丢帧这两个判据不会因为自身的调度抖动而误报」。
 */
#define CAM_FB_COUNT   3
#define CAM_FB_BYTES   ((size_t)CAM_SENSOR_W * CAM_SENSOR_H * 2)

/* 帧缓冲对齐。P4 的 PSRAM cache line 是 64 字节，DMA 与 esp_cache_msync() 都要求
 * 首地址与长度按 cache line 对齐（不对齐时 msync 返回 INVALID_ARG，而它是在 CSI
 * 的中断里被 assert 的 —— 表现为崩在驱动内部，很难反查到这里）。
 * CAM_FB_BYTES = 1843200 = 64 × 28800，长度天然对齐。首地址靠 aligned_calloc。
 * init 里还会用 esp_cache_get_line_size_by_addr() 复核一次，免得这个 64 是猜的。 */
#define CAM_FB_ALIGN   64

/* ISP 时钟。1280×720@30fps = 27.6 Mpixel/s，ISP 每周期处理 1 个像素 ⇒ 80 MHz
 * 有近 3 倍余量。与 IDF 的 mipi_isp_dsi 例程取同一个数。 */
#define CAM_ISP_CLK_HZ (80 * 1000 * 1000)

static esp_cam_ctlr_handle_t s_cam;
static isp_proc_handle_t     s_isp;
static uint16_t             *s_fb[CAM_FB_COUNT];

/*
 * 缓冲在两个队列之间轮转：
 *   s_free_q  空闲，等着交给 DMA        —— 中断里取（ISR safe）
 *   s_done_q  已写满，等着交给调用方      —— 中断里放
 * s_held 是已经交给调用方、尚未归还的那一块（见 camera_csi_get_frame() 的约定）。
 */
static QueueHandle_t s_free_q;
static QueueHandle_t s_done_q;
static uint16_t     *s_held;
static bool          s_streaming;

/* 只在中断里读写，中断彼此串行，不需要额外同步。 */
static uint16_t *s_filling;        /* 当前交给 DMA 的那一块 */
static bool      s_reuse_pending;  /* 这一帧的缓冲是「抢回来的」，内容留不住 */

/* 运行期计数器。**只在自检快照里读**，不参与任何控制流。
 * volatile：前三个由 CSI 中断写、report/取帧任务读；32 位对齐读写在 P4 上是原子的，
 * 又都只做单向累加，不需要更强的同步。 */
static volatile uint32_t s_frames_done;     /* 完整写进缓冲、并交到 done 队列的帧 */
static volatile uint32_t s_frames_reused;   /* 中断没抢到空闲缓冲，把刚写完那块又借走 */
static volatile uint32_t s_frames_dropped;  /* done 队列满，写好的帧没人要 */
static uint32_t          s_get_timeouts;    /* camera_csi_get_frame() 超时次数 */
/*
 * 帧长不符。CSI 驱动交回来的 received_size 就是它自己算的
 * fb_size_in_bytes = h*v*out_bpp/8（esp_cam_ctlr_csi.c:158-160、386），
 * 与本文件的 CAM_FB_BYTES 是两条独立算出来的路。对不上就说明 csi_cfg 里
 * output_data_color_type 的理解错了 —— 那种错在画面上表现为花屏/错位，
 * 从像素上很难反推，所以在这里直接拦下来记成一个数，别让它冒充正常帧。
 */
static volatile uint32_t s_size_mismatch;
static volatile uint32_t s_last_size;       /* 最近一次收到的 received_size */

/* 六个初始化步骤各记一个返回值，**不共用哨兵**（STEP_NOT_RUN 在文件上半部定义）。
 * 这是音频那轮的教训：一个哨兵表达两件事，现场就分不出「没跑」和「跑了但失败」。 */
static int32_t s_st_fb    = STEP_NOT_RUN;   /* 帧缓冲分配 */
static int32_t s_st_ctlr  = STEP_NOT_RUN;   /* esp_cam_new_csi_ctlr() */
static int32_t s_st_cbs   = STEP_NOT_RUN;   /* esp_cam_ctlr_register_event_callbacks() */
static int32_t s_st_isp   = STEP_NOT_RUN;   /* esp_isp_new_processor() */
static int32_t s_st_fmt   = STEP_NOT_RUN;   /* esp_cam_sensor_set_format() */
static int32_t s_st_start = STEP_NOT_RUN;   /* enable/start/stream-on 整条启动链 */
static int32_t s_st_ccm   = STEP_NOT_RUN;   /* CCM 配置 + 使能（白平衡） */
static int32_t s_st_ae    = STEP_NOT_RUN;   /* AE 可调范围查询 */

/* ══ 画质：白平衡(AWB→CCM) 与自动曝光(AE) ══════════════════════════
 * 控制律与全部可调参数在 cam_tune.h；本文件只做两件 IDF 侧的事：
 * 把矩阵写进 ISP，以及把 AE 算出来的曝光/增益经 SCCB 写回传感器。 */
static cam_ae_limits_t   s_ae_lim;
static cam_ae_state_t    s_ae;
static bool              s_ae_ready;                  /* 可调范围查到了吗 */
static int32_t           s_ae_last_err = ESP_OK;      /* 最近一次下发的返回值 */
static cam_frame_stats_t s_last_stats;                /* 最近一帧的统计，自检行用 */

/* 此刻**真正写进 CCM 硬件**的那一对增益。初值是静态标定值；AWB 开着时由
 * camera_awb_tick() 跟着状态机走。自检行打的「当前」就是它，抄进 cam_tune.h
 * 即可把闭环的结论固化成静态标定。 */
static uint32_t s_ccm_r = CAM_CCM_GAIN_R_MILLI;
static uint32_t s_ccm_b = CAM_CCM_GAIN_B_MILLI;

#if CAM_AWB_ENABLE
static cam_awb_state_t s_awb;
static int32_t         s_awb_last_err = ESP_OK;   /* 最近一次重配 CCM 的返回值 */
#endif

#if CAM_AE_SOURCE && !CAM_AE_STAT_ENABLE
#error "CAM_AE_SOURCE=1（AE 吃硬件统计）依赖 CAM_AE_STAT_ENABLE=1；\
两者不相容时若不在这里拦下，运行期表现是 AE 拿一份全 0 的统计把曝光推到顶。"
#endif

#if CAM_AE_SOURCE
/*
 * ⚠️ 目标与死区**必须**与官方标定表逐位相同 —— 换源之后它们才是同一个采样点上的量。
 * cam_tune.h 里写的是字面量（那个文件是纯逻辑、不许依赖标定表），这三条断言
 * 是唯一把两边钉在一起的东西：改一个不改另一个，编译期就断。
 */
_Static_assert(CAM_AE_TARGET      == CAM_CAL_AE_TARGET,
               "CAM_AE_TARGET 与官方 agc.luma_adjust.target 不一致");
_Static_assert(CAM_AE_TARGET_LOW  == CAM_CAL_AE_TARGET_LOW,
               "CAM_AE_TARGET_LOW 与官方 agc.luma_adjust 的下边界不一致");
_Static_assert(CAM_AE_TARGET_HIGH == CAM_CAL_AE_TARGET_HIGH,
               "CAM_AE_TARGET_HIGH 与官方 agc.luma_adjust 的上边界不一致");
#endif

#if CAM_AE_STAT_ENABLE
/* ══ 硬件 AE 5×5 分块统计 ══════════════════════════════════════════
 * 设计意图、ρ 的定义与「为什么先观测再切换」见 cam_tune.h 的 CAM_AE_STAT_ENABLE。 */
static isp_ae_ctlr_t s_ae_ctlr;
static int32_t       s_st_aestat = STEP_NOT_RUN;  /* 建控制器 / 注册回调 / 使能，取第一个失败 */
static int32_t       s_st_aerun  = STEP_NOT_RUN;  /* start/stop 连续统计的返回值 */

/* 25 块亮度 + 帧计数。中断写、任务读 ⇒ 必须整体一致（25 个字节不是原子的），
 * 用自旋锁把「搬 25 字节」与「读 25 字节」各自变成一个临界区。
 * 用 portMUX 而不是 mutex：写方在 ISR 里，ISR 不能阻塞。 */
static portMUX_TYPE  s_ae_lock = portMUX_INITIALIZER_UNLOCKED;
static uint8_t       s_ae_blocks[25];
static uint32_t      s_ae_stat_frames;

/*
 * ⚠️ 本函数跑在 **ISR 上下文**（isp_core.c 的 s_isp_isr_dispatcher）。
 *   里面只做 25 字节的搬运：不打日志、不发队列、不调任何可能阻塞的东西。
 *
 * ⓘ **不加 IRAM_ATTR**：CONFIG_ISP_ISR_IRAM_SAFE 默认关（本工程没开），此时
 *   ISP 的 ISR 允许访问 flash；加了反而按 isp_ae.c 的 `#if CONFIG_ISP_ISR_IRAM_SAEE`
 *   分支要求 s_ae_blocks 等一并进内部 RAM，凭空多一层约束。
 *
 * ⓘ 返回 false = 没有唤醒任何任务（我们不用队列/信号量，AE 的执行仍然跑在
 *   帧泵那一拍上，见 camera_ae_tick）。
 *
 * ⓘ 驱动填 luminance[i][j] 的次序是 `block_id = i*5 + j` 顺着
 *   isp_ll_ae_get_block_mean_lum() 读的（isp_ae.c 的 esp_isp_ae_isr），
 *   而**硬件块编号横着数还是竖着数在 IDF 里查不到 [缺口]**。这对我们没有影响：
 *   官方权重表是中心对称的金字塔（转置后与自身相同），过暗/过亮块又只是计数。
 *   真实排布由「只遮半边镜头看哪些块掉下去」这条现场判据顺带测出来。
 */
static bool cam_on_ae_stat(isp_ae_ctlr_t h, const esp_isp_ae_env_detector_evt_data_t *e,
                           void *ud)
{
    (void)h;
    (void)ud;
    portENTER_CRITICAL_ISR(&s_ae_lock);
    for (int i = 0; i < 5; i++)
        for (int j = 0; j < 5; j++)
            s_ae_blocks[i * 5 + j] = (uint8_t)e->ae_result.luminance[i][j];
    s_ae_stat_frames++;
    portEXIT_CRITICAL_ISR(&s_ae_lock);
    return false;
}

/* 取一份 25 块的快照，并算出加权均值与两个 quorum 计数。
 * 返回本函数被调用时统计块已经交付过多少帧（0 = 一帧都没收到，调用方据此
 * 判断「这份数能不能用」——拿全 0 去调曝光会把曝光一路推到顶）。 */
static uint32_t cam_ae_stat_snapshot(uint8_t blocks[25], uint8_t *hw_mean,
                                     uint8_t *n_dark, uint8_t *n_bright)
{
    uint32_t frames;
    portENTER_CRITICAL(&s_ae_lock);
    memcpy(blocks, s_ae_blocks, 25);
    frames = s_ae_stat_frames;
    portEXIT_CRITICAL(&s_ae_lock);
    *hw_mean = cam_ae_weighted_mean(blocks, n_dark, n_bright);
    return frames;
}
#endif  /* CAM_AE_STAT_ENABLE */

/* ══ 官方前馈画质级（开环查表）══════════════════════════════════════
 * 三组各一个编译开关（cam_tune.h），关掉时下面整段不进镜像 —— 这是现场
 * bisect 的唯一手段，别把它们合并成一个开关。
 *
 * ⚠️ 每一级的状态槽都**不共用哨兵**（与文件上半部那六个同一处置）：
 *      STEP_NOT_RUN  这一级编译进来了，但**一次都没配过**（比如还没取流）
 *      非 ESP_OK     配过了，硬件拒了，值就是错误码
 *      ESP_OK        配上了，自检行同时打出该级此刻的关键参数值
 *      「未编译」     开关 = 0，由自检行的 #else 分支说出来
 *   四种情况必须能分开，否则「画面没变化」这一个现象对应四种完全不同的下一步。 */
#if CAM_ADN_ENABLE || CAM_AEN_ENABLE
/* **所有**前馈级加起来累计重配了多少次（一个计数器、每行自检都打同一个数，
 * 所以标签是「前馈重配合计」而不是「重配」—— 别读成「本级重配了这么多次」）。
 * 它是迟滞是否起作用的唯一判据：随时间线性增长 ⇒ 要么增益一直在变（去看 AE
 * 那行），要么 CAM_FEEDFWD_HYST_TICKS 太小。
 * 开机稳定后它应当停住；开机第一拍每个被编译进来的子级各 +1
 * （ADN + AEN 全开 ⇒ BF/Demosaic/SHARP/Color 各一次 = 4）。 */
static uint32_t s_feedfwd_reconf;
/* 最近一拍喂给选档器的总增益。选档全靠它，打出来才能判断「档位不动」是
 * 「增益没变」还是「选档算错了」。 */
static uint32_t s_feedfwd_gain_milli;
#endif

#if CAM_ADN_ENABLE
static cam_slot_track_t s_bf_track, s_dm_track;
static int32_t s_st_bf = STEP_NOT_RUN;    /* esp_isp_bf_configure/enable 的返回值 */
static int32_t s_st_dm = STEP_NOT_RUN;    /* esp_isp_demosaic_configure 的返回值 */
static bool    s_bf_enabled;              /* esp_isp_bf_enable 有 FSM 门，只能成功一次 */
#endif

#if CAM_LSC_ENABLE
/* 四个通道各 273 项的增益数组，由驱动分配、常驻（T13 换档要复用同一块）。 */
static esp_isp_lsc_gain_array_t s_lsc_gain;
static size_t  s_lsc_n;
static int32_t s_st_lsc = STEP_NOT_RUN;
#endif

#if CAM_AEN_ENABLE
static cam_slot_track_t s_sh_track, s_ct_track;
static int32_t s_st_sharp = STEP_NOT_RUN;
static int32_t s_st_color = STEP_NOT_RUN;
static bool    s_sharp_enabled;           /* enable 有 FSM 门 */
static bool    s_color_enabled;
static uint8_t s_contrast_val = 128;      /* 此刻写进硬件的对比度，自检行用 */
#endif

#if CAM_GAMMA_ENABLE
/*
 * ══ gamma ══ 线性 → sRGB 式的编码曲线，**这条链路上缺的那一环**。
 *
 * 为什么它不属于「前馈画质级」那一组（虽然写法很像）：前三组只改画质，gamma
 * 改的是**输出的传递函数本身** —— 它一开，送给主机的每个像素的含义就变了，
 * 因此必须同时把统计侧的逆变换配套上，否则 AE/AWB 的反馈量当场失真。
 * 完整的「为什么提前 / 代价怎么还」见 cam_tune.h 的 CAM_GAMMA_ENABLE 那段。
 */
static int32_t s_st_gamma = STEP_NOT_RUN;
/* 当前生效的档。逆表就是按它生成的，两者永远由 camera_gamma_apply() 一起设定。
 * T11 做动态换档时改的是它，不是别处。 */
static uint32_t s_gamma_slot = CAM_GAMMA_SLOT;
/*
 * 逆表。**只有 s_gamma_ready 为真时才交给统计层** —— 它同时表达两件事：
 * 「表建好了」且「硬件里确实是这条曲线」。gamma 没配上时画面本来就是线性的，
 * 这时再逆一次会把反馈量系统性压暗，比不逆更糟。
 */
static uint8_t s_gamma_inv[256];
static bool    s_gamma_ready;

/*
 * 配一档 gamma：**下发硬件与重建逆表绑在同一个函数里**。
 *
 * 这不是排版偏好，是这次改动唯一的正确性支点：逆表与硬件曲线一旦不同源，
 * AE/AWB 会拿一个系统性偏移过的反馈量安静地闭环，画面上看不出任何异常，
 * 而自检行里的每一个数都仍然「自洽」。所以不给它们各自走一条路的机会 ——
 * 将来 T11 做动态换档时也只需要再调一次本函数。
 *
 * R/G/B 三个通道配**同一条**曲线：官方每档只有一个 gamma_param，没有分通道差异；
 * 而且逐通道的逆表能成立，前提正是三通道同曲线。
 *
 * ⚠️ **逆表还原的是「线性 + YUV 域那点残差」，不是数学上完美的线性。** 硬件管线里
 *   gamma 在 RGB 域、Color（对比度/饱和度）在其**下游**的 YUV 域 ⇒ 我们采到的是
 *   C(F(linear))，逆回去得到的是 F⁻¹(C(F(linear)))。残差量在 T4 已经逐条算过：
 *   饱和度钉在 128 = 1.000× ⇒ **逐像素恒等，零残差**；对比度 132 = 1.031× 只作用
 *   在 Y 上 ⇒ 亮度残差约 3%、通道比值残差约 0.7%，分别远小于 AE 死区（6/62 ≈ 9.7%）
 *   与 AWB 死区（5%）。也就是说这份残差在 gamma 上线之前就已经存在、量级没变，
 *   不是本次引入的新误差。
 */
static esp_err_t camera_gamma_apply(uint32_t slot)
{
    isp_gamma_curve_points_t pts = {0};

    /*
     * ⚠️ **不走 esp_isp_gamma_fill_curve_points()。** 那个 helper 只接受一个
     *   `uint32_t f(uint32_t)` 的函数指针，要在运行期算 x^γ ⇒ 拖进浮点 powf，
     *   而我们的 y 早就在提取脚本里算好、并且是**宿主机测试逐点核对过**的常量表。
     *   顺带避开它那条 `y < 256` 的检查：以 256 归一时末点 256·(255/256)^0.5 = 256
     *   会被直接拒（这正是标定表以 255 而不是 256 归一的原因，见 cam_isp_cal.h）。
     *
     * x 栅格 16,32,…,240,255 满足驱动的两条硬要求（isp_gamma.c 的校验循环）：
     *   ① 每段段长必须是 **2 的幂** —— 全部是 16；
     *   ② 末点 x **必须恰好是 255**，且末段按 256−240 = 16 算段长。
     */
    for (int i = 0; i < CAM_CAL_GAMMA_PTS; i++) {
        pts.pt[i].x = cam_cal_gamma_x[i];
        pts.pt[i].y = cam_cal_gamma_y[slot][i];
    }

    for (int c = 0; c < 3; c++) {
        const color_component_t comp = (c == 0) ? COLOR_COMPONENT_R
                                     : (c == 1) ? COLOR_COMPONENT_G
                                                : COLOR_COMPONENT_B;
        const esp_err_t err = esp_isp_gamma_configure(s_isp, comp, &pts);
        if (err != ESP_OK)
            return err;   /* 逆表不建 ⇒ s_gamma_ready 保持假 ⇒ 统计留在线性域 */
    }

    /* 硬件收下了才建逆表，顺序不能反。 */
    cam_gamma_inverse_lut(slot, s_gamma_inv);
    s_gamma_slot  = slot;
    s_gamma_ready = true;
    return ESP_OK;
}
#endif  /* CAM_GAMMA_ENABLE */

/*
 * 统计层要用的逆 gamma 表。返回 NULL = 「别逆」（gamma 关着或没配上，
 * 画面本来就是线性的）。
 */
const uint8_t *camera_csi_gamma_inv_lut(void)
{
#if CAM_GAMMA_ENABLE
    return s_gamma_ready ? s_gamma_inv : NULL;
#else
    return NULL;
#endif
}

/*
 * 把一对增益写成 CCM 的对角阵送进 ISP。开机配一次，之后 AWB 每次调整再配一次。
 *
 * saturation = true：万一系数落到定点格式表达不了的值，宁可饱和也不要整个配置
 * 失败 —— 失败等于**一点白平衡都没有**，比略微不准坏得多。
 * update_once_configured = true：立刻写进硬件而不是等下一个 VSYNC。开机时这是
 * 必须的（那时还没 stream on，等 VSYNC 就等成了「第一帧还没白平衡」）；运行期
 * 它意味着理论上可能有一帧中途换矩阵，但 rev < 3.0 上 isp_ll_shadow_update_ccm()
 * 本就是个恒真的空函数（hal/isp_ll.h 的 "for compatibility" 分支），这一位在本板
 * 上无害，而 AWB 最快一秒才改一次、每次幅度 ≤ 25%，肉眼不可能看出来。
 *
 * ⓘ 只 configure、**不再 enable**：esp_isp_ccm_enable() 有 FSM 检查，重复调用
 *   直接返回 ESP_ERR_INVALID_STATE。而 esp_isp_ccm_configure() 没有任何 FSM/版本
 *   门（IDF v6.0 的 isp_ccm.c 全文），取流中随时可调。
 */
static esp_err_t camera_ccm_apply(uint32_t r_milli, uint32_t b_milli)
{
    const esp_isp_ccm_config_t ccm_cfg = {
        .matrix = {
            {r_milli / 1000.0f, 0.0f, 0.0f},
            {0.0f, CAM_CCM_GAIN_G_MILLI / 1000.0f, 0.0f},
            {0.0f, 0.0f, b_milli / 1000.0f},
        },
        .saturation = true,
        .flags = { .update_once_configured = 1 },
    };
    const esp_err_t err = esp_isp_ccm_configure(s_isp, &ccm_cfg);
    if (err == ESP_OK) {
        s_ccm_r = r_milli;
        s_ccm_b = b_milli;
    }
    return err;
}

#if CAM_LSC_ENABLE
/*
 * 把某一档 LSC 标定表填进驱动分配的增益数组并下发。
 *
 * 定点：表里存的就是 round(v × 256)，与 isp_lsc_gain_t 的 2 整数位 + 8 小数位
 * 逐位对齐 ⇒ 直接写 .val，**不做任何换算**。全表实测最大 851（3.323×），
 * 硬件上限 1023（3.996×），余量 17%；那条边界由提取脚本的断言守着，不在这里重复。
 *
 * ⓘ esp_isp_lsc_configure() 没有 FSM 门（isp_lsc.c 全文），取流中可以重配 ——
 *   T13 按色温换档就靠这一点。代价是 273 × 2 条 LUT 写命令，所以只在档变时做。
 */
static esp_err_t camera_lsc_apply(uint32_t slot)
{
    for (size_t y = 0; y < CAM_CAL_LSC_GRID_Y; y++) {
        for (size_t x = 0; x < CAM_CAL_LSC_GRID_X; x++) {
            /* 目的下标固定按驱动的写法 i = y·num_grids_x + x（isp_lsc.c）。
             * 源下标可能要转置 —— JSON 的排布顺序是缺口，见 CAM_LSC_TRANSPOSE。 */
            const size_t dst = y * CAM_CAL_LSC_GRID_X + x;
#if CAM_LSC_TRANSPOSE
            const size_t src = x * CAM_CAL_LSC_GRID_Y + y;
#else
            const size_t src = dst;
#endif
            s_lsc_gain.gain_r [dst].val = cam_cal_lsc[slot][0][src];
            s_lsc_gain.gain_gr[dst].val = cam_cal_lsc[slot][1][src];
            s_lsc_gain.gain_gb[dst].val = cam_cal_lsc[slot][2][src];
            s_lsc_gain.gain_b [dst].val = cam_cal_lsc[slot][3][src];
        }
    }
    const esp_isp_lsc_config_t cfg = { .gain_array = &s_lsc_gain };
    return esp_isp_lsc_configure(s_isp, &cfg);
}
#endif  /* CAM_LSC_ENABLE */

/*
 * 中断回调之一：DMA 要下一块缓冲了。
 *
 * ⚠️ **必须无条件给出一块缓冲。** bk_buffer_dis = true 时驱动没有内部备份缓冲，
 * 这里返回空会让它走到 assert(false)（esp_cam_ctlr_csi.c 的
 * "no new buffer, and no driver internal buffer"）—— 也就是直接崩机。
 * 所以空闲队列空了的时候，把**刚写满、还没交出去的那一块**再借给 DMA，
 * 并置 s_reuse_pending；紧接着的 on_trans_finished 会据此把这一帧记成 reused
 * 而不是入队 —— 它的内容马上就要被覆盖，交出去就是错的。
 * 这样「跟不上」表现为一个可读的计数器，而不是一次崩机。
 */
static bool cam_on_get_new_trans(esp_cam_ctlr_handle_t handle,
                                 esp_cam_ctlr_trans_t *trans, void *user_data)
{
    (void)handle;
    (void)user_data;
    BaseType_t woken = pdFALSE;
    uint16_t *buf = NULL;

    if (xQueueReceiveFromISR(s_free_q, &buf, &woken) == pdTRUE) {
        s_reuse_pending = false;
    } else {
        buf = s_filling;          /* 即将在下一段被 finish 的那一块 */
        s_reuse_pending = true;
    }
    trans->buffer = buf;
    trans->buflen = CAM_FB_BYTES;
    s_filling = buf;
    return woken == pdTRUE;
}

/* 中断回调之二：一帧写完了。 */
static bool cam_on_trans_finished(esp_cam_ctlr_handle_t handle,
                                  esp_cam_ctlr_trans_t *trans, void *user_data)
{
    (void)handle;
    (void)user_data;
    BaseType_t woken = pdFALSE;

    if (s_reuse_pending) {
        s_reuse_pending = false;
        s_frames_reused++;
        return false;
    }
    s_last_size = (uint32_t)trans->received_size;
    if (trans->received_size != CAM_FB_BYTES) {
        /* 不把它当帧交出去：半帧/超长帧的统计值会冒充正常画面，比没有帧更坏。 */
        s_size_mismatch++;
        uint16_t *bad = trans->buffer;
        xQueueSendFromISR(s_free_q, &bad, &woken);
        return woken == pdTRUE;
    }
    uint16_t *buf = trans->buffer;
    if (xQueueSendFromISR(s_done_q, &buf, &woken) == pdTRUE)
        s_frames_done++;
    else
        s_frames_dropped++;       /* 队列深度 = 缓冲数，理论上到不了这里 */
    return woken == pdTRUE;
}

esp_err_t camera_csi_init(void)
{
    ESP_RETURN_ON_FALSE(s_sensor, ESP_ERR_INVALID_STATE, TAG,
                        "传感器没探到，不建 CSI/ISP");
    if (s_cam)
        return ESP_OK;            /* 幂等 */

    /*
     * ⓘ MIPI PHY 的供电（LDO_VO3 @ 2.5V → VDD_MIPI_DPHY）**不在这里申请**：
     *   P4 上 DSI 与 CSI 两个 PHY 共用这一路 LDO，display_dsi.c 开机时已经
     *   esp_ldo_acquire_channel(DSI_PHY_LDO_CHAN) 过了，而显示是核心链路
     *   （ESP_ERROR_CHECK，起不来就没有任何可用形态），所以走到这里时它必然是通的。
     *   在这里再申请一次只会多一条会失败的路径。
     */

    /*
     * CSI 控制器。参数全部来自 esp_cam_sensor 的模式表 sc202cs_format_info[0]
     * （"MIPI_1lane_24Minput_RAW8_1280x720_30fps"）：lane_num = 1、
     * mipi_clk = 576000000 ⇒ lane_bit_rate_mbps = 576。
     * ⚠️ 这是**唯一可用**的传感器模式：1600×1200 的 1200 行超出 P4 ISP 的
     *    1920×1080 输入上限，1600×900 裁不出 4:3。见 P4 计划的「关键事实」。
     *
     * ══ input 与 output **都填 RGB565**，这不是笔误 ═══════════════════════
     *
     * 硬件管线是：CSI PHY/host → **ISP** → CSI 桥 → DW-GDMA → PSRAM。
     * ISP 在桥的**上游**（soc_caps.h 的 SOC_ISP_SHARE_CSI_BRG = 1；isp_core.c:92
     * 用 MIPI_CSI_BRG_USER_SHARE 认领同一个桥，本文件的 CSI 控制器用
     * MIPI_CSI_BRG_USER_CSI 认领，mipi_csi_share_hw_ctrl.c 明确允许这一对共存，
     * 见 esp_driver_isp/test_apps 的 test_isp_csi.c）。
     * ⇒ **写进 PSRAM 的字节由 ISP 的输出格式决定**，桥只是搬运。
     *   RAW8 → RGB565 的去马赛克整个由 ISP 做（isp_ll.h:473-478，
     *   isp_ll_set_output_data_color_format(RGB565) 会顺手把 demosaic_en 打开）。
     *
     * 于是这两个字段对 CSI 控制器只剩两个作用，**都不是「告诉它传感器发的是什么」**
     * （CSI host 压根不配色彩格式：mipi_csi_hal_init() 只设 lane/时钟，
     *  数据类型范围写死 0x12~0x2f，已经涵盖 RAW8 的 0x2A）：
     *   input  → in_bpp  → csi_transfer_size = h*v*in_bpp/64，**DMA 搬多少字节**
     *   output → out_bpp → fb_size_in_bytes  = h*v*out_bpp/8，缓冲长度校验与
     *                      交回来的 received_size
     *   （esp_cam_ctlr_csi.c:143-160、207）
     * 填 RAW8/RGB565 的话 DMA 只搬 921600 字节、却声称收到 1843200 字节 ——
     * **半帧**。两个都填 RGB565 时 in_bpp == out_bpp == 16，两个数都是 1843200，
     * 与 ISP 实际吐出的字节数一致。
     *
     * ⚠️⚠️ 更硬的一条：**本板 P4 是 rev v1.0，桥的颜色转换功能根本不存在。**
     *   esp_cam_new_csi_ctlr() 内部会调 s_csi_ctlr_format_conversion()
     *   （esp_cam_ctlr_csi.c:226）；只要 input != output，它在
     *   :604-608 处查芯片版本，rev < 3.0 直接返回 ESP_ERR_NOT_SUPPORTED —— 实机
     *   第一次就是死在这里（快照打的是 ctlr=ESP_ERR_NOT_SUPPORTED）。
     *   而 mipi_csi_ll.h:159/292 那对 #if HAL_CONFIG(CHIP_SUPPORT_MIN_REV) >= 300
     *   更说明问题：rev < 3.0 编译出来的那一版里，桥的五个颜色模式 LL 函数
     *   **全是空函数**，硬件上就没有这个块。
     *   ⇒ IDF 例程 examples/peripherals/camera/mipi_isp_dsi 那份
     *      RAW8 → RGB565 的 CSI 配置**只适用于 rev ≥ 3.0，不能照抄**。
     *   （这是同一个芯片版本限制第三次咬这个工程：先是烧录门槛
     *     CONFIG_ESP32P4_SELECTS_REV_LESS_V3，再是 JPEG 编码器不支持 YUV420/444。）
     *
     * ⓘ input == output 这条路**两个版本都对**：src == dst 时驱动走的是
     *   :599-602 的直通分支，rev ≥ 3.0 上写真的旁路位、rev < 3.0 上是空操作，
     *   去马赛克反正都在 ISP 里。所以这里不做版本分支。
     */
    const esp_cam_ctlr_csi_config_t csi_cfg = {
        .ctlr_id  = 0,
        .clk_src  = MIPI_CSI_PHY_CLK_SRC_DEFAULT,
        .h_res    = CAM_SENSOR_W,
        .v_res    = CAM_SENSOR_H,
        .data_lane_num      = CAM_MIPI_LANES,   /* 1 */
        .lane_bit_rate_mbps = CAM_MIPI_MBPS,    /* 576 */
        /* 见上面那一大段：这两个描述的是**桥搬运的数据**（= ISP 的输出），
         * 不是传感器发出来的 RAW8。相等 ⇒ 桥直通，不触发颜色转换的版本门。 */
        .input_data_color_type  = CAM_CTLR_COLOR_RGB565,
        .output_data_color_type = CAM_CTLR_COLOR_RGB565,
        .queue_items  = CAM_FB_COUNT,
        .byte_swap_en = false,
        /* 关掉驱动内部的备份缓冲：它会再吃 1.84 MB PSRAM **和一份写带宽**
         * （没人排队时 DMA 照样往它里面写），而本驱动自己排了 3 块缓冲，
         * 空闲队列见底时由 cam_on_get_new_trans() 的抢用路径兜住。 */
        .bk_buffer_dis = true,
    };
    s_st_ctlr = esp_cam_new_csi_ctlr(&csi_cfg, &s_cam);
    ESP_RETURN_ON_ERROR(s_st_ctlr, TAG, "CSI 控制器");

    /* 两个回调都必须注册：esp_cam_ctlr_start() 会硬性检查 on_trans_finished
     * （没有它直接返回 ESP_ERR_INVALID_STATE），而 bk_buffer_dis = true 时
     * on_get_new_trans 也是必须的 —— start 拿不到第一块缓冲同样起不来。 */
    const esp_cam_ctlr_evt_cbs_t cbs = {
        .on_get_new_trans  = cam_on_get_new_trans,
        .on_trans_finished = cam_on_trans_finished,
    };
    s_st_cbs = esp_cam_ctlr_register_event_callbacks(s_cam, &cbs, NULL);
    ESP_RETURN_ON_ERROR(s_st_cbs, TAG, "CSI 回调注册");

    /* 队列放指针即可，深度 = 缓冲数。 */
    s_free_q = xQueueCreate(CAM_FB_COUNT, sizeof(uint16_t *));
    s_done_q = xQueueCreate(CAM_FB_COUNT, sizeof(uint16_t *));
    ESP_RETURN_ON_FALSE(s_free_q && s_done_q, ESP_ERR_NO_MEM, TAG, "帧队列");

    for (int i = 0; i < CAM_FB_COUNT; i++) {
        s_fb[i] = heap_caps_aligned_calloc(CAM_FB_ALIGN, 1, CAM_FB_BYTES,
                                           MALLOC_CAP_SPIRAM | MALLOC_CAP_DMA);
        if (!s_fb[i]) {
            s_st_fb = ESP_ERR_NO_MEM;
            ESP_RETURN_ON_FALSE(false, ESP_ERR_NO_MEM, TAG,
                                "帧缓冲 %d/%d（每块 %u 字节）分配失败",
                                i, CAM_FB_COUNT, (unsigned)CAM_FB_BYTES);
        }
        /* CAM_FB_ALIGN 是不是真的够，问一次硬件而不是靠记忆 —— 猜错的话
         * esp_cache_msync() 会在 CSI 中断里 assert，那种崩很难反查到这一行。 */
        const size_t line = esp_cache_get_line_size_by_addr(s_fb[i]);
        if (line == 0 || (CAM_FB_ALIGN % line) != 0) {
            s_st_fb = ESP_ERR_INVALID_STATE;
            ESP_RETURN_ON_FALSE(false, ESP_ERR_INVALID_STATE, TAG,
                                "cache line = %u，与 CAM_FB_ALIGN(%d) 不相容",
                                (unsigned)line, CAM_FB_ALIGN);
        }
        xQueueSend(s_free_q, &s_fb[i], 0);
    }
    s_st_fb = ESP_OK;

    /*
     * ISP：把 RAW8 去马赛克成 RGB565。**整条 RAW→RGB 转换只有这一处在做**，
     * CSI 桥那边是直通（理由见上面 csi_cfg 那一大段）。
     *
     * ⓘ rev < 3.0 上这条路是通的：esp_isp_new_processor() / esp_isp_enable() /
     *   去马赛克本身**没有任何芯片版本门**，isp_ll.h:473-478 里
     *   ISP_COLOR_RGB565 会把 isp_out_type = 4 且 demosaic_en = 1 一起设好。
     *   可选子模块里**真正有版本门的只有三个**（IDF v6.0 逐个 grep 过）：
     *   BLC(isp_blc.c:30)、WBG(isp_wbg.c:30)、crop(isp_crop.c:30) 要 rev ≥ 3.0；
     *   LSC(isp_lsc.c:58) 要 rev ≥ 1.0，而 ESP_CHIP_REV_ABOVE 是
     *   `(min_rev) <= (rev)`（soc/chip_revision.h:31）⇒ 本板 rev v1.0 **满足**。
     *   ⚠️ 曾经写在这里的「AWB(isp_awb.c:82) 要 rev ≥ 3.0」**是错的**：
     *      isp_awb.c 整个文件没有 ESP_CHIP_REV_ABOVE，那一处 efuse_hal_chip_revision()
     *      < 300 只否掉 AWB 统计的 **subwindow** 子功能（还只是打个 warning）。
     *      也就是说硬件 AWB 统计在本板上是可用的 —— **闭环 AWB 上线之后仍然
     *      不用它**，完整取舍见 cam_tune.h 文件头的「为什么不挂硬件 AWB 统计」。
     *      一句话版本：软件分通道均值已经每帧在算（帧统计顺带的，零额外成本），
     *      而硬件统计块能多给的那份「白点筛选」在本板上恰好残缺（subwindow 没有）
     *      且它的白点框本身要标定 —— 拿不准的参数换不来更可信的统计。
     *   **CCM 没有任何版本门**（isp_ccm.c 全文无 ESP_CHIP_REV_ABOVE），这正是
     *   下面拿它顶替用不了的 WBG 的前提；只是 rev < 3.0 的定点格式窄一些，
     *   系数上限 4.0 而非 16.0（hal/isp_ll.h:138-144）。
     *
     * ⓘ **曝光与白平衡都自己做，没有引 espressif/esp_ipa**（它会把 esp_video 的
     *   一半拖进来）：两个闭环都在 camera_csi_tune_tick() 里，控制律本体在
     *   cam_tune.c（纯逻辑、宿主机可测）—— AE 是带四道防振荡闸的 P 控制器，
     *   AWB 是灰世界 + 四道场景防护、经下面这个 CCM 施加增益。
     *   这两件事都没做的时候，实机现象正是「整体发绿 + 欠曝（亮度均值 45）」。
     * bayer 顺序取自 sc202cs_isp_info[0].bayer_type = ESP_CAM_SENSOR_BAYER_BGGR。
     * ⚠️ 只能按**名字**抄，不能按数值抄：两个枚举的顺序正好是反的
     *    （esp_cam_sensor_types.h 是 RGGB=0…BGGR=3，hal/color_types.h 是
     *     BGGR=0…RGGB=3）。数值直传的话红蓝会对调，而那种偏色一眼看不出是配错了。
     */
    const esp_isp_processor_cfg_t isp_cfg = {
        .clk_hz = CAM_ISP_CLK_HZ,
        .input_data_source      = ISP_INPUT_DATA_SOURCE_CSI,
        .input_data_color_type  = ISP_COLOR_RAW8,
        .output_data_color_type = ISP_COLOR_RGB565,
        .has_line_start_packet  = false,
        .has_line_end_packet    = false,
        .h_res = CAM_SENSOR_W,
        .v_res = CAM_SENSOR_H,
        .bayer_order = COLOR_RAW_ELEMENT_ORDER_BGGR,
    };
    s_st_isp = esp_isp_new_processor(&isp_cfg, &s_isp);
    ESP_RETURN_ON_ERROR(s_st_isp, TAG, "ISP");

#if CAM_AE_STAT_ENABLE
    /*
     * ══ 硬件 AE 5×5 分块统计 ══ **只建、只观测，不接管控制律**（T5）。
     *
     * 失败**只降级不拦启动**（与 LSC / gamma / CCM 同一处置）：统计块建不起来时
     * s_st_aestat 记下错误码、自检行照打，AE 继续吃软件均值 —— 取流本身是好的。
     */
    const esp_isp_ae_config_t ae_cfg = {
        /*
         * 官方 esp_video 把采样点**硬编码**为 AFTER_DEMOSAIC
         * （esp_video_isp_device.c:879）—— 即线性 RGB 亮度，**CCM 之前、gamma 之前**。
         * 这正是我们要的：官方那套 target=62 / 权重表 / 过曝欠曝阈值全部是在这个
         * 采样点上标定的，换个采样点那些数就不成立了。
         * 顺带一个结构性好处：AWB 改 CCM、gamma 换档都在它下游 ⇒ 扰不到 AE 的输入。
         */
        .sample_point = ISP_AE_SAMPLE_POINT_AFTER_DEMOSAIC,
        /*
         * ⚠️ 窗口**必须显式写**。isp_hal_ae_window_config() 把窗按 /5 分块：
         *   全零窗口能通过 esp_isp_new_ae_controller() 的参数校验（它只查
         *   btm_right >= top_left 且都 < 4095），但 bsize = 0 ⇒ 25 个块全是 0，
         *   现场表现为「统计跑着、数全是零」，最难归因的一种。
         * 写 1280×720 而不是 1279×719：/5 之后是 256×144，**整除**，不丢边缘 5 列。
         * 官方桥接层用的也是整幅传感器分辨率。
         */
        .window = { .top_left  = { .x = 0,            .y = 0 },
                    .btm_right = { .x = CAM_SENSOR_W, .y = CAM_SENSOR_H } },
        /*
         * ⚠️ 三个统计块（AE/AWB/AF）共用**一个** ISP 中断，intr_priority 必须与
         *   处理器一致。上面的 esp_isp_processor_cfg_t 没写这一项 ⇒ 零初始化
         *   ⇒ intr_priority = 0 ⇒ 这里也必须是 0。不一致时驱动走的是
         *   `ESP_GOTO_ON_ERROR(intr_priority != isp_proc->intr_priority, ...)`，
         *   **返回的是布尔 1 而不是 esp_err_t**，自检行会打出一个看不懂的码
         *   （esp_err_to_name(1) = "ESP_FAIL"，与真正的 ESP_FAIL 混在一起）。
         */
        .intr_priority = 0,
    };
    s_st_aestat = esp_isp_new_ae_controller(s_isp, &ae_cfg, &s_ae_ctlr);
    if (s_st_aestat == ESP_OK) {
        /* 只注册 on_env_statistics_done（AE_FDONE）。
         * ⓘ 不注册 on_env_change：环境突变检测的阈值我们从没设过
         *   （esp_isp_ae_controller_set_env_detector_threshold 没调），
         *   注册它等于给一个语义未定义的事件挂回调。 */
        const esp_isp_ae_env_detector_evt_cbs_t ae_cbs = {
            .on_env_statistics_done = cam_on_ae_stat,
        };
        s_st_aestat = esp_isp_ae_env_detector_register_event_callbacks(s_ae_ctlr, &ae_cbs, NULL);
    }
    if (s_st_aestat == ESP_OK) {
        /* enable 打开 AE 块并使能 AE 中断；**统计还没开始跑** ——
         * 连续统计要到 camera_csi_start() 里 start_continuous 才触发第一次。
         * 而且此刻 ISP 整体还没 esp_isp_enable()，硬件也无从产生统计。
         * ⇒ 「摄像头不取流时零影响」由这两层共同保证。 */
        s_st_aestat = esp_isp_ae_controller_enable(s_ae_ctlr);
    }
    if (s_st_aestat != ESP_OK)
        ESP_LOGW(TAG, "AE 硬件统计没建起来(%s)，AE 继续吃软件全帧均值，其余一切照常",
                 esp_err_to_name((esp_err_t)s_st_aestat));
#endif

#if CAM_LSC_ENABLE
    /*
     * ══ 镜头阴影校正（暗角）══ 官方 273 格 × 4 通道的标定表。
     *
     * ⚠️ **顺序有硬要求**：esp_isp_lsc_allocate_gain_array() 要求 lsc_fsm == INIT
     *   （isp_lsc.c），必须排在 esp_isp_lsc_enable() 之前 —— 这也是为什么整段放在
     *   init 里而不是取流之后。allocate 之后才轮到 configure（填表）与 enable。
     *
     * ⚠️ 网格数由 ISP 的 h_res/v_res 算出，不是我们定的：
     *      num_grids = (res − 1)/2/32 + 2  ⇒  x: 21，y: 13  ⇒  273
     *   与官方标定文件的 lsc_tbl_size **精确相等**（官方标定也是 1280×720，
     *   不需要重采样）。哪天换了传感器模式这个 273 会变、而标定表不会变，
     *   下面那条比对就是唯一会拦住它的地方 —— 不比对的话表会被错位填进 LUT，
     *   现象是「暗角修正的位置整体偏了」，几乎不可能反查到这里。
     *
     * 失败**只降级不拦启动**（与 CCM 同一处置）：LSC 配不上只是画面保留暗角，
     * 而取流本身是好的。
     */
    s_st_lsc = esp_isp_lsc_allocate_gain_array(s_isp, &s_lsc_gain, &s_lsc_n);
    if (s_st_lsc == ESP_OK && s_lsc_n != CAM_CAL_LSC_GRIDS) {
        ESP_LOGE(TAG, "LSC 网格数 %u 与标定表 %u 不符（ISP 分辨率变了？）",
                 (unsigned)s_lsc_n, (unsigned)CAM_CAL_LSC_GRIDS);
        s_st_lsc = ESP_ERR_INVALID_SIZE;
    }
    if (s_st_lsc == ESP_OK)
        s_st_lsc = camera_lsc_apply(CAM_LSC_SLOT_DEFAULT);
    if (s_st_lsc == ESP_OK)
        s_st_lsc = esp_isp_lsc_enable(s_isp);
    if (s_st_lsc != ESP_OK)
        /* ⚠️ ESP_ERR_NOT_SUPPORTED 只有一个含义：**这块板的 efuse 报的芯片版本
         *   低于 v1.0**（isp_lsc.c 的门是 ESP_CHIP_REV_ABOVE(rev,100)，而该宏是
         *   `(min) <= (rev)`，v1.0 ⇒ 100<=100 为真）。真拿到它就去 esptool.py
         *   chip_id 读实际版本，那会推翻本工程关于 LSC 的全部前提。 */
        ESP_LOGW(TAG, "LSC 没配上(%s)，画面保留四角暗角，其余一切照常",
                 esp_err_to_name((esp_err_t)s_st_lsc));
#endif

#if CAM_GAMMA_ENABLE
    /*
     * ══ gamma ══ 排在 LSC 之后、CCM 之前只是**书写顺序**，与硬件管线次序无关：
     * 三者都只是往各自的寄存器组里写参数，谁先写都一样。真正有顺序要求的只有
     * LSC 那三步（allocate → configure → enable，见上面）。
     *
     * 失败**只降级不拦启动**（与 LSC / CCM 同一处置）：gamma 配不上只是画面继续
     * 偏暗，而取流本身是好的。此时 s_gamma_ready 保持假 ⇒ 统计层拿到 NULL 逆表
     * ⇒ 画面是线性的、反馈量也按线性算，两侧仍然自洽。
     */
    s_st_gamma = camera_gamma_apply(CAM_GAMMA_SLOT);
    if (s_st_gamma == ESP_OK) {
        /* enable 有 FSM 门（重复调直接 ESP_ERR_INVALID_STATE），整个生命周期只调这一次。 */
        s_st_gamma = esp_isp_gamma_enable(s_isp);
        if (s_st_gamma != ESP_OK)
            s_gamma_ready = false;   /* 曲线写进去了但没使能 ⇒ 画面仍是线性的，别逆 */
    }
    if (s_st_gamma != ESP_OK)
        ESP_LOGW(TAG, "gamma 没配上(%s)，画面会明显偏暗（主机按 sRGB 解码线性图），"
                      "其余一切照常", esp_err_to_name((esp_err_t)s_st_gamma));
#endif

    /*
     * ══ 白平衡 ══ 用 **CCM 的对角线**顶替用不了的 WBG。
     *
     * 为什么非做不可：上面这条管线里 RAW→RGB 只有去马赛克一步，**没有任何一处
     * 对三个通道施加不同的增益**。而 Bayer 阵列 50% 是绿色像素、绿滤光片透过率
     * 也最高 ⇒ 不做白平衡的输出必然整体偏绿。这是管线的定义，不是「可能」。
     * 完整依据（含「为什么不是 bayer order 配错」的三条论证）见 cam_tune.h 文件头。
     *
     * 这里配的是**开机初值**（cam_tune.h 的静态标定常量）。CAM_AWB_ENABLE = 1 时
     * 闭环 AWB 会在取流后从这个初值出发接着调（camera_awb_tick）；= 0 时这就是
     * 最终值，行为与闭环上线之前完全一致。
     *
     * 失败**只降级不拦启动**：CCM 配不上只是画面继续发绿，而取流本身是好的 ——
     * 让一个画质改良把已经验证过的出图能力拖垮，是本末倒置。
     * ⓘ 失败时 s_ccm_r/s_ccm_b 保持初值，而硬件里其实是单位阵；这对判读没有影响，
     *   因为自检行第一格就是 CCM=<错误码>，看到它就该先修这个、别去读后面的数。
     */
#if CAM_AWB_ENABLE
    cam_awb_init(&s_awb);       /* 初值 = 同一对静态标定值，两边不会各说各话 */
#endif
    s_st_ccm = camera_ccm_apply(CAM_CCM_GAIN_R_MILLI, CAM_CCM_GAIN_B_MILLI);
    if (s_st_ccm == ESP_OK)
        s_st_ccm = esp_isp_ccm_enable(s_isp);
    if (s_st_ccm != ESP_OK)
        ESP_LOGW(TAG, "CCM 白平衡没配上(%s)，画面会整体发绿，其余一切照常",
                 esp_err_to_name(s_st_ccm));

    /*
     * ⚠️ **实测结论（与计划里的存疑处对应）：set_format 是必须的，不能省。**
     * sc202cs_detect() 只把 dev->cur_format 指向模式表里的那一项，**一个寄存器
     * 都没往芯片里写**（managed_components/.../sc202cs.c:1527 附近，detect 里只有
     * power_on + 读 ID）。真正把那张 1280×720 RAW8 寄存器表写下去的是
     * sc202cs_set_format()。不调它就 stream on，传感器还停在上电默认态，
     * CSI 收到的行数/格式全对不上 —— 现象是一帧都收不到或者花屏。
     * 传 NULL 让组件自己挑 CONFIG_CAMERA_SC202CS_MIPI_IF_FORMAT_INDEX_DEFAULT
     * 那一项，与 Task7 日志里打出来的默认模式是同一个，不必自己找 index。
     */
    s_st_fmt = esp_cam_sensor_set_format(s_sensor, NULL);
    ESP_RETURN_ON_ERROR(s_st_fmt, TAG, "传感器 set_format");

    /*
     * ══ 自动曝光的可调范围 ══ **一律运行时查，不写死。**
     *
     * 曝光上限跟着模式表的 VTS 走，增益表的长度与内容跟着 menuconfig 的
     * CONFIG_CAMERA_SC202CS_ABSOLUTE_GAIN_LIMIT 与增益优先策略走（本工程当前是
     * 数字增益优先那张表）。抄成常量必然在某次改配置时悄悄过期，而症状是
     * 「曝光调不动」或者更坏 —— 越界下标。
     *
     * ⚠️ 必须排在 set_format **之后**：传感器驱动是在那里才把它内部的
     *    exposure_max / 默认曝光/增益填好的（sc202cs.c:1346-1348）。
     *
     * 查不到就**关掉 AE**（s_ae_ready 保持 false），画面停在模式表的默认曝光上 ——
     * 与改动前的行为完全一致，不会比现在更坏。
     */
    esp_cam_sensor_param_desc_t d_exp = { .id = ESP_CAM_SENSOR_EXPOSURE_VAL };
    esp_cam_sensor_param_desc_t d_gain = { .id = ESP_CAM_SENSOR_GAIN };
    s_st_ae = esp_cam_sensor_query_para_desc(s_sensor, &d_exp);
    if (s_st_ae == ESP_OK)
        s_st_ae = esp_cam_sensor_query_para_desc(s_sensor, &d_gain);
    if (s_st_ae == ESP_OK && d_gain.enumeration.elements && d_gain.enumeration.count > 0 &&
        d_exp.number.minimum > 0 && d_exp.number.maximum >= d_exp.number.minimum) {
        s_ae_lim.exp_min    = (uint32_t)d_exp.number.minimum;
        s_ae_lim.exp_max    = (uint32_t)d_exp.number.maximum;
        s_ae_lim.gain_map   = d_gain.enumeration.elements;
        s_ae_lim.gain_count = d_gain.enumeration.count;
        /* 状态机的初值就是**芯片此刻的实际值** —— set_format 刚把这两个默认值写进去，
         * 所以状态与硬件天然一致，不必再多发一次 SCCB 去「同步」。 */
        cam_ae_init(&s_ae, &s_ae_lim, (uint32_t)d_exp.default_value,
                    (uint32_t)d_gain.default_value);
        s_ae_ready = true;
        ESP_LOGI(TAG, "AE 就绪：曝光 %" PRIu32 "~%" PRIu32 "（默认 %" PRIu32 "），"
                      "增益 %" PRIu32 " 档（%u.%03u×~%u.%03u×，上限按 cam_tune.h 压到 %u.%03u×），"
                      "目标亮度 %d",
                 s_ae_lim.exp_min, s_ae_lim.exp_max, s_ae.exposure, s_ae_lim.gain_count,
                 (unsigned)(s_ae_lim.gain_map[0] / 1000), (unsigned)(s_ae_lim.gain_map[0] % 1000),
                 (unsigned)(s_ae_lim.gain_map[s_ae_lim.gain_count - 1] / 1000),
                 (unsigned)(s_ae_lim.gain_map[s_ae_lim.gain_count - 1] % 1000),
                 (unsigned)(CAM_AE_GAIN_MAX_MILLI / 1000), (unsigned)(CAM_AE_GAIN_MAX_MILLI % 1000),
                 CAM_AE_TARGET);
    } else {
        if (s_st_ae == ESP_OK)
            s_st_ae = ESP_ERR_INVALID_RESPONSE;   /* 查成功了但内容不可用 */
        ESP_LOGW(TAG, "拿不到曝光/增益的可调范围(%s)，自动曝光关闭，"
                      "画面固定在模式表的默认曝光上", esp_err_to_name(s_st_ae));
    }

    ESP_LOGI(TAG, "CSI+ISP 就绪：%dx%d RAW8→RGB565，%d 块帧缓冲各 %u 字节"
                  "（共 %u KB PSRAM）；**尚未取流**",
             CAM_SENSOR_W, CAM_SENSOR_H, CAM_FB_COUNT, (unsigned)CAM_FB_BYTES,
             (unsigned)(CAM_FB_COUNT * CAM_FB_BYTES / 1024));
    return ESP_OK;
}

esp_err_t camera_csi_start(void)
{
    ESP_RETURN_ON_FALSE(s_cam && s_isp, ESP_ERR_INVALID_STATE, TAG, "CSI 未初始化");
    if (s_streaming)
        return ESP_OK;            /* 幂等 */

    /* 控制器先就位，传感器最后开：传感器一 stream on，MIPI 差分对就开始送数据，
     * 控制器没 start 的话那些数据无处可去（表现为 CSI 的 error 中断刷屏）。
     * 四步各自记进 s_st_start，失败时快照里能直接看出断在哪一步 ——
     * 「CSI enable 就没过」与「传感器 stream on 没写进去」的排查方向完全不同。 */
    int on = 1;
    esp_err_t err = esp_cam_ctlr_enable(s_cam);
    const char *step = "CSI enable";
    if (err == ESP_OK) { err = esp_isp_enable(s_isp);   step = "ISP enable"; }
    if (err == ESP_OK) { err = esp_cam_ctlr_start(s_cam); step = "CSI start"; }
    if (err == ESP_OK) {
        err = esp_cam_sensor_ioctl(s_sensor, ESP_CAM_SENSOR_IOC_S_STREAM, &on);
        step = "传感器 stream on";
    }
    s_st_start = err;
    if (err != ESP_OK) {
        /* 启动链断在某一步。把已经打开的东西按反序关掉，免得留下「控制器开着、
         * 传感器没开」这种半开状态 —— 那会在下一次 start 时以
         * ESP_ERR_INVALID_STATE 的形式重新冒出来，掩盖真正的根因。
         * 这三个 stop/disable 自身的返回值故意不看：此刻它们必然有一部分是
         * INVALID_STATE（本来就没开起来），看了反而盖掉上面那个真错误码。 */
        esp_cam_ctlr_stop(s_cam);
        esp_isp_disable(s_isp);
        esp_cam_ctlr_disable(s_cam);
        ESP_LOGE(TAG, "取流启动失败于「%s」(%s)", step, esp_err_to_name(err));
        return err;
    }

#if CAM_AE_STAT_ENABLE
    /*
     * 统计**只在取流时跑**（硬约束：摄像头不取流时零影响）。
     * 排在 esp_isp_enable() 成功之后：start_continuous 会立刻发一次
     * isp_ll_ae_manual_update() 触发第一帧统计，ISP 没使能时那一发是空放。
     * 建控制器失败时（s_st_aestat != ESP_OK）不碰这里 —— 句柄是 NULL。
     */
    if (s_st_aestat == ESP_OK) {
        s_st_aerun = esp_isp_ae_controller_start_continuous_statistics(s_ae_ctlr);
        if (s_st_aerun != ESP_OK)
            ESP_LOGW(TAG, "AE 连续统计没启动(%s)，25 块亮度会一直是 0",
                     esp_err_to_name((esp_err_t)s_st_aerun));
    }
#endif

    s_streaming = true;
    ESP_LOGI(TAG, "取流已开始（CSI 每秒往 PSRAM 写约 %u MB）",
             (unsigned)(CAM_FB_BYTES * 30 / (1024 * 1024)));
    return ESP_OK;
}

/* 记下第一个错误并把它念出来。停流的四步一个都不能早退，见下面的说明。 */
static void keep_first_err(esp_err_t *first, const char *what, esp_err_t rc)
{
    if (rc == ESP_OK)
        return;
    ESP_LOGW(TAG, "停流的「%s」失败(%s)，仍继续把剩下几步走完",
             what, esp_err_to_name(rc));
    if (*first == ESP_OK)
        *first = rc;              /* 后面的错误多半是第一个的连锁反应 */
}

esp_err_t camera_csi_stop(void)
{
    if (!s_streaming)
        return ESP_OK;            /* 幂等 */

    /*
     * 严格反序：先让传感器停止送数据，再停控制器。顺序反了会在 CSI 上留下半帧，
     * 下次 start 的第一帧是错位的。
     *
     * **四步一个都不能早退**：stop 的后置条件是「停下来了」，中途 return 会留下
     * 「控制器还开着但 s_streaming 已经是 false」这类半停状态，下一次 start 只会
     * 收到一个与根因无关的 INVALID_STATE。失败只记 warning、继续往下走，
     * 最终状态由 s_streaming = false 一锤定音。
     */
    esp_err_t err = ESP_OK;
    int off = 0;
    /* 逐条顺序展开，**不要**塞进数组初始化器里循环 —— C 不保证初始化器各表达式的
     * 求值顺序，而这四步的先后正是本函数的全部内容。 */
    keep_first_err(&err, "传感器 stream off",
                   esp_cam_sensor_ioctl(s_sensor, ESP_CAM_SENSOR_IOC_S_STREAM, &off));
    keep_first_err(&err, "CSI stop",    esp_cam_ctlr_stop(s_cam));
#if CAM_AE_STAT_ENABLE
    /* ⚠️ 必须排在 `ISP disable` **之前**：先让统计块停下来，再关 ISP。
     * 反过来的话 disable 之后还可能收到最后一次 AE 中断。
     * 顺序理由与既有四步停流一致（先停数据源，再关块），并同样 keep_first_err 记账。
     * 幂等由 s_streaming 那道闸保证：驱动的 FSM 门只允许 ENABLE↔CONTINUOUS 各一次。 */
    if (s_st_aestat == ESP_OK) {
        s_st_aerun = esp_isp_ae_controller_stop_continuous_statistics(s_ae_ctlr);
        keep_first_err(&err, "AE 统计 stop", (esp_err_t)s_st_aerun);
    }
#endif
    keep_first_err(&err, "ISP disable", esp_isp_disable(s_isp));
    keep_first_err(&err, "CSI disable", esp_cam_ctlr_disable(s_cam));
    s_streaming = false;

    /* 把所有缓冲收回空闲队列，让下一次 start 从确定的状态开始 ——
     * 否则残留在 done 队列里的旧帧会被下一次 get_frame() 当成新帧取走。 */
    if (s_held) {
        xQueueSend(s_free_q, &s_held, 0);
        s_held = NULL;
    }
    uint16_t *buf;
    while (xQueueReceive(s_done_q, &buf, 0) == pdTRUE)
        xQueueSend(s_free_q, &buf, 0);
    s_filling = NULL;
    s_reuse_pending = false;

    ESP_LOGI(TAG, "取流已停止（传感器进 sleep mode，不再占 PSRAM 带宽）");
    return err;
}

esp_err_t camera_csi_get_frame(const uint16_t **fb, uint32_t timeout_ms)
{
    ESP_RETURN_ON_FALSE(fb, ESP_ERR_INVALID_ARG, TAG, "fb 为空");
    ESP_RETURN_ON_FALSE(s_streaming, ESP_ERR_INVALID_STATE, TAG, "没在取流");

    /* 归还上一次交出去的那一块。**必须在等新帧之前做** —— 中断只在空闲队列里
     * 有货时才不用走抢缓冲的降级路径。 */
    if (s_held) {
        xQueueSend(s_free_q, &s_held, 0);
        s_held = NULL;
    }

    uint16_t *buf = NULL;
    if (xQueueReceive(s_done_q, &buf, pdMS_TO_TICKS(timeout_ms)) != pdTRUE) {
        s_get_timeouts++;
        return ESP_ERR_TIMEOUT;
    }

    /*
     * DMA 写完之后、CPU 读之前，必须把这块缓冲的 cache 行作废（M2C），
     * 否则读到的可能是上一轮遗留在 cache 里的旧内容。
     *
     * ⚠️ **这一步不能指望 CSI 驱动替我们做。** 驱动确实在中断里调了
     *    esp_cache_msync(trans.buffer, trans.received_size, M2C)，但那一行在
     *    `trans.received_size = fb_size_in_bytes` **之前**执行，此时 received_size
     *    还是 0（我们在 on_get_new_trans 里没有、也不该去设它）—— 长度 0 的
     *    invalidate 是个空操作。上游这个顺序问题不该由我们靠「刚好也能工作」
     *    去赌，在这里自己做一次，代价是一条硬件 invalidate 指令。
     */
    const esp_err_t err = esp_cache_msync(buf, CAM_FB_BYTES,
                                          ESP_CACHE_MSYNC_FLAG_DIR_M2C);
    ESP_RETURN_ON_ERROR(err, TAG, "帧缓冲 cache invalidate");

    s_held = buf;
    *fb = buf;
    return ESP_OK;
}

/* AE 走一拍：算出新的曝光/增益并经 SCCB 下发。
 * **只换反馈量的来源，控制律（四道防振荡闸）一行不动**，见 cam_tune.h 的 CAM_AE_SOURCE。 */
static void camera_ae_tick(const cam_frame_stats_t *st)
{
    (void)st;   /* CAM_AE_SOURCE = 1 时用不到软件统计 */
    if (!s_ae_ready)
        return;

#if CAM_AE_SOURCE
    /*
     * 硬件 5×5 加权测光。官方权重表 + 过暗/过亮块 quorum 剔除，
     * 归约逻辑在 cam_ae_weighted_mean()（纯逻辑，490 个宿主机用例守着）。
     */
    uint8_t blocks[25], lum = 0, nd = 0, nb = 0;
    if (cam_ae_stat_snapshot(blocks, &lum, &nd, &nb) == 0)
        return;   /* 统计块一帧都还没交付：这一拍不动，别拿全 0 去调曝光 */
#else
    /*
     * ⚠️ 喂进去的是 **lin_lum_mean**（逆 gamma 还原过的线性亮度），不是 lum_mean。
     * CAM_AE_TARGET 是线性域的量：gamma 是逐通道的凹函数，把线性 62 抬到 126，
     * 拿 gamma 域的均值去比 62 会让 AE 以为已经过曝一倍、把曝光一路往下压。
     * gamma 关着时两者逐位相等 ⇒ 这一行在两种构建下都对。
     */
    const uint8_t lum = st->lin_lum_mean;
#endif

    if (!cam_ae_step(&s_ae, lum, &s_ae_lim))
        return;   /* 没到更新周期 / 落在死区 / 已顶到限位：别去打扰 I2C 总线 */

    /*
     * 曝光与增益**一次调用一起下发**（ESP_CAM_SENSOR_GROUP_EXP_GAIN）。
     * 分两次发的话，两次之间会漏出一帧「新曝光 + 旧增益」的画面 —— 亮度跳一下，
     * 而 AE 下一拍恰好会把这一帧的亮度当成反馈，等于自己给自己注入扰动。
     * exposure_us 传 0 表示「用 exposure_val 这个原始寄存器值」（组件约定，
     * esp_cam_sensor_types.h:466-470）：我们的控制量本来就是寄存器域的，
     * 走 us 会多一次浮点往返换算，白白引入量化误差。
     *
     * ⓘ 代价：6 次 SCCB 写（曝光 3 + 增益 3），100 kHz 下约 2 ms，最快 300 ms
     *   一次 ⇒ 占这条共用 I2C 总线不到 1%。触摸那 20 ms 一次的轮询感觉不到。
     */
    const esp_cam_sensor_gh_exp_gain_t v = {
        .exposure_us  = 0,
        .exposure_val = s_ae.exposure,
        .gain_index   = s_ae.gain_index,
    };
    s_ae_last_err = esp_cam_sensor_set_para_value(s_sensor, ESP_CAM_SENSOR_GROUP_EXP_GAIN,
                                                  &v, sizeof(v));
    if (s_ae_last_err != ESP_OK)
        ESP_LOGW(TAG, "曝光/增益下发失败(%s)", esp_err_to_name((esp_err_t)s_ae_last_err));
}

#if CAM_AWB_ENABLE
/* AWB 走一拍：算出新的 R/B 增益并重配 CCM。控制律与全部防护判据在 cam_tune.c。 */
static void camera_awb_tick(const cam_frame_stats_t *st)
{
    /*
     * AE 是否已收敛 —— AWB 只在亮度稳定的窗口里采信颜色统计（理由见 cam_tune.h
     * 的 cam_awb_step）。
     * ⚠️ AE **关着**（查不到可调范围）时要传 true 而不是 false：那种情况下曝光
     *    恒定不变，亮度天然是稳的，正是最该采信统计的时候。传 false 会让 AWB
     *    永远一步不走，而且现场只看到「AE未稳」这个自相矛盾的理由。
     */
    const bool ae_stable = !s_ae_ready || cam_ae_converged(&s_ae);

    /*
     * ⓘ **T6 换了 AE 的测量口径，对 AWB 的影响只有一处：这个 ae_stable 的时机。**
     *   AWB 自己的输入（软件线性通道均值）与公式一个字都没动 ⇒ 行为等价。
     *   现场判据：自检行 AWB 那排「未更新：」直方图的分布应与 T5 时同量级，
     *   尤其 `AE未稳=` 不该暴涨。若它暴涨，说明官方那个非对称死区（−6/+2）
     *   在本板上太窄、AE 报不出收敛 —— 那时先看 AE 是不是在死区两侧来回跨，
     *   再决定是放宽 CAM_AE_TARGET_LOW/HIGH 还是退回 CAM_AE_SOURCE = 0。
     */

    /*
     * ⚠️ 四个反馈量全部取**线性域**那一份。灰世界算的是通道**比值**，而 gamma 是
     * 逐通道的幂律 ⇒ 它把比值压向 1（1.23 在 γ=0.605 档上被压成 1.135，−7.7%）
     * ⇒ 直接拿 gamma 域的均值去闭环，AWB 会**系统性地欠校正**，而且欠多少随
     * 画面亮度变化（幂律不是等比缩放）。逆回线性域之后 cam_awb_suggest() 的
     * 幂等性才继续成立。
     */
    if (cam_awb_step(&s_awb, st->lin_lum_mean, st->lin_r_mean, st->lin_g_mean,
                     st->lin_b_mean, ae_stable) != CAM_AWB_APPLIED)
        return;

    s_awb_last_err = camera_ccm_apply(s_awb.gain_r_milli, s_awb.gain_b_milli);
    if (s_awb_last_err != ESP_OK) {
        /*
         * ⚠️ 写不进去就**把状态机回滚到硬件里实际生效的那一对**。
         * 不回滚的话状态机以为增益已经变了、而画面反映的还是旧增益 —— 下一拍
         * 它会拿旧画面去校正新系数，cam_awb_suggest() 赖以成立的幂等性当场失效，
         * 表现为白平衡缓慢单向漂移。这条路径实际上走不到（系数被钳在 [1.0, 3.0]，
         * esp_isp_ccm_configure() 只在 NaN/超范围时失败），但「状态机必须永远
         * 镜像硬件」是个不该靠「反正失败不了」维持的不变式。
         */
        s_awb.gain_r_milli = s_ccm_r;
        s_awb.gain_b_milli = s_ccm_b;
        ESP_LOGW(TAG, "AWB 重配 CCM 失败(%s)，白平衡回滚到上一组系数",
                 esp_err_to_name((esp_err_t)s_awb_last_err));
    }
}
#endif

#if CAM_ADN_ENABLE
/*
 * BF（Bayer 域降噪）+ Demosaic 梯度比，按传感器总增益查官方表。
 *
 * 选它们打头阵的理由：这两级都**不改画面的平均亮度、也不改通道比值**
 * ⇒ AE 与 AWB 两个闭环的输入完全不变，是整条对齐路线上最安全的一步，
 * 用来验证「标定表 → ISP API」这条新通路本身是通的。
 */
static void camera_adn_tick(uint32_t gain_milli)
{
    const uint32_t bf = cam_map_gain_slot(cam_cal_bf_gain, CAM_CAL_BF_N, gain_milli);
    if (cam_slot_changed(&s_bf_track, bf, CAM_FEEDFWD_HYST_TICKS)) {
        esp_isp_bf_config_t cfg = {
            /* 官方桥接层一律用 SRND_DATA + tail valid 0/0：边缘用周围像素补，
             * 而不是补一个常数 —— 补常数会在画面四边留一圈被降噪算进去的假边。
             * 两个 tail valid 都写 0 是驱动约定的「整行 padding 都有效」。
             * ⚠️ **绝不能给 esp_isp_bf_configure() 传 NULL**：它在 else 分支之后
             *    仍然无条件求值 config->flags.update_once_configured（isp_bf.c），
             *    传 NULL 就是一次空指针解引用 —— 那不是「优雅地禁用」。要禁用
             *    这一级请用 CAM_ADN_ENABLE = 0。 */
            .padding_mode    = ISP_BF_EDGE_PADDING_MODE_SRND_DATA,
            .padding_data    = 0,
            .denoising_level = cam_cal_bf[bf].level,
            .padding_line_tail_valid_start_pixel = 0,
            .padding_line_tail_valid_end_pixel   = 0,
            /* 立刻写进硬件而不是等下一个 VSYNC。rev < 3.0 上影子寄存器本就是
             * 恒真的空桩，这一位在本板上无害；而重配已经被迟滞压到很低频。 */
            .flags = { .update_once_configured = 1 },
        };
        memcpy(cfg.bf_template, cam_cal_bf[bf].matrix, sizeof cfg.bf_template);
        s_st_bf = esp_isp_bf_configure(s_isp, &cfg);
        if (s_st_bf == ESP_OK && !s_bf_enabled) {
            /* enable 有 FSM 门（重复调直接 ESP_ERR_INVALID_STATE），只能成功一次。 */
            s_st_bf = esp_isp_bf_enable(s_isp);
            s_bf_enabled = (s_st_bf == ESP_OK);
        }
        s_feedfwd_reconf++;
    }

    const uint32_t dm = cam_map_gain_slot(cam_cal_demosaic_gain, CAM_CAL_DEMOSAIC_N, gain_milli);
    if (cam_slot_changed(&s_dm_track, dm, CAM_FEEDFWD_HYST_TICKS)) {
        /* grad_ratio 是 2 整数位 + 4 小数位（soc_caps.h）⇒ 步长 1/16。
         * 官方四档 1.5/1.25/1.05/1.0 ⇒ 1+8/16 / 1+4/16 / 1+1/16 / 1+0/16
         * （1.05 量化到 1.0625，这个 6% 的偏差比「不配、停在复位值」小得多）。 */
        uint32_t ip = 1, dp = 0;
        cam_map_to_fixed(cam_cal_demosaic[dm].grad_ratio_milli, 2, 4, &ip, &dp);
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
        s_feedfwd_reconf++;
    }
}
#endif  /* CAM_ADN_ENABLE */

#if CAM_AEN_ENABLE
/*
 * SHARP 锐化 + Color 对比度/饱和度，按传感器总增益查官方表。
 *
 * 这两级在 YUV 域，位于 AE（demosaic 后）与 AWB（CCM 前）两个**硬件**采样点的
 * 下游 —— 但我们今天的统计是软件采在 **ISP 输出**（这两级的下游），所以它们会
 * 进到 AE/AWB 的反馈里。量化评估（README 有完整推导）：
 *   · 饱和度钉在 128 = 1.000× ⇒ 逐像素恒等，对通道比值**零影响**（不是「影响小」）；
 *   · 对比度 132 = 1.031× 只作用在 Y 上（色度不动）⇒ 三个通道拿到的是**同一个**
 *     加性偏移 ⇒ 通道比值被拉向 1 的幅度 ≈ 0.7%，远小于 CAM_AWB_DEADBAND_PCT = 5。
 *     ⚠️ 亮度均值的**变化方向**取决于硬件用的是哪种对比度式子，而 TRM 与 IDF
 *        都没写死这一点：纯增益式 Y' = c·Y 会让 lum_mean 抬约 +3%；以 128 为轴的
 *        Y' = (Y−128)·c + 128 在偏暗画面上反而让它降约 0.4%。**两种都不超过
 *        CAM_AE_DEADBAND（12/120 = 10%）⇒ AE 多半连动都不动**，所以这里不需要
 *        分支处理；但上板读自检行时别把「亮度略降」当成配错了 —— 它只说明是
 *        后一种式子，把观察到的方向记进 README 即可（这是一处 [缺口] 的实测机会）。
 *   · 对比度按 gain 选档、gain 由 AE 定 ⇒ 存在 AE→gain→对比度→亮度→AE 的回路，
 *     但四档之间只差 1.5%，且换档有 3 拍迟滞，环增益远小于 1，不会自激。
 */
static void camera_aen_tick(uint32_t gain_milli)
{
    const uint32_t sh = cam_map_gain_slot(cam_cal_sharpen_gain, CAM_CAL_SHARPEN_N, gain_milli);
    if (cam_slot_changed(&s_sh_track, sh, CAM_FEEDFWD_HYST_TICKS)) {
        /* 两个系数是 3 整数位 + 5 小数位（soc_caps.h）⇒ 步长 1/32。
         * h = 1.625 恰好是 1+20/32（精确）；m = 1.525 → 1+17/32（差 0.4%）。
         * m_coeff 随增益单调下降（1.525 → 1.225）：高增益时减弱中频锐化，
         * 否则被放大的是噪声而不是细节。 */
        uint32_t hi = 1, hd = 0, mi = 1, md = 0;
        cam_map_to_fixed(cam_cal_sharpen[sh].h_coeff_milli, 3, 5, &hi, &hd);
        cam_map_to_fixed(cam_cal_sharpen[sh].m_coeff_milli, 3, 5, &mi, &md);
        esp_isp_sharpen_config_t cfg = {
            .h_freq_coeff = { .integer = hi, .decimal = hd },
            .m_freq_coeff = { .integer = mi, .decimal = md },
            .h_thresh     = cam_cal_sharpen[sh].h_thresh,
            .l_thresh     = cam_cal_sharpen[sh].l_thresh,
            .padding_mode = ISP_SHARPEN_EDGE_PADDING_MODE_SRND_DATA,
            .padding_data = 0,
            .padding_line_tail_valid_start_pixel = 0,
            .padding_line_tail_valid_end_pixel   = 0,
            .flags = { .update_once_configured = 1 },
        };
        memcpy(cfg.sharpen_template, cam_cal_sharpen[sh].matrix, sizeof cfg.sharpen_template);
        s_st_sharp = esp_isp_sharpen_configure(s_isp, &cfg);
        if (s_st_sharp == ESP_OK && !s_sharp_enabled) {
            s_st_sharp = esp_isp_sharpen_enable(s_isp);
            s_sharp_enabled = (s_st_sharp == ESP_OK);
        }
        s_feedfwd_reconf++;
    }

    const uint32_t ct = cam_map_gain_slot(cam_cal_contrast_gain, CAM_CAL_CONTRAST_N, gain_milli);
    if (cam_slot_changed(&s_ct_track, ct, CAM_FEEDFWD_HYST_TICKS)) {
        /* 对比度/饱和度是 1 整数位 + 7 小数位 ⇒ **128 就是 1.0×**。标定文件里的
         * 132/130/128/126 与 128/130 就是这个 val 的原值，**直接写、不换算**
         * （把 1.031 乘 1000 写进去会拿到 ESP_ERR_INVALID_ARG，上限是 255）。
         * ⓘ 色调：官方 SC202CS 标定里**没有 hue 字段**，写 0 就是对齐；顺带避开
         *   rev<3.0 只有 8 bit 色调（HAL 内部做 hue×256/360 折算）的精度坑。
         * ⓘ 亮度：同样不在标定里，写 0。 */
        s_contrast_val = cam_cal_contrast[ct].value;
        const esp_isp_color_config_t cfg = {
            .color_contrast   = { .val = s_contrast_val },
            .color_saturation = { .val = CAM_SATURATION_FIXED_VAL },
            .color_hue        = 0,
            .color_brightness = 0,
            .flags = { .update_once_configured = 1 },
        };
        s_st_color = esp_isp_color_configure(s_isp, &cfg);
        if (s_st_color == ESP_OK && !s_color_enabled) {
            /* ⓘ isp_core.c 那处 isp_ll_color_enable(true) 的 workaround（DIG-474）
             *   只在 **DVP** 输入时触发，我们是 CSI 输入 ⇒ 不触发，所以 color 块
             *   此刻确实停在 FSM 的 INIT 态。若拿到 ESP_ERR_INVALID_STATE，
             *   说明这条判断错了，回来改这段注释。 */
            s_st_color = esp_isp_color_enable(s_isp);
            s_color_enabled = (s_st_color == ESP_OK);
        }
        s_feedfwd_reconf++;
    }
}
#endif  /* CAM_AEN_ENABLE */

void camera_csi_tune_tick(const cam_frame_stats_t *st)
{
    /* samples == 0 表示这份统计什么都没采到（参数非法），拿它去调曝光/白平衡等于
     * 拿随机数当反馈 —— 与「采到了，结果是全黑」严格区分开。 */
    if (!st || st->samples == 0)
        return;

    /* 统计本身先留下来：即便 AE/AWB 都关着，分通道均值仍然是判断白平衡对不对的
     * 唯一客观手段，自检行必须能打出来。 */
    s_last_stats = *st;

    /*
     * **不取流就一步都不走。** 调用方（uvc_stream.c 的帧泵）只在 alt 1 下才拿得到
     * 帧，本来就不会走到这里；这一行是结构上的第二道保险 —— 「摄像头不取流时
     * 零影响」不该依赖调用方记得这件事。
     */
    if (!s_streaming)
        return;

    /* 顺序：**先 AE 后 AWB**。AWB 要读 cam_ae_converged()，让它读到的是本帧刚
     * 更新过的收敛状态，而不是上一帧的陈旧值。 */
    camera_ae_tick(st);
#if CAM_AWB_ENABLE
    camera_awb_tick(st);
#endif

#if CAM_ADN_ENABLE || CAM_AEN_ENABLE
    /*
     * 官方前馈级**排在 AE 之后**：它们按增益选档，要用本拍刚更新过的增益，
     * 而不是上一拍的陈旧值。
     *
     * AE 关着（查不到可调范围）时传感器停在模式表的默认增益，那就是增益表第 0 档
     * 1.000× ⇒ 这里填 1000 而不是 0。填 0 选出来的也是第 0 档、结果一样，但自检行
     * 会打出一个不存在的「0.000×」，把「AE 没起来」误报成「增益读错了」。
     */
    s_feedfwd_gain_milli = (s_ae_ready && s_ae.gain_index < s_ae_lim.gain_count)
                               ? s_ae_lim.gain_map[s_ae.gain_index] : 1000;
#if CAM_ADN_ENABLE
    camera_adn_tick(s_feedfwd_gain_milli);
#endif
#if CAM_AEN_ENABLE
    camera_aen_tick(s_feedfwd_gain_milli);
#endif
#endif
}

/*
 * 硬件 AE 5×5 统计的自检：**两行**。
 *
 * 第一行是归约后的量（能不能用、算出来多少、与软件口径差多少），第二行是 25 块
 * 原始值 —— 后者不是冗余：**「25 个数彼此不同」本身就是一条判据**，它证明分块
 * 统计的空间性是真的，而不是同一个全画面均值被复制了 25 份。
 *
 * 四种情况严格分开（与本文件其余自检行同一处置）：
 *   未编译      CAM_AE_STAT_ENABLE = 0 ⇒ 由 #else 分支说出来
 *   未运行      编译进来了但控制器一次都没建过（还没 camera_csi_init）
 *   <错误码>    建了、硬件或驱动拒了
 *   ESP_OK      建上了 ⇒ 同时打出帧计数、加权均值、两个 quorum 计数与 ρ
 *
 * 判读：
 *   帧=0 而取流中          → 连续统计没启动，看「运行=」那格（start 的返回值）。
 *   25 块**全是 0**        → 窗口 bsize=0。见 camera_csi_init() 里 ae_cfg 的 ⚠️。
 *   25 块全都相同的非零值   → 分块没生效（同上，或分辨率与窗口对不上）。
 *   遮住镜头 ⇒ 25 块全掉；只遮半边 ⇒ **只有一侧掉**（这条顺带把硬件的块排布
 *                          方向测出来，把结论记进 cam_on_ae_stat 的注释）。
 *   手电照中心 ⇒ 中心块冲到 250 以上、「亮块」计数涨到 3 以上。
 *   帧= 不涨而 CSI 帧在涨   → 忘了 start_continuous，或 enable 失败。
 *   帧= 涨得比 CSI 帧**快** → AE_ENV 事件也在触发重采（它的阈值我们没设过）。
 *                          不影响正确性（每次都是完整的一次统计），但 ρ 的
 *                          采样时刻会与画面统计错开，判读 ρ 时留意。
 *   alt 0（不取流）下帧= 还在涨 → stop 路径没停统计，看 camera_csi_stop()。
 *
 * ⚠️ **ρ 只在 AE 已收敛时才有意义**。曝光正在大幅调整时两个口径采的是不同瞬间的
 *   画面，比值会抖。反复三次遮挡/复原后 ρ 应当回到同一个值（±0.03）。
 *
 * ⓘ T6 之后 ρ 从「换目标的依据」变成了「推导的验算」：预测值 0.79 来自
 *   1/(0.30·kr + 0.586 + 0.113·kb) = 1/1.271（kr/kb 就是 CCM 对角线上那两个数，
 *   自检行「画质」那一格实时打着）。实测显著偏离 0.79 就说明这条推导错了 ——
 *   最可能的原因是硬件采样点其实不在 CCM 上游，那会直接推翻 CAM_AE_SOURCE
 *   那一整段论证，回来改它。
 */
#if CAM_AE_STAT_ENABLE
static void camera_ae_stat_report(void)
{
    uint8_t blocks[25], hw = 0, nd = 0, nb = 0;
    const uint32_t frames = cam_ae_stat_snapshot(blocks, &hw, &nd, &nb);

    /*
     * ρ = 硬件加权 / **软件线性**均值，×1000 的定点。
     *
     * ⚠️ 分母是 lin_lum_mean 而**不是** lum_mean：硬件采样点在 gamma 上游，本来
     *   就是线性量；拿 gamma 域均值当分母会把 γ=0.5 那条曲线的整体抬升（线性 62
     *   被编码成 126）算进去，得到一个凭空小一倍的假 ρ。
     *   （gamma 是在本计划里提前做掉的 —— 原计划 T5 写的「软件全帧」是 gamma
     *     上线之前的说法，直接照抄会错一倍。）
     * 分母为 0（画面全黑）时打 0，别除零。
     */
    const uint32_t lin = s_last_stats.lin_lum_mean;
    const uint32_t rho = lin ? (uint32_t)hw * 1000u / lin : 0;

    ESP_LOGI(TAG, "[自检] AE统计=%s 运行=%s 帧=%" PRIu32 " | 硬件加权=%u"
                  "（暗块 %u/%d 亮块 %u/%d）软件线性=%" PRIu32
                  " ρ=%" PRIu32 ".%03" PRIu32 "（=硬件/软件，预测 0.79）| AE 源=%s",
             step_str(s_st_aestat), step_str(s_st_aerun), frames,
             hw, nd, CAM_CAL_AE_LOW_REGIONS, nb, CAM_CAL_AE_HIGH_REGIONS,
             lin, rho / 1000, rho % 1000,
             CAM_AE_SOURCE ? "本统计（已接管）" : "软件线性（本统计只观测）");

    /* 25 块原始值，按 5 行打。缓冲 5×(5×4+3)+1 = 116，开 160 留足余量：
     * -Wformat-truncation 按 %3u 的类型上界估算，开小了会被 -Werror 打回。 */
    char row[160];
    int n = 0;
    for (int i = 0; i < 5; i++) {
        for (int j = 0; j < 5; j++)
            n += snprintf(row + n, sizeof row - (size_t)n, "%s%3u",
                          j ? " " : "", blocks[i * 5 + j]);
        if (i < 4)
            n += snprintf(row + n, sizeof row - (size_t)n, " |");
    }
    ESP_LOGI(TAG, "[自检] AE统计 25 块: %s", row);
}
#endif

/*
 * 画质自检：白平衡与曝光各一行。**这两行是判断画面对不对唯一的客观依据** ——
 * 「发绿」「太暗」是观感，R98/G121/B105、亮度均值 45 才是能拿来算系数的数字。
 */
static void camera_quality_report(void)
{
    /* ⚠️ 用**线性域**那一份：CCM 是线性域上的对角阵，而 gamma 会把通道比值压向 1
     * ⇒ 拿 gamma 后的均值反推出来的建议值会系统性偏小（欠校正），抄进
     * cam_tune.h 就把这个偏差固化了。gamma 关着时两份逐位相等。 */
    uint32_t sug_r = s_ccm_r, sug_b = s_ccm_b;
    cam_awb_suggest(s_last_stats.lin_r_mean, s_last_stats.lin_g_mean, s_last_stats.lin_b_mean,
                    s_ccm_r, s_ccm_b, &sug_r, &sug_b);

    /*
     * 判读：
     *   CCM!=ESP_OK               → 白平衡压根没生效，画面必然发绿，先修这个。
     *   通道均值 R<G>B 比例固定    → 白平衡还没调准。AWB 开着的话它会自己收敛
     *                               （看下一行的「已收敛」与下发次数）；AWB 关着
     *                               时把「建议」那两个数抄进 cam_tune.h 的
     *                               CAM_CCM_GAIN_R/B_MILLI 重编。
     *   拍红色物体时 B > R        → 这才是 bayer order 配错（红蓝对调），
     *                               改 camera_csi.c 上面 isp_cfg 的 bayer_order。
     *   三个均值相近（差 <5%）     → 白平衡到位，「建议」应当≈「当前」。
     * ⚠️ 只有 AE 收敛之后这几个数才有意义：曝光没稳的时候画面整体偏暗/偏亮，
     *    通道比例会被削顶与量化噪声带偏。（AWB 也正是因此才等 AE 收敛才动。）
     */
    ESP_LOGI(TAG, "[自检] 画质 CCM=%s 当前 R×%" PRIu32 ".%03" PRIu32 " G×%u.%03u"
                  " B×%" PRIu32 ".%03" PRIu32
                  " | 通道均值(线性) R%u G%u B%u → 建议 R×%" PRIu32 ".%03" PRIu32
                  " B×%" PRIu32 ".%03" PRIu32 "（对白纸/灰卡时才作数）",
             step_str(s_st_ccm),
             s_ccm_r / 1000, s_ccm_r % 1000,
             (unsigned)(CAM_CCM_GAIN_G_MILLI / 1000), (unsigned)(CAM_CCM_GAIN_G_MILLI % 1000),
             s_ccm_b / 1000, s_ccm_b % 1000,
             s_last_stats.lin_r_mean, s_last_stats.lin_g_mean, s_last_stats.lin_b_mean,
             sug_r / 1000, sug_r % 1000, sug_b / 1000, sug_b % 1000);

#if CAM_AWB_ENABLE
    /*
     * AWB 那一行。存在的理由是「颜色不对」有两种完全不同的病因，而它们在画面上
     * 长得一样：**AWB 没在动**（被某道防护挡着）与 **AWB 被场景带偏**（灰世界
     * 失效，动了但动错了）。所以这里必须同时给出三样东西：
     *   当前增益 + 是否收敛   →  它调到哪了、还动不动
     *   最近一拍的结论        →  这一瞬间为什么没动
     *   每种理由的累计次数    →  过去这段时间主要是被哪一条挡的
     *
     * 判读：
     *   下发=0 且 AE未稳=一大堆   → AE 一直没收敛（环境光在变？帧率太低？），
     *                              AWB 一步都走不了。先去看 AE 那一行。
     *   色偏过大 一直在涨          → **防护③正在起作用**：镜头对着单色物体
     *                              （红墙/绿植/蓝天）。这是**正确行为**，把镜头
     *                              转向普通场景，这个数就不涨了。
     *   暗场/过亮 在涨             → 环境光超出 [LUM_MIN, LUM_MAX]，加/减光。
     *   增益越界 在涨              → 灰世界推出来的系数跑出 [1.0, 3.0]：要么光源
     *                              极端（比如纯色 LED），要么 bayer order 配错了。
     *   死区内 在涨 + 已收敛       → **一切正常**，白平衡已经到位并稳住。
     *   下发一直涨、增益来回摆      → 振荡。调大 CAM_AWB_INTERVAL_TICKS 或减小
     *                              CAM_AWB_DAMP_NUM/DEN（都在 cam_tune.h）。
     */
    ESP_LOGI(TAG, "[自检] AWB=开 R×%" PRIu32 ".%03" PRIu32 " B×%" PRIu32 ".%03" PRIu32
                  " %s 下发=%" PRIu32 " 最近=%s(%s) | 未更新：AE未稳=%" PRIu32
                  " 暗场=%" PRIu32 " 过亮=%" PRIu32 " 色偏过大=%" PRIu32
                  " 未到周期=%" PRIu32 " 死区内=%" PRIu32 " 增益越界=%" PRIu32
                  " 量化无变化=%" PRIu32,
             s_awb.gain_r_milli / 1000, s_awb.gain_r_milli % 1000,
             s_awb.gain_b_milli / 1000, s_awb.gain_b_milli % 1000,
             cam_awb_converged(&s_awb) ? "已收敛" : "调整中",
             s_awb.updates, cam_awb_reason_str(s_awb.last), step_str(s_awb_last_err),
             s_awb.reasons[CAM_AWB_SKIP_AE], s_awb.reasons[CAM_AWB_SKIP_DARK],
             s_awb.reasons[CAM_AWB_SKIP_BRIGHT], s_awb.reasons[CAM_AWB_SKIP_CAST],
             s_awb.reasons[CAM_AWB_SKIP_PERIOD], s_awb.reasons[CAM_AWB_SKIP_BAND],
             s_awb.reasons[CAM_AWB_SKIP_RANGE], s_awb.reasons[CAM_AWB_SKIP_QUANT]);
#else
    ESP_LOGI(TAG, "[自检] AWB=关（CAM_AWB_ENABLE=0，白平衡钉在上面那对静态标定值上）");
#endif

    /*
     * 判读：
     *   AE=未运行 / 非 ESP_OK      → 自动曝光没起来，画面固定在默认曝光（会欠曝）。
     *   下发=0 且取流中             → 控制律一次都没动过：要么亮度一直落在死区
     *                                （那是好事），要么帧统计压根没送进来。
     *   亮度长期偏离目标而下发不涨   → **顶到限位了**：曝光已经是上限、增益已经是
     *                                cam_tune.h 的 CAM_AE_GAIN_MAX_MILLI ⇒ 环境
     *                                太暗，只能加光或抬那个上限（代价是噪声）。
     *   亮度在目标附近来回摆、下发一直涨 → 振荡。四道闸的调法见 cam_tune.h，
     *                                优先加大 CAM_AE_INTERVAL_TICKS 或减小阻尼。
     */
    const uint32_t gain_milli = (s_ae_ready && s_ae.gain_index < s_ae_lim.gain_count)
                                    ? s_ae_lim.gain_map[s_ae.gain_index] : 0;
    /* 「亮度=」打的是 s_ae.last_mean —— **AE 这一拍真正吃进去的那个数**，
     * 而不是重新算一遍。换源之后这一格与「源=」必须一起读：
     *   源=硬件5×5  这个数来自 demosaic 后的官方加权测光（CCM/WB 上游）
     *   源=软件线性  来自 ISP 输出的全帧抽样均值（CCM/WB 下游，逆 gamma 还原）
     * 两者相差约 1/ρ ≈ 1.27×（推导见 cam_tune.h 的 CAM_AE_SOURCE），
     * 把它们当同一个量比较是本阶段最容易犯的错。 */
    ESP_LOGI(TAG, "[自检] AE=%s 源=%s 曝光=%" PRIu32 "/%" PRIu32 " 增益=%u.%03u×(第 %" PRIu32 " 档)"
                  " 曝光量=%" PRIu32 " | 亮度 %u→目标 %d[%d,%d] %s 下发=%" PRIu32
                  " 最近=%s",
             step_str(s_st_ae),
             CAM_AE_SOURCE ? "硬件5×5(官方加权,demosaic后)" : "软件线性(全帧抽样,ISP输出)",
             s_ae.exposure, s_ae_lim.exp_max,
             (unsigned)(gain_milli / 1000), (unsigned)(gain_milli % 1000), s_ae.gain_index,
             s_ae.ev, s_ae.last_mean, CAM_AE_TARGET, CAM_AE_TARGET_LOW, CAM_AE_TARGET_HIGH,
             cam_ae_converged(&s_ae) ? "已收敛" : "调整中",
             s_ae.updates, step_str(s_ae_last_err));

#if CAM_AE_STAT_ENABLE
    camera_ae_stat_report();
#else
    ESP_LOGI(TAG, "[自检] AE统计=未编译（CAM_AE_STAT_ENABLE=0，不建 ISP AE 统计块、"
                  "不申请 ISP 中断；AE 只有软件全帧均值这一个口径）");
#endif
}

/*
 * 官方前馈画质级的自检：**每一级一行**，三级各自独立可读。
 *
 * 一级一行不是排版洁癖，是 bisect 的前提：三个开关分别管三级，现场把某一级关掉
 * 重编时，对应那行会变成「未编译」，另外两行原样 —— 一眼看出这一版关的是哪个。
 *
 * 每行都必须能分出四种情况（别用同一个哨兵表达其中两种）：
 *   未编译     开关 = 0，整段代码不在镜像里 ⇒ 由 #else 分支的那行说出来
 *   未运行     编译进来了但一次都没配过（还没取流，或取流后帧统计没送进来）
 *   <错误码>   配了、硬件拒了 ⇒ 打的是 esp_err_to_name()，直接可查
 *   ESP_OK     配上了 ⇒ 同时打出**此刻硬件里的关键参数值**，可与官方标定表逐个核对
 */
static void camera_feedfwd_report(void)
{
#if CAM_ADN_ENABLE
    /*
     * 判读：
     *   BF=未运行            → 还没取流，或帧统计没进 camera_csi_tune_tick()。
     *   BF=ESP_ERR_INVALID_ARG   → padding tail valid 参数不合法（两个都得是 0）。
     *   BF=ESP_ERR_INVALID_STATE → 重复调了 esp_isp_bf_enable()，看 s_bf_enabled。
     *   档号一直是 0 不动     → 增益没变（正常）或选档喂错了值：看「增益=」那格，
     *                          遮住镜头让 AE 顶到高增益，档号应当从 0 涨到 3~6、
     *                          level 从 2 涨到 8~10；开灯回落。
     *   前馈重配合计 一直涨   → 迟滞没起作用，调大 CAM_FEEDFWD_HYST_TICKS。
     *                          （它是各前馈级共用的**总**计数，不是本级的）
     */
    const uint32_t bf = s_bf_track.cur, dm = s_dm_track.cur;
    const uint32_t gr = cam_cal_demosaic[dm].grad_ratio_milli;
    uint32_t gi = 0, gd = 0;
    cam_map_to_fixed(gr, 2, 4, &gi, &gd);
    ESP_LOGI(TAG, "[自检] ADN=开 增益=%" PRIu32 ".%03" PRIu32 "× | "
                  "BF=%s 档%" PRIu32 "/%d level=%u 模板中心=%u | "
                  "Demosaic=%s 档%" PRIu32 "/%d grad=%" PRIu32 ".%03" PRIu32
                  "→%" PRIu32 "+%" PRIu32 "/16 | 前馈重配合计=%" PRIu32,
             s_feedfwd_gain_milli / 1000, s_feedfwd_gain_milli % 1000,
             step_str(s_st_bf), bf, CAM_CAL_BF_N,
             cam_cal_bf[bf].level, cam_cal_bf[bf].matrix[4],
             step_str(s_st_dm), dm, CAM_CAL_DEMOSAIC_N,
             gr / 1000, gr % 1000, gi, gd, s_feedfwd_reconf);
#else
    ESP_LOGI(TAG, "[自检] ADN=未编译（CAM_ADN_ENABLE=0，BF/Demosaic 停在寄存器复位值）");
#endif

#if CAM_LSC_ENABLE
    /*
     * 判读（**四角与中心那五个数是本级唯一能自证生效的东西**）：
     *   LSC=ESP_ERR_NOT_SUPPORTED → 芯片版本低于 v1.0，见 camera_csi_init() 里的 ⚠️。
     *   LSC=ESP_ERR_INVALID_SIZE  → 网格数 ≠ 273，ISP 分辨率变了。
     *   中心≈256(1.00×) 且四角 700~860 → 表填对了：LSC 就是「中心不动、四角提亮」。
     *   中心不是 256 / 四角不比中心大 → 表被当成衰减而不是增益，或档位填错。
     *   四个角的值彼此差很多、或某个角接近 256
     *                             → **排布顺序猜错了**（JSON 是 y 快变），
     *                               画面会表现为上下亮、左右暗 ⇒ 把 cam_tune.h 的
     *                               CAM_LSC_TRANSPOSE 改成 1 重编。
     *   实拍白墙：改动前四角/中心亮度比约 0.3~0.4，改动后差值应 < 15%。
     */
    const size_t c_mid = (CAM_CAL_LSC_GRID_Y / 2) * CAM_CAL_LSC_GRID_X + CAM_CAL_LSC_GRID_X / 2;
    const size_t c_tr  = CAM_CAL_LSC_GRID_X - 1;
    const size_t c_bl  = (CAM_CAL_LSC_GRID_Y - 1) * CAM_CAL_LSC_GRID_X;
    const size_t c_br  = c_bl + CAM_CAL_LSC_GRID_X - 1;
    ESP_LOGI(TAG, "[自检] LSC=开 %s 档%d(%uK) 网格 %d×%d=%u(驱动要 %u) 转置=%s | "
                  "R 增益 中心=%" PRIu32 " 四角=%" PRIu32 "/%" PRIu32 "/%" PRIu32
                  "/%" PRIu32 "（256=1.00×）",
             step_str(s_st_lsc), CAM_LSC_SLOT_DEFAULT,
             (unsigned)cam_cal_lsc_cct[CAM_LSC_SLOT_DEFAULT],
             CAM_CAL_LSC_GRID_X, CAM_CAL_LSC_GRID_Y, (unsigned)CAM_CAL_LSC_GRIDS,
             (unsigned)s_lsc_n, CAM_LSC_TRANSPOSE ? "是" : "否",
             s_lsc_gain.gain_r ? s_lsc_gain.gain_r[c_mid].val : 0,
             s_lsc_gain.gain_r ? s_lsc_gain.gain_r[0].val : 0,
             s_lsc_gain.gain_r ? s_lsc_gain.gain_r[c_tr].val : 0,
             s_lsc_gain.gain_r ? s_lsc_gain.gain_r[c_bl].val : 0,
             s_lsc_gain.gain_r ? s_lsc_gain.gain_r[c_br].val : 0);
#else
    ESP_LOGI(TAG, "[自检] LSC=未编译（CAM_LSC_ENABLE=0，画面保留四角暗角）");
#endif

#if CAM_AEN_ENABLE
    /*
     * 判读：
     *   Color=ESP_ERR_INVALID_ARG → val 超 255：多半是把 1.031 乘了 1000 写进去。
     *   画面整体发灰、对比度反而降低 → 把 132 当成百分数或做了 /128 的换算。
     *   遮镜头拉高增益 ⇒ SHARP 档 0→3、m 系数 1.525→1.225，对比度 132→126。
     *   高增益下噪点被锐化成明显颗粒 → 看 m 系数是否真的随增益降了（没降就是档没跟上）。
     *   边缘出现白边/黑边（过锐）  → h 系数的定点换算错了（整数位/小数位颠倒）。
     */
    const uint32_t sh = s_sh_track.cur;
    uint32_t hi = 0, hd = 0, mi = 0, md = 0;
    cam_map_to_fixed(cam_cal_sharpen[sh].h_coeff_milli, 3, 5, &hi, &hd);
    cam_map_to_fixed(cam_cal_sharpen[sh].m_coeff_milli, 3, 5, &mi, &md);
    ESP_LOGI(TAG, "[自检] AEN=开 增益=%" PRIu32 ".%03" PRIu32 "× | "
                  "SHARP=%s 档%" PRIu32 "/%d h阈=%u l阈=%u "
                  "h系数=%u.%03u→%" PRIu32 "+%" PRIu32 "/32 "
                  "m系数=%u.%03u→%" PRIu32 "+%" PRIu32 "/32 | "
                  "Color=%s 对比度=%u(%u.%03u×) 饱和度=%u(%u.%03u×，本阶段钉住) | "
                  "前馈重配合计=%" PRIu32,
             s_feedfwd_gain_milli / 1000, s_feedfwd_gain_milli % 1000,
             step_str(s_st_sharp), sh, CAM_CAL_SHARPEN_N,
             cam_cal_sharpen[sh].h_thresh, cam_cal_sharpen[sh].l_thresh,
             (unsigned)(cam_cal_sharpen[sh].h_coeff_milli / 1000),
             (unsigned)(cam_cal_sharpen[sh].h_coeff_milli % 1000), hi, hd,
             (unsigned)(cam_cal_sharpen[sh].m_coeff_milli / 1000),
             (unsigned)(cam_cal_sharpen[sh].m_coeff_milli % 1000), mi, md,
             step_str(s_st_color), s_contrast_val,
             (unsigned)(s_contrast_val * 1000u / 128u / 1000u),
             (unsigned)(s_contrast_val * 1000u / 128u % 1000u),
             (unsigned)CAM_SATURATION_FIXED_VAL,
             (unsigned)(CAM_SATURATION_FIXED_VAL * 1000u / 128u / 1000u),
             (unsigned)(CAM_SATURATION_FIXED_VAL * 1000u / 128u % 1000u),
             s_feedfwd_reconf);
#else
    ESP_LOGI(TAG, "[自检] AEN=未编译（CAM_AEN_ENABLE=0，不配 SHARP/Color）");
#endif

#if CAM_GAMMA_ENABLE
    /*
     * gamma 那一行。它要同时回答**三个**问题，缺一个现场就分不清病因：
     *   ① 硬件里到底是不是这条曲线      → 档号 + γ + 前向曲线的四个关键点
     *   ② 统计到底在哪个域算的          → 「统计域=」，以及逆表建了没有
     *   ③ 逆变换是不是真的对上了        → **线性均值与 gamma 后均值并排**
     *
     * ⚠️ ③ 是这次改动唯一能在现场证伪的判据，判读方式必须准确：
     *
     *   曲线 F 是**凹**的（段斜率单调下降，宿主机测试守着），由詹森不等式
     *       mean(F(p)) >= F(mean(p))
     *   ⇒ 打出来的「gamma后均值」必须 **>= F(线性均值)**（也一起打出来做参照），
     *     且在画面对比度不极端时两者相差不大（几级到十几级）。
     *   ⓘ 出厂钉住的第 0 档严格凹 ⇒ 这条不等式严格成立。官方 y 表是取整的，
     *     第 2 档有一处 1 级的斜率抖动（曲线离自己的上凸包最远 1.22 级）⇒ 将来
     *     动态换档到那一档时，判读留 1 级余量。
     *
     *   gamma后 ≈ 线性        → **逆表没生效**（或 gamma 根本没使能）：两个数应当
     *                          明显不同才对，相等说明统计域与画面域是同一个。
     *   gamma后 明显 < F(线性) → 逆表与硬件曲线**不同源**（档号对不上），这是最该
     *                          怕的一种：画面看着正常，但 AE/AWB 在拿偏移量闭环。
     *                          用错邻档的误差是十几级量级（宿主机测试 ⑦ 守着），
     *                          与上面那 1 级的舍入余量差着一个数量级，分得开。
     *   两者都≈0              → 画面真的全黑，先去看 CSI 那几行，不是 gamma 的事。
     *
     * ⓘ「线性均值」就是喂给 AE 的那个数，直接与「AE 目标」比较即可判断曝光够不够。
     */
    const uint8_t lin = s_last_stats.lin_lum_mean;
    ESP_LOGI(TAG, "[自检] GAMMA=%s 档%" PRIu32 "/%d(γ=%u.%03u) 前向 F(16)=%u F(64)=%u"
                  " F(128)=%u F(255)=%u | 统计域=%s | 亮度均值 线性=%u gamma后=%u"
                  "（应 >= F(线性)=%u）| 通道均值 线性 R%u G%u B%u / gamma后 R%u G%u B%u"
                  " | AE 目标=%d(线性域)",
             step_str(s_st_gamma), s_gamma_slot, CAM_CAL_GAMMA_N,
             (unsigned)(cam_cal_gamma_param_milli[s_gamma_slot] / 1000),
             (unsigned)(cam_cal_gamma_param_milli[s_gamma_slot] % 1000),
             cam_gamma_forward(s_gamma_slot, 16), cam_gamma_forward(s_gamma_slot, 64),
             cam_gamma_forward(s_gamma_slot, 128), cam_gamma_forward(s_gamma_slot, 255),
             s_gamma_ready ? "线性(逆表已建)" : "gamma 域(逆表未建，等同没开 gamma)",
             lin, s_last_stats.lum_mean, cam_gamma_forward(s_gamma_slot, lin),
             s_last_stats.lin_r_mean, s_last_stats.lin_g_mean, s_last_stats.lin_b_mean,
             s_last_stats.r_mean, s_last_stats.g_mean, s_last_stats.b_mean,
             CAM_AE_TARGET);
#else
    ESP_LOGI(TAG, "[自检] GAMMA=未编译（CAM_GAMMA_ENABLE=0，直出线性光 ⇒ 主机按 sRGB "
                  "解码会明显偏暗；统计与控制律同在线性域，逆变换一并旁路）");
#endif
}

void camera_csi_report(void)
{
    /*
     * 读法（从上往下，第一条不对的就是根因）：
     *   fb!=ESP_OK              → 1.84 MB × 3 的 PSRAM 分配或对齐不过关，与摄像头无关。
     *   ctlr!=ESP_OK            → CSI 控制器建不起来。lane 数/速率/分辨率参数问题，
     *                             或者 CSI 已被别的东西占了。
     *                             **ESP_ERR_NOT_SUPPORTED 特指一件事**：csi_cfg 的
     *                             input/output 颜色格式不相等，触发了桥的颜色转换，
     *                             而本板 P4 rev < 3.0 没有这个硬件块。曾经实机死在
     *                             这里一次，详见 csi_cfg 上面那段。
     *   cbs!=ESP_OK             → 回调注册被拒。几乎只可能是调用顺序错了。
     *   isp!=ESP_OK             → ISP 建不起来（时钟源/分辨率超上限）。
     *   fmt!=ESP_OK             → SCCB 写寄存器表失败：总线在探测之后掉了。
     *   start!=ESP_OK           → 前面全对，但 enable/start/stream-on 那一串断了。
     *   以上全 ESP_OK 但 帧=0    → 管线建起来了、传感器也 stream on 了，
     *                             但一帧数据都没到 —— 查 MIPI 走线/lane 速率。
     *   帧长不符 非零            → 驱动交回来的 received_size 与 CAM_FB_BYTES 对不上，
     *                             即 csi_cfg 的 output_data_color_type 理解错了。
     *                             此时**这些帧一律不交出去**，所以「帧」不会涨 ——
     *                             两个数要一起看才分得清「没数据」和「数据长度不对」。
     *   帧在涨                   → 取到了。**此时才轮到看亮度那几行**判断内容对不对。
     * 「未运行」与任何一个错误码严格区分开，见 STEP_NOT_RUN 的声明。
     */
    ESP_LOGI(TAG, "[自检] CSI fb=%s ctlr=%s cbs=%s isp=%s fmt=%s start=%s | "
                  "取流中=%d 帧=%" PRIu32 " 抢缓冲=%" PRIu32 " 丢弃=%" PRIu32
                  " 取帧超时=%" PRIu32 " 帧长不符=%" PRIu32 "(实收 %" PRIu32
                  "，应为 %u)",
             step_str(s_st_fb), step_str(s_st_ctlr), step_str(s_st_cbs),
             step_str(s_st_isp), step_str(s_st_fmt), step_str(s_st_start),
             s_streaming, s_frames_done, s_frames_reused, s_frames_dropped,
             s_get_timeouts, s_size_mismatch, s_last_size,
             (unsigned)CAM_FB_BYTES);

    /* 画质那两行紧跟其后：上面那行说的是「有没有帧」，它们说的是「帧对不对」，
     * 顺序就是排查顺序 —— 没帧的时候画质数字一律不必看。 */
    camera_quality_report();

    /* 官方前馈画质级排在最后：它们既不影响「有没有帧」，也不参与 AE/AWB
     * 两个闭环的控制律，是纯前向的画质级 —— 前面两组都正常了才轮到看它们。 */
    camera_feedfwd_report();
}

/* ══ PSRAM 读带宽实测 ══════════════════════════════════════════════ */

/*
 * 存在的理由：这条链路最大的风险是「CSI 每秒往 PSRAM 写 55 MB」＋「PPA 每秒读
 * 18 MB / 写 4.6 MB」＋「JPEG 编码器的读写」，把 DPI 面板刷新（每秒从 PSRAM 读
 * 89～107 MB，算式见 camera_csi.h）挤出撕裂/花屏，而**肉眼看屏幕不是判据** ——
 * 轻微的带宽紧张肉眼看不出来，等看得出来时已经说不清是不是别的原因。
 * 这里量的是「同一时刻 CPU 还能从 PSRAM 读多快」：不取流 / 取流+缩放+编码 /
 * 停流后各测一次，差值就是这条链路实际吃掉的那一份带宽，是个能写进报告的数字。
 *
 * ⓘ Task8 时它长在那个临时自检任务里（那个任务连同它 120 秒强制取流的行为
 *   已随 Task9 删掉）；**量本身保留**，改由 uvc_stream.c 在真实链路的三个时点
 *   各调一次 —— 观测设施跟着被观测对象走。
 *
 * 做法：从帧缓冲里连续读 1 MB 到内部 SRAM。读的区间远大于 cache，每条 cache line
 * 都真的要去 PSRAM 取；目的地常驻 cache，测到的就是**读**带宽。
 * 读的内容是什么无所谓（正在被 DMA 写也没关系），所以直接借 s_fb[0]。
 *
 * ⚠️ 它自己要读 1 MB PSRAM（约 10 ms），**是个有代价的观测**，只能在明确的时点
 *    调，不能每帧调 —— 否则它就成了被观测的干扰源。
 */
#define CAM_BW_CHUNK   1024
#define CAM_BW_TOTAL   (1024 * 1024)

uint32_t camera_csi_psram_read_mbps(void)
{
    if (!s_fb[0])
        return 0;
    uint8_t *sink = heap_caps_malloc(CAM_BW_CHUNK, MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT);
    if (!sink)
        return 0;

    const uint8_t *src = (const uint8_t *)s_fb[0];
    const int64_t t0 = esp_timer_get_time();
    for (size_t off = 0; off < CAM_BW_TOTAL; off += CAM_BW_CHUNK)
        memcpy(sink, src + off, CAM_BW_CHUNK);
    const int64_t dt = esp_timer_get_time() - t0;

    heap_caps_free(sink);
    /* 字节/微秒 == MB/s（都按 1e6 算，量级判断够用，不必纠结 MiB） */
    return dt > 0 ? (uint32_t)(CAM_BW_TOTAL / dt) : 0;
}
