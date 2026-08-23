/*
 * SC202CS 的 SCCB 探测 + MIPI-CSI/ISP 取流，以及**官方 esp_ipa 算法所需的硬件统计**。
 *
 * ⚠️ **画质算法本体不在这里，在 cam_ipa.c**（= 官方闭源 esp_ipa）。本文件只负责
 *   两件事：把三块硬件统计（AE 5×5 / AWB 白点 / 直方图）建起来并读出来，
 *   以及把它们填成 esp_ipa_stats_t 交给 cam_ipa_process()。**一行控制律都没有。**
 *
 * 此前这里有一整套自研的 AE/AWB/CCM/gamma 控制律（cam_tune.c + cam_isp_map.c +
 * cam_isp_cal.h），已随本次返工**全部删除** —— 它们建立在「引 esp_ipa 会把
 * esp_video + usb_host_uvc + esp_h264 拖进来」这个错误判断上，而实测依赖方向
 * 是反的。取舍与依据见 cam_ipa.h 的文件头。
 *
 * 实现说明见 camera_csi.h。
 */
#include "camera_csi.h"
#include "board_power.h"
#include "cam_ipa.h"
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
#include "driver/isp_ae.h"      /* 硬件 5×5 分块测光（isp_ae.c 全文无 ESP_CHIP_REV_ABOVE） */
#include "driver/isp_awb.h"     /* 硬件白点统计（isp_awb.c 的版本门只否掉 subwindow） */
#include "driver/isp_hist.h"    /* 直方图统计（isp_hist.c 全文无 ESP_CHIP_REV_ABOVE） */
#include "esp_cache.h"
#include "esp_heap_caps.h"
#include "esp_timer.h"

/*
 * ══ 整条 esp_ipa 路的总开关 ═══════════════════════════════════════
 *
 * CONFIG_AIO_CAM_IPA（Kconfig.projbuild，**默认开**）。关掉时：
 *   · 三块硬件统计照常建、照常跑（它们是观测设施，自检行仍然有数可看）；
 *   · 但**不建 IPA pipeline、不下发任何 metadata** ⇒ ISP 停在
 *     esp_isp_new_processor() 给的基础配置上：只做 RAW8→RGB565 去马赛克，
 *     没有 CCM、没有 gamma、没有 LSC、没有降噪/锐化，曝光与增益固定在
 *     传感器模式表的默认值上。
 *   · 画面预期：**整体发绿**（Bayer 50% 是绿像素、绿滤光片透过率也最高，而
 *     管线里没有任何一处对三通道施加不同增益）、**明显偏暗**（直出线性光，
 *     主机按 sRGB 解码）、**四角有暗角**（无 LSC）、曝光不随环境变化。
 *     这是一个「能启动、能出图」的最小可用状态，专用于把画质问题与
 *     取流/USB 问题分开 —— 不是产品形态。
 */
#ifdef CONFIG_AIO_CAM_IPA
#define CAM_IPA_ENABLE 1
#else
#define CAM_IPA_ENABLE 0
#endif

static const char *TAG = "camera";

/* 把宏的**值**变成字符串字面量（两级展开，缺一级会得到宏名本身）。
 * 自检行里凡是「门限是多少」这种数，宁可让预处理器去拼，也不要在格式串里
 * 手抄一遍 —— 手抄的那份迟早会与宏走岔，而现场看到的是那份手抄的。 */
#define CAM_STR_(x)  #x
#define CAM_STR(x)   CAM_STR_(x)

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

/*
 * SCCB io 句柄。**提成文件级静态是 T7 唯一的结构性改动**：黑电平那件事要在
 * set_format 之后直接读/写传感器的 0x3902，而 esp_cam_sensor 的公开接口里
 * 没有「透传一次寄存器访问」的口子，只能自己留着这个句柄。
 * 探测失败时不删它（纯软件对象，十几字节），留着让自检行还有东西可查。
 */
static esp_sccb_io_handle_t s_sccb;

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
    s_st_sccb = sccb_new_i2c_io(board_i2c_bus(), &sccb_cfg, &s_sccb);
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
    s_st_pid_rd = esp_sccb_transmit_receive_reg_a16v8(s_sccb, SC202CS_REG_PID_H, &pid_h);
    if (s_st_pid_rd == ESP_OK)
        s_st_pid_rd = esp_sccb_transmit_receive_reg_a16v8(s_sccb, SC202CS_REG_PID_L, &pid_l);
    if (s_st_pid_rd == ESP_OK)
        s_pid = (int32_t)(((uint16_t)pid_h << 8) | pid_l);

    esp_cam_sensor_config_t cfg = {
        .sccb_handle  = s_sccb,
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


/* ══ 黑电平：传感器自带 BLC 的**观测**（读一次，不写）══
 *   s_st_blc_rd  读 0x3902 的返回值
 *   s_blc_before 读回的值，−1 = 一个字节都没读到（与读回 0x00 严格区分）
 *
 * ⓘ 只读不写。官方标定文件里的 acc.blc（四通道偏移 16）走的是 ISP 的 BLC 块，
 *   而本板 rev v1.0 没有那个块 —— cam_ipa.c 会收到 IPA_METADATA_FLAGS_BLC
 *   并忽略它（见那里 CAM_IPA_HAS_BLC 的推理）。于是「传感器自己的 BLC 开没开」
 *   就成了判断暗部基座的唯一现场依据，值得留着这一次读：
 *     读回 0xc0 ⇒ 开着 ⇒ 基座应当已经 ≈ 0；
 *     读回 0x80 ⇒ 关着 ⇒ 预期基座 ≈ 16，与官方 acc.blc 的 16 精确吻合。
 */
#define CAM_SENSOR_BLC_REG  0x3902
static int32_t s_st_blc_rd  = STEP_NOT_RUN;
static int32_t s_blc_before = -1;

#if CAM_IPA_ENABLE
/*
 * IPA 节拍任务的句柄。**提到这里**只有一个理由：唤醒动作发生在下面那个 AE
 * 统计的 ISR 回调里，而任务体本身在文件下半部、紧挨着它消费的
 * cam_fill_ipa_stats（那里有「为什么要单开一个任务」的完整推理）。
 * NULL = IPA 没起来（或任务没建成）⇒ ISR 不唤醒任何人。
 */
static TaskHandle_t s_ipa_task;
static void cam_ipa_task_start(void);
#endif

/* ══ 硬件 AE 5×5 分块统计 ══════════════════════════════════════════
 * 官方 esp_ipa 的 agc/ian 两个模块吃的就是这 25 个块（esp_ipa_stats_t.ae_stats）。
 * 采样点 AFTER_DEMOSAIC 与官方 esp_video 硬编码的那个**必须一致** ——
 * 官方 agc.luma_adjust 的 target=62、25 个权重、过曝欠曝阈值全部是在这个
 * 采样点上标定的，换个采样点那些数就不成立了。 */
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
 * ⓘ 它同时是**整条 IPA 的节拍源**：搬完 25 字节之后给 cam_ipa_task 发一条
 *   任务通知，process() 就在那个任务里跑。ISR 侧只有「给通知」这一个动作，
 *   重活（填 esp_ipa_stats_t、跑 blob、下发 I2C）一件都不在这里。
 *   选 AE 而不是 AWB/直方图当拍子的理由写在 cam_ipa_task 上方。
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

#if CAM_IPA_ENABLE
    /* 通知计数式唤醒：任务侧用 ulTaskNotifyTake(pdTRUE) 一次取走全部计数，
     * 取回的数就是「这一拍之前积了几份统计」—— 那正是判断有没有丢统计的依据。 */
    BaseType_t woken = pdFALSE;
    if (s_ipa_task)
        vTaskNotifyGiveFromISR(s_ipa_task, &woken);
    /* 返回 true ⇒ ISP 的 ISR 出口做一次 portYIELD_FROM_ISR（isp_ae.c 的
     * need_yield 是把各回调的返回值或起来的），让节拍任务立刻拿到 CPU。 */
    return woken == pdTRUE;
#else
    return false;
#endif
}

/* 取一份 25 块的快照。**不做任何归约** —— 加权、剔除过暗/过亮块这些事全部由
 * 官方 blob 按 agc.luma_adjust 的权重表去做，我们再算一遍只会得到第二个口径。
 * 返回统计块至今交付过多少帧（0 = 一帧都没收到 ⇒ 这份数不能用，
 * 拿全 0 喂 blob 会让它把曝光一路推到顶）。 */
static uint32_t cam_ae_stat_snapshot(uint8_t blocks[25])
{
    uint32_t frames;
    portENTER_CRITICAL(&s_ae_lock);
    memcpy(blocks, s_ae_blocks, 25);
    frames = s_ae_stat_frames;
    portEXIT_CRITICAL(&s_ae_lock);
    return frames;
}

/* ══ 硬件 AWB 白点统计 ═════════════════════════════════════════════
 * 官方 esp_ipa 的 awb 模块吃的就是这四个累加值（esp_ipa_stats_t.awb_stats[0]）。
 * 采样点 BEFORE_CCM 与官方 esp_video 硬编码的那个一致。
 *
 * ⚠️ **从 oneshot 改成连续模式 + ISR 回调**（本次返工改的）。原先每秒一次的
 *   oneshot 会在帧泵任务里阻塞最坏 60 ms；而官方要求「每拿到一份统计就调一次
 *   process()」，若三块统计都走 oneshot，一拍就要阻塞 120 ms，直接把 100 ms 的
 *   帧泵节拍撑爆（表现为 fps 掉到 8 以下、UVC「拒收」立刻非零）。
 *   连续模式下 ISR 每帧填一次，任务侧只做一次 16 字节的快照，**零阻塞**。
 * ⓘ subwindow 在 rev < 3.0 上不可用，我们不配、也不置 IPA_STATS_FLAGS_AWB_SUBWIN。 */
static isp_awb_ctlr_t s_awb_ctlr;
static int32_t        s_st_awbstat = STEP_NOT_RUN;  /* 建控制器 / 注册回调 / 使能 */
static int32_t        s_st_awbrun  = STEP_NOT_RUN;  /* start/stop 连续统计的返回值 */

static portMUX_TYPE s_awb_lock = portMUX_INITIALIZER_UNLOCKED;
static uint32_t s_awb_counted, s_awb_sum_r, s_awb_sum_g, s_awb_sum_b;
static uint32_t s_awb_stat_frames;

/* ⚠️ 跑在 ISR 上下文，只搬四个 32 位数。不加 IRAM_ATTR 的理由同 cam_on_ae_stat。 */
static bool cam_on_awb_stat(isp_awb_ctlr_t h, const esp_isp_awb_evt_data_t *e, void *ud)
{
    (void)h;
    (void)ud;
    portENTER_CRITICAL_ISR(&s_awb_lock);
    s_awb_counted = e->awb_result.white_patch_num;
    s_awb_sum_r   = e->awb_result.sum_r;
    s_awb_sum_g   = e->awb_result.sum_g;
    s_awb_sum_b   = e->awb_result.sum_b;
    s_awb_stat_frames++;
    portEXIT_CRITICAL_ISR(&s_awb_lock);
    return false;
}

static uint32_t cam_awb_stat_snapshot(uint32_t *counted, uint32_t *r, uint32_t *g, uint32_t *b)
{
    uint32_t frames;
    portENTER_CRITICAL(&s_awb_lock);
    *counted = s_awb_counted;
    *r = s_awb_sum_r;
    *g = s_awb_sum_g;
    *b = s_awb_sum_b;
    frames = s_awb_stat_frames;
    portEXIT_CRITICAL(&s_awb_lock);
    return frames;
}
/*
 * ══ 直方图统计 ══ 官方 esp_ipa 的 ian 模块靠它重建 env.luma
 * （= 环境亮度，gamma 选档与 CCM 低照度分支的索引量）。
 *
 * 它给出 AE 的 5×5 测光给不出的东西：**近似均匀加权**的场景均值与亮/暗块分布。
 * AE 那张中心加权金字塔答的是「主体够不够亮」，直方图答的是「环境有多亮」——
 * 官方把它们分成两张表（ian.luma.ae.weight 与 ian.luma.env.weight）正是为了
 * 让 gamma 不跟着测光抖。
 *
 * ⚠️ 与 AWB 同一处置：**连续模式 + ISR 回调**，不用 oneshot。理由见上面 AWB
 *   那一段（三块统计都阻塞的话一拍要 120 ms，撑爆 100 ms 的帧泵节拍）。
 */
static isp_hist_ctlr_t s_hist_ctlr;
static int32_t  s_st_hist    = STEP_NOT_RUN;   /* 建控制器 / 注册回调 / 使能 */
static int32_t  s_st_histrun = STEP_NOT_RUN;   /* start/stop 连续统计的返回值 */

static portMUX_TYPE s_hist_lock = portMUX_INITIALIZER_UNLOCKED;
static uint32_t s_hist_bins[ISP_HIST_SEGMENT_NUMS];
static uint32_t s_hist_stat_frames;

/* ⚠️ 跑在 ISR 上下文，只搬 16 个 32 位数。 */
static bool cam_on_hist_stat(isp_hist_ctlr_t h, const esp_isp_hist_evt_data_t *e, void *ud)
{
    (void)h;
    (void)ud;
    portENTER_CRITICAL_ISR(&s_hist_lock);
    for (int i = 0; i < ISP_HIST_SEGMENT_NUMS; i++)
        s_hist_bins[i] = e->hist_result.hist_value[i];
    s_hist_stat_frames++;
    portEXIT_CRITICAL_ISR(&s_hist_lock);
    return false;
}

static uint32_t cam_hist_stat_snapshot(uint32_t bins[ISP_HIST_SEGMENT_NUMS])
{
    uint32_t frames;
    portENTER_CRITICAL(&s_hist_lock);
    memcpy(bins, s_hist_bins, sizeof s_hist_bins);
    frames = s_hist_stat_frames;
    portEXIT_CRITICAL(&s_hist_lock);
    return frames;
}

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
     *      硬件 AWB 统计在本板上是可用的，下面就在建它 —— 它是官方 awb 算法的输入。
     *   **CCM 没有任何版本门**（isp_ccm.c 全文无 ESP_CHIP_REV_ABOVE），这正是
     *   cam_ipa.c 拿它顶替用不了的 WBG 的前提；只是 rev < 3.0 的定点格式窄一些，
     *   系数上限 4.0 而非 16.0（hal/isp_ll.h:138-144）。
     *
     * ⓘ **画质算法一律走官方 esp_ipa**（cam_ipa.c）：CCM / gamma / BF / 锐化 /
     *   demosaic / LSC / 色彩 / 曝光 / 增益全部由它算，本文件只建统计块并转发。
     *   这些都没做的时候，实机现象正是「整体发绿 + 欠曝（亮度均值 45）」——
     *   也正是 CONFIG_AIO_CAM_IPA 关掉时的预期画面。
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

    /*
     * ══ 硬件 AE 5×5 分块统计 ══ 官方 esp_ipa 的 agc/ian 模块的输入。
     *
     * 失败**只降级不拦启动**：统计块建不起来时 s_st_aestat 记下错误码、自检行
     * 照打，blob 收不到 AE 统计（IPA_STATS_FLAGS_AE 不置位）⇒ 曝光不再自适应，
     * 但取流本身是好的。
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
        ESP_LOGW(TAG, "AE 硬件统计没建起来(%s)，曝光不再自适应，其余一切照常",
                 esp_err_to_name((esp_err_t)s_st_aestat));

    /*
     * ══ 硬件 AWB 白点统计 ══ 用官方标定的白点筛选框，喂官方 awb 模块。
     *
     * 失败**只降级不拦启动**：建不起来时 IPA_STATS_FLAGS_AWB 不置位 ⇒ blob 的
     * 白平衡停在初值（画面会保持一个固定的偏色），取流本身是好的。
     */
    const esp_isp_awb_config_t awb_cfg = {
        /*
         * ⚠️⚠️ **CCM 之前**，与官方 esp_video 硬编码的采样点一致。
         * 这一个字段决定了 blob 拿到的是什么：统计**不穿过**被控块（CCM），
         * 于是它给出的 red_gain/blue_gain 是**绝对值**而不是增量 ——
         * cam_ipa.c 的 config_ccm() 正是按这个语义把它们右乘进 CCM 的。
         * 换成 AFTER_CCM 会让整条白平衡变成正反馈。
         */
        .sample_point = ISP_AWB_SAMPLE_POINT_BEFORE_CCM,
        /*
         * ⚠️ 窗口**必须显式写**（与 AE 同一个坑）：全零窗能通过
         *   esp_isp_new_awb_controller() 的参数校验，但它表达的是「左上角那一个
         *   像素」⇒ counted 恒为 0 或 1，现场表现是「统计跑着、白点数几乎恒为 0」。
         * ⚠️ 与 AE 那边写 1280/720 **不同，这里写 1279/719**：AWB 的窗口
         *   （isp_hal_awb_set_window_range → isp_ll_awb_set_window_range）是把
         *   左上/右下四个坐标**原样**写进 lpoint/rpoint 寄存器的**闭区间**，
         *   不做 AE 那样的 /5 分块。写 1280 就多要了一列不存在的像素。
         */
        .window = { .top_left  = { .x = 0,               .y = 0 },
                    .btm_right = { .x = CAM_SENSOR_W - 1, .y = CAM_SENSOR_H - 1 } },
        /*
         * ⚠️ subwindow 在 rev < 3.0 上不可用（驱动打个 warning 就跳过配置），
         *   我们**不配**，留零 —— 主窗那四个累加值就是全部可用信息。
         *   零初始化正是驱动认定「没配 subwindow」的判据，不要画蛇添足去填。
         */
        .white_patch = {
            /*
             * 三个框全部取官方 awb.range（sc202cs_default.json），**不自己猜**。
             * 亮度窗的量纲是 R+G+B（[0, 765]，驱动注释写死 255*3），官方给的却是
             * green 的范围 [98, 210] —— 换算式是官方桥接层自己的：
             *     lum = G × (1 + R/G + B/G) = R + G + B
             *     lum_max = 210 × (1 + 0.8790 + 0.6587) = 532.9 → 533
             *     lum_min =  98 × (1 + 0.3801 + 0.2903) = 163.7 → 164
             * **现场验算的办法**是自检行里那个「平均G = Σg/白点数」，
             * 它应当落回 [98, 210]。
             *
             * ⚠️ 这四个比值与两个亮度界是**唯一**必须手抄进固件的官方标定量 ——
             *   esp_isp_awb_controller 的白点框只能在**创建时**给定，而 blob 是在
             *   pipeline 建起来之后才可能通过 IPA_METADATA_FLAGS_AWB 给出这个框。
             *   顺序上够不着，所以这里照抄 sc202cs_default.json 的 awb.range：
             *     green { max 210, min 98 }, rg { max 0.879, min 0.3801 },
             *     bg    { max 0.6587, min 0.2903 }
             *   （改标定文件时这六个数要跟着改，这是本次返工留下的唯一一处
             *    「官方数据在两个地方各存一份」，别再增加第二处。）
             * ⓘ 驱动把这两个比值转成 2 位整数 + 8 位小数的定点（截断），
             *   ⇒ 硬件实际用的框是 0.37890625~0.87890625 / 0.2890625~0.65625，
             *   比这里写的略宽一点点（方向安全：宁可多收几个边界像素，
             *   重心那一关还有 cam_awb_step_hw 的 SKIP_RANGE 兜着）。
             */
            .luminance        = { .min = 164, .max = 533 },
            .red_green_ratio  = { .min = 0.3801f, .max = 0.879f },
            .blue_green_ratio = { .min = 0.2903f, .max = 0.6587f },
        },
        /* ⚠️ 三个统计块（AE/AWB/AF）共用**一个** ISP 中断，intr_priority 必须与
         *   处理器一致（都是 0）。理由与失败表现见上面 ae_cfg 的同名字段。 */
        .intr_priority = 0,
    };
    s_st_awbstat = esp_isp_new_awb_controller(s_isp, &awb_cfg, &s_awb_ctlr);
    if (s_st_awbstat == ESP_OK) {
        /* 连续模式要靠回调拿结果（见上面那段「为什么不用 oneshot」）。 */
        const esp_isp_awb_cbs_t awb_cbs = { .on_statistics_done = cam_on_awb_stat };
        s_st_awbstat = esp_isp_awb_register_event_callbacks(s_awb_ctlr, &awb_cbs, NULL);
    }
    if (s_st_awbstat == ESP_OK)
        s_st_awbstat = esp_isp_awb_controller_enable(s_awb_ctlr);
    if (s_st_awbstat != ESP_OK)
        ESP_LOGW(TAG, "AWB 硬件统计没建起来(%s)，白点统计一直是 0，白平衡停在初值",
                 esp_err_to_name((esp_err_t)s_st_awbstat));

    /*
     * ══ 直方图统计 ══ 官方 ian 模块重建 env.luma 用。
     *
     * 失败**只降级不拦启动**：建不起来时 IPA_STATS_FLAGS_HIST 不置位 ⇒ blob 的
     * env.luma 拿不到输入，gamma 停在初值档，取流本身是好的。
     */
    const esp_isp_hist_config_t hist_cfg = {
        /*
         * ⚠️ 与 AE 同一个坑：isp_hal_hist_window_config() 把窗按 /5 分块，
         *   全零窗口能通过参数校验但 bsize = 0 ⇒ 16 个 bin 全是 0。
         * 写 1280×720（而不是 1279×719）：/5 之后是 256×144，**整除**，
         *   5×256 × 5×144 = 921600 = 整幅像素数，自检行的「Σbin」直接可核对。
         */
        .window = { .top_left  = { .x = 0,            .y = 0 },
                    .btm_right = { .x = CAM_SENSOR_W, .y = CAM_SENSOR_H } },
        /*
         * RGB 模式 ⇒ 抽头在 demosaic 之后、**gamma 之前**，与硬件 AE 同域
         * ⇒ gamma 换档不会扰动这份统计（这正是 T12 敢动态换 gamma 档的前提）。
         * 官方 esp_video 的默认也是 ISP_HIST_SAMPLING_RGB。
         */
        .hist_mode = ISP_HIST_SAMPLING_RGB,
        /*
         * ⚠️ 三个 integer 域必须为 0（驱动硬性检查，即三个系数都要 < 1.0）。
         *   文档要求小数部之和 = 256，而 256/3 除不尽 ⇒ 取 86/85/85。
         *   官方 esp_video 用的是 85/85/85（和为 255）—— 驱动**只检查权重和、
         *   不检查系数和**，所以两者都能配上；我们取和恰好 256 的那组，
         *   量纲上是「亮度 = (86R + 85G + 85B)/256」，干净可核对。
         */
        .rgb_coefficient = { .coeff_r = { .integer = 0, .decimal = 86 },
                             .coeff_g = { .integer = 0, .decimal = 85 },
                             .coeff_b = { .integer = 0, .decimal = 85 } },
        /*
         * ⚠️⚠️ 25 个权重的小数部之和**必须精确等于 256**
         *   （s_esp_isp_hist_config_hardware() 的 weight_sum == 256，不等直接
         *    ESP_ERR_INVALID_ARG），而 256/25 除不尽。取 IDF 测试用的那组：
         *   中心块 16、其余 24 块各 10 ⇒ 24×10 + 16 = 256。
         *
         *   ⚠️ **基线文档里那组「10 为主 / 内十字 11 / 中心 12」加起来是 260，
         *      照抄会直接被驱动拒掉**（本次实施逐条核对源码时发现，已记进计划
         *      §H.1）。别改回去。
         *
         *   这里要的是**近似均匀**（对应官方 ian.luma.env.weight 全 1），
         *   与 AE 的中心加权金字塔是两张不同的表、两个不同的量。中心那 16
         *   是被 256 这个整除条件逼出来的 6/256 = 2.3% 的偏差，可以忽略。
         */
        .window_weight = {
            {.integer=0,.decimal=10}, {.integer=0,.decimal=10}, {.integer=0,.decimal=10},
            {.integer=0,.decimal=10}, {.integer=0,.decimal=10},
            {.integer=0,.decimal=10}, {.integer=0,.decimal=10}, {.integer=0,.decimal=10},
            {.integer=0,.decimal=10}, {.integer=0,.decimal=10},
            {.integer=0,.decimal=10}, {.integer=0,.decimal=10}, {.integer=0,.decimal=16},
            {.integer=0,.decimal=10}, {.integer=0,.decimal=10},
            {.integer=0,.decimal=10}, {.integer=0,.decimal=10}, {.integer=0,.decimal=10},
            {.integer=0,.decimal=10}, {.integer=0,.decimal=10},
            {.integer=0,.decimal=10}, {.integer=0,.decimal=10}, {.integer=0,.decimal=10},
            {.integer=0,.decimal=10}, {.integer=0,.decimal=10},
        },
        /* ⚠️ 15 个阈值必须**严格落在 (0, 256)**，写 0 会被拒。取 16 的整数倍
         *   ⇒ 16 个 bin 各覆盖 16 个码值，与 cam_hist_stats() 里「bin i 的代表值
         *   取 16i+8」的约定逐位对齐（那个约定由宿主机用例守着）。 */
        .segment_threshold = { 16, 32, 48, 64, 80, 96, 112, 128,
                               144, 160, 176, 192, 208, 224, 240 },
        /* ⓘ esp_isp_hist_config_t **没有 intr_priority 字段**（IDF v6.0 的
         *   isp_hist.h 全文）—— 直方图的 ISR 直接复用处理器的优先级，
         *   不存在 AE/AWB 那个「三块必须一致」的坑。 */
    };
    s_st_hist = esp_isp_new_hist_controller(s_isp, &hist_cfg, &s_hist_ctlr);
    if (s_st_hist == ESP_OK) {
        const esp_isp_hist_cbs_t hist_cbs = { .on_statistics_done = cam_on_hist_stat };
        s_st_hist = esp_isp_hist_register_event_callbacks(s_hist_ctlr, &hist_cbs, NULL);
    }
    if (s_st_hist == ESP_OK)
        s_st_hist = esp_isp_hist_controller_enable(s_hist_ctlr);
    if (s_st_hist != ESP_OK)
        ESP_LOGW(TAG, "直方图统计没建起来(%s)，官方 env.luma 拿不到输入、"
                      "gamma 停在初值档，其余一切照常", esp_err_to_name((esp_err_t)s_st_hist));

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
     * ══ 黑电平：传感器自带的 BLC（T7）══
     *
     * ⚠️ **必须排在 set_format 之后**：set_format 会把整张模式寄存器表重写一遍
     *   （sc202cs_set_format），写早了会被它覆盖掉，而现象是「写了但没效果」——
     *   最容易被误判成「寄存器地址理解错了」的一种失败。
     *
     * 先**无条件读一次**。这一半零风险、开关关着也做，而它单独就能回答
     * 「传感器的 BLC 上电默认到底是开还是关」：
     *   读回 0xc0 ⇒ 本来就开着 ⇒ 基座应当已经 ≈ 0，什么都不用做；
     *   读回 0x80 ⇒ 关着       ⇒ 预期基座 ≈ 16，与官方 acc.blc 吻合。
     * 读失败不拦启动：它只是个观测量。
     */
    uint8_t blc = 0;
    s_st_blc_rd = esp_sccb_transmit_receive_reg_a16v8(s_sccb, CAM_SENSOR_BLC_REG, &blc);
    if (s_st_blc_rd == ESP_OK)
        s_blc_before = blc;

    /*
     * ══ 官方 esp_ipa 接管画质 ══ **必须排在 set_format 之后**：
     * 曝光上下限、增益表、默认值都是传感器驱动在 set_format 里才填好的。
     *
     * 失败只降级不拦启动：画面停在 ISP 基础配置上（发绿 + 偏暗 + 暗角，
     * 与总开关关掉时同一形态），而取流本身是好的 —— 让一个画质层把已经
     * 验证过的出图能力拖垮，是本末倒置。
     */
#if CAM_IPA_ENABLE
    const esp_err_t ipa_err = cam_ipa_init(s_isp, s_sensor);
    if (ipa_err != ESP_OK)
        ESP_LOGW(TAG, "官方 IPA 没起来(%s)，画面会发绿+偏暗+带暗角，其余一切照常",
                 esp_err_to_name(ipa_err));
    else
        cam_ipa_task_start();   /* pipeline 建起来了，才有节拍任务的消费对象 */
#else
    ESP_LOGW(TAG, "CONFIG_AIO_CAM_IPA 关闭：ISP 只做去马赛克，"
                  "画面会发绿+偏暗+带暗角、曝光固定 —— 这是排障档，不是产品形态");
#endif

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

    /*
     * 三块统计**只在取流时跑**（硬约束：摄像头不取流时零影响）。
     * 排在 esp_isp_enable() 成功之后：start_continuous 会立刻发一次
     * manual_update 触发第一帧统计，ISP 没使能时那一发是空放。
     * 建控制器失败的那一块不碰 —— 它的句柄是 NULL。
     */
    if (s_st_aestat == ESP_OK) {
        s_st_aerun = esp_isp_ae_controller_start_continuous_statistics(s_ae_ctlr);
        if (s_st_aerun != ESP_OK)
            ESP_LOGW(TAG, "AE 连续统计没启动(%s)，25 块亮度会一直是 0",
                     esp_err_to_name((esp_err_t)s_st_aerun));
    }
    if (s_st_awbstat == ESP_OK) {
        s_st_awbrun = esp_isp_awb_controller_start_continuous_statistics(s_awb_ctlr);
        if (s_st_awbrun != ESP_OK)
            ESP_LOGW(TAG, "AWB 连续统计没启动(%s)，白点数会一直是 0",
                     esp_err_to_name((esp_err_t)s_st_awbrun));
    }
    if (s_st_hist == ESP_OK) {
        s_st_histrun = esp_isp_hist_controller_start_continuous_statistics(s_hist_ctlr);
        if (s_st_histrun != ESP_OK)
            ESP_LOGW(TAG, "直方图连续统计没启动(%s)，16 个 bin 会一直是 0",
                     esp_err_to_name((esp_err_t)s_st_histrun));
    }

    s_streaming = true;
#if CAM_IPA_ENABLE
    /* 踢一下节拍任务。它此刻正睡在 portMAX_DELAY 上（不取流那一档），不踢的话
     * 要等第一份 AE 统计中断才醒 —— 而 AE 统计若压根没建起来（只降级不拦启动），
     * 它就再也醒不过来，连兜底节拍都不会开始。这一下把它拨回「取流」那一档。 */
    if (s_ipa_task)
        xTaskNotifyGive(s_ipa_task);
#endif
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
     *
     * ⚠️ **而那句 s_streaming = false 必须排在动任何硬件之前。**
     * 它是 cam_ipa_task 的闸 —— 那是一条独立的任务（节拍源是 AE 统计的 ISR），
     * 与本函数**不在同一个任务上**（本函数跑在 UVC 帧泵里）。先关闸，
     * 停流期间新到的 AE 统计就只会让节拍任务醒一下、看一眼、接着睡，
     * 不会再往一个正在被关掉的传感器上写曝光/增益。
     * 残留窗口只剩「关闸那一刻已经进了门的那一拍」（几百微秒），它最坏也只是
     * 给一颗即将 sleep 的传感器多写一次曝光寄存器 —— 无害，下次 start 照常。
     *
     * ⓘ 提前置位不影响本函数原有的语义：入口那道幂等闸已经过了，而
     *   「最终状态由 s_streaming = false 一锤定音」说的是**不因中途失败而回退**，
     *   提前置反而让这一点更硬。
     */
    s_streaming = false;

    esp_err_t err = ESP_OK;
    int off = 0;
    /* 逐条顺序展开，**不要**塞进数组初始化器里循环 —— C 不保证初始化器各表达式的
     * 求值顺序，而这四步的先后正是本函数的全部内容。 */
    keep_first_err(&err, "传感器 stream off",
                   esp_cam_sensor_ioctl(s_sensor, ESP_CAM_SENSOR_IOC_S_STREAM, &off));
    keep_first_err(&err, "CSI stop",    esp_cam_ctlr_stop(s_cam));
    /* ⚠️ 三块统计必须排在 `ISP disable` **之前**：先让统计块停下来，再关 ISP。
     * 反过来的话 disable 之后还可能收到最后一次统计中断。
     * 顺序理由与既有四步停流一致（先停数据源，再关块），并同样 keep_first_err 记账。
     * 幂等由 s_streaming 那道闸保证：驱动的 FSM 门只允许 ENABLE↔CONTINUOUS 各一次。 */
    if (s_st_aestat == ESP_OK) {
        s_st_aerun = esp_isp_ae_controller_stop_continuous_statistics(s_ae_ctlr);
        keep_first_err(&err, "AE 统计 stop", (esp_err_t)s_st_aerun);
    }
    if (s_st_awbstat == ESP_OK) {
        s_st_awbrun = esp_isp_awb_controller_stop_continuous_statistics(s_awb_ctlr);
        keep_first_err(&err, "AWB 统计 stop", (esp_err_t)s_st_awbrun);
    }
    if (s_st_hist == ESP_OK) {
        s_st_histrun = esp_isp_hist_controller_stop_continuous_statistics(s_hist_ctlr);
        keep_first_err(&err, "直方图统计 stop", (esp_err_t)s_st_histrun);
    }
    keep_first_err(&err, "ISP disable", esp_isp_disable(s_isp));
    keep_first_err(&err, "CSI disable", esp_cam_ctlr_disable(s_cam));

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

/* ══ 统计 → 官方 esp_ipa ═════════════════════════════════════════════ */

/* 最近一帧的内容统计，自检行用（**纯观测**，不参与任何控制）。 */
static cam_frame_stats_t s_last_stats;

/* 三块统计各自交付了多少帧 —— 自检行要能分出「哪一块没在跑」。 */
static uint32_t s_ae_frames, s_awb_frames, s_hist_frames;
#if CAM_IPA_ENABLE
/* 送进 blob 的序号。官方用它判断「这份统计是不是新的」。 */
static uint64_t s_stats_seq;
#endif

/*
 * 把三块硬件统计填成 esp_ipa_stats_t。
 *
 * 逐条对应 esp_video/src/esp_video_isp_pipeline.c 的 isp_stats_to_ipa_stats()：
 *   AE   → ae_stats[i*5 + j].luminance      （25 块，与驱动填 luminance[i][j] 同序）
 *   AWB  → awb_stats[0] 的 counted/sum_r/g/b（ISP_AWB_REGIONS = 1，只有全局那一桶）
 *   HIST → hist_stats[i].value              （16 段）
 *
 * ⚠️ **哪一块没交付过帧，就不置它的 flag 位。** blob 是按位判断输入有没有的，
 *   置了位却给全 0 与「没给」是完全不同的两件事 —— 前者会让它以为画面全黑，
 *   把曝光一路推到顶。
 *
 * 返回 true = 至少有一块统计可用（值得调 process()）。
 *
 * ⓘ 只在 CAM_IPA_ENABLE 下编译：开关关掉时没有消费者，留着会是一个
 *   -Wunused-function 告警（本工程要求两档零告警）。三块统计的 snapshot
 *   helper 不受影响 —— 自检行两档都要用它们。
 */
#if CAM_IPA_ENABLE
static bool cam_fill_ipa_stats(esp_ipa_stats_t *st)
{
    memset(st, 0, sizeof *st);
    st->seq = ++s_stats_seq;

    if (s_st_aestat == ESP_OK) {
        uint8_t blocks[25];
        s_ae_frames = cam_ae_stat_snapshot(blocks);
        if (s_ae_frames) {
            for (int i = 0; i < ISP_AE_BLOCK_X_NUM; i++)
                for (int j = 0; j < ISP_AE_BLOCK_Y_NUM; j++)
                    st->ae_stats[i * ISP_AE_BLOCK_Y_NUM + j].luminance =
                        blocks[i * ISP_AE_BLOCK_Y_NUM + j];
            st->flags |= IPA_STATS_FLAGS_AE;
        }
    }

    if (s_st_awbstat == ESP_OK) {
        uint32_t counted = 0, r = 0, g = 0, b = 0;
        s_awb_frames = cam_awb_stat_snapshot(&counted, &r, &g, &b);
        if (s_awb_frames) {
            st->awb_stats[0].counted = counted;
            st->awb_stats[0].sum_r   = r;
            st->awb_stats[0].sum_g   = g;
            st->awb_stats[0].sum_b   = b;
            st->flags |= IPA_STATS_FLAGS_AWB;
            /* ⓘ 不置 IPA_STATS_FLAGS_AWB_SUBWIN：rev < 3.0 上 subwindow 不可用
             *   （驱动打个 warning 就跳过配置），awb_subwin[][] 保持全零。 */
        }
    }

    if (s_st_hist == ESP_OK) {
        uint32_t bins[ISP_HIST_SEGMENT_NUMS];
        s_hist_frames = cam_hist_stat_snapshot(bins);
        if (s_hist_frames) {
            for (int i = 0; i < ISP_HIST_SEGMENT_NUMS; i++)
                st->hist_stats[i].value = bins[i];
            st->flags |= IPA_STATS_FLAGS_HIST;
        }
    }

    /* ⓘ SHARPEN / AF 两块统计本工程没建：前者只喂官方 aen 的自适应锐化
     *   （标定文件里没有相应字段），后者要 VCM 而 SC202CS 是定焦模组。 */
    return st->flags != 0;
}

/*
 * ══ IPA 节拍任务 ══════════════════════════════════════════════════
 *
 * ── 为什么要单开一个任务 ───────────────────────────────────────────
 * 官方的消费侧（esp_video/src/esp_video_isp_pipeline.c 的 isp_task）是一个
 * **专用 FreeRTOS 任务**：阻塞在 VIDIOC_DQBUF 等 ISP 统计 DMA 完成 → 取传感器
 * 状态 → 填 esp_ipa_stats_t → esp_ipa_pipeline_process() → 分发 metadata →
 * VIDIOC_QBUF 归还缓冲。**一份统计一次 process，不分频。**
 *
 * 本工程一度把 process() 挂在 UVC 帧泵那一拍上，而帧泵是 100 ms 固定节拍
 * ⇒ 只有 10 Hz。三块统计本来就是 30 Hz 到的（连续模式 + ISR 回调），
 * 慢的只是消费侧 —— 而 stats->seq 由我们每次 process() 递增，于是官方标定里
 * 所有按「帧」计的量统统被拉长三倍：
 *     agc.exposure.frame_delay = 3 → 3 × 100 ms = 300 ms（应为 3 × 33 ms）
 *     agc.gain.frame_delay     = 3 → 同上
 *     awb 的各种 delay / counter → 同上
 * 表现就是 AE/AWB **收敛慢三倍**。修法只能是把消费侧从帧泵上摘下来，
 * 让它跟着统计走 —— 也就是这个任务。
 *
 * ── 节拍源为什么取 AE ─────────────────────────────────────────────
 * 官方那边三块统计装在同一个 meta buffer 里一起 DQ（带 flags 表示哪些有效），
 * 我们这边是三个独立的 ISR 回调，必须挑一个当拍子。挑 AE：
 *   · 它由 ISP 的 AE_FDONE 中断驱动，**每帧必发一次**，是三块里最可靠的；
 *   · agc 是唯一每拍都消费输入的控制律，拍子跟着它走语义最直接；
 *   · AWB / 直方图用各自 ISR 最近一次的值 —— 三块统计由**同一个** ISP 中断
 *     周期产生，落后至多一帧，而 blob 本来就按帧延迟工作。
 * ⚠️ **只对真正交付过数据的块置 flag 位**，这条不变式在 cam_fill_ipa_stats 里，
 *   别绕过它：置了位却给全 0，blob 会以为画面全黑、把曝光一路推到顶。
 *
 * ── 兜底超时 ──────────────────────────────────────────────────────
 * AE 统计没建起来（s_st_aestat != ESP_OK，只降级不拦启动的那条路）或中途断供
 * 时，通知永远不来。纯通知驱动的话 AWB/CCM/gamma/LSC 会一起冻在初值上 ——
 * 比返工前**更差**。所以取流期间的等待带 CAM_IPA_FALLBACK_MS 超时，超时也走
 * 一拍：降级成返工前那个 10 Hz 节奏，而不是失效。
 * 不取流时无限期阻塞、一次都不醒 ——「摄像头不取流时零影响」在本任务上的落点。
 */
#define CAM_IPA_FALLBACK_MS  100    /* AE 断供时的兜底节拍，恰好是返工前那一拍 */

/*
 * 优先级 3。**必须低于 TinyUSB 与各条数据泵**：TinyUSB 与 UVC 帧泵都是 5、
 * 触摸与键盘是 5、音频泵是 4。理由有两条：
 *   · 本任务是一条尽力而为的控制回路 —— 晚一拍的代价只是 AE 多花 33 ms 收敛；
 *     而 UVC/UAC/HID 晚一拍是用户直接看得见听得见的掉帧、爆音、丢触点。
 *   · 它会做 I2C 写（下发曝光/增益），走的是与触摸/codec/IO 扩展共用的那条
 *     内部总线，压在触摸之上更没有道理。
 * 3 之下还有待机点阵任务(2)与 IDLE(0)，不存在把它们饿死的风险：
 * 本任务 30 Hz、每拍只有几百微秒（blob 的浮点 + 最多 6 次 SCCB 写）。
 */
#define CAM_IPA_TASK_PRIO    3

/*
 * 栈 4096 字节。esp_ipa_stats_t（≈624 B = 25 块 AE + 5×5 AWB 子窗 + 16 段
 * 直方图 + 3 个 AF 窗 + seq/flags）**提成文件级静态、不放栈上** —— 它每拍都要
 * memset 一遍，放栈上等于从 blob 的浮点运算与 LSC 分发那里挤掉六百多字节。
 * ⓘ 顺带把 UVC 帧泵那 4096 字节的栈也还回去了：这个结构体原先是 uvc 任务的
 *   局部变量。
 * 实际余量由自检行的「栈余」直读（uxTaskGetStackHighWaterMark，IDF 返回字节），
 * 不必靠猜；那一格掉到 512 B 以下就该把这里加大。
 */
#define CAM_IPA_TASK_STACK   4096

/* 送进 blob 的那份统计。**文件级静态**，理由见 CAM_IPA_TASK_STACK 上方。
 * 只有 cam_ipa_task 一个写者与读者，不需要同步。 */
static esp_ipa_stats_t s_ipa_stats;

/* ── 节拍自检计数器 ──────────────────────────────────────────────
 * 只由 cam_ipa_task 写、自检行读，与本文件其余计数器同规格（单向累加、
 * 32 位对齐读写在 P4 上原子）。判读表写在 camera_csi_report() 里。 */
static uint32_t s_ipa_wakes;      /* 任务醒过几次（含兜底超时那几次） */
static uint32_t s_ipa_notifies;   /* 一共消费掉多少条 AE 通知 */
static uint32_t s_ipa_runs;       /* 真正调到 cam_ipa_process() 的次数 */
static uint32_t s_ipa_skips;      /* 醒了但没跑（停流中 / 三块统计一份都没到） */
static uint32_t s_ipa_timeouts;   /* 兜底超时触发的次数 = AE 统计断供的拍数 */
static uint32_t s_ipa_batch_max;  /* 单次唤醒里最多消费掉几条通知，>1 = 没跟上 */

static void cam_ipa_task(void *arg)
{
    (void)arg;
    while (1) {
        /*
         * 不取流 ⇒ 睡到天荒地老（统计块此时也停了，通知不会来），零 CPU；
         * 取流   ⇒ 最多等一个兜底节拍。
         * s_streaming 的读法与本文件其余各处一致（写方是启停那一路的任务，
         * 读到旧值最多让这一拍多睡或少睡一次，下一拍就纠正回来）。
         */
        const TickType_t wait = s_streaming ? pdMS_TO_TICKS(CAM_IPA_FALLBACK_MS)
                                            : portMAX_DELAY;
        /* pdTRUE = 退出时把计数清零 ⇒ 返回值就是「上一拍到现在积了几份统计」。
         * 它恒等于 1 才说明真的做到了「一份统计一次 process」。 */
        const uint32_t n = ulTaskNotifyTake(pdTRUE, wait);

        s_ipa_wakes++;
        s_ipa_notifies += n;
        if (n == 0)
            s_ipa_timeouts++;           /* AE 断供，走兜底那一拍 */
        else if (n > s_ipa_batch_max)
            s_ipa_batch_max = n;        /* >1 ⇒ 没跟上，blob 少看了 n-1 帧统计 */

        /* 停流之后可能还剩一条在路上的通知（AE 的 ISR 与本任务是两条线）。
         * 这一行是「不取流时一步都不走」的闸，与 camera_csi_stop() 里那句
         * 提前置 false 配对 —— 后者关的是门，这里是进门前再看一眼。 */
        if (!s_streaming) {
            s_ipa_skips++;
            continue;
        }

        if (cam_fill_ipa_stats(&s_ipa_stats)) {
            cam_ipa_process(&s_ipa_stats);
            s_ipa_runs++;
        } else {
            s_ipa_skips++;              /* 三块统计一份都还没到，刚开流那几拍 */
        }
    }
}

/*
 * 建节拍任务。幂等。
 * 失败**只降级不拦启动**（与本文件其余画质级同一处置）：没有节拍任务就没人调
 * process()，画面停在 cam_ipa_init() 下发的那批初值上，取流本身完全不受影响。
 */
static void cam_ipa_task_start(void)
{
    if (s_ipa_task)
        return;
    if (xTaskCreate(cam_ipa_task, "ipa", CAM_IPA_TASK_STACK, NULL,
                    CAM_IPA_TASK_PRIO, &s_ipa_task) != pdPASS) {
        ESP_LOGW(TAG, "IPA 节拍任务建不起来，画面停在 IPA 初值上，其余一切照常");
        return;   /* xTaskCreate 失败时不写句柄，s_ipa_task 保持 NULL */
    }
    ESP_LOGI(TAG, "IPA 节拍任务已建：节拍源=AE 统计中断（每帧一次 ⇒ 跟随传感器帧率），"
                  "优先级 %d、栈 %d B，兜底 %d ms；不取流时休眠",
             CAM_IPA_TASK_PRIO, CAM_IPA_TASK_STACK, CAM_IPA_FALLBACK_MS);
}
#endif  /* CAM_IPA_ENABLE */

void camera_csi_note_frame_stats(const cam_frame_stats_t *st)
{
    /*
     * samples == 0 表示这份统计什么都没采到（参数非法）—— 与「采到了，结果是
     * 全黑」严格区分开。**纯观测量，不参与任何控制。**
     *
     * ⚠️ 本函数**不再驱动 IPA**。process() 已经搬进 cam_ipa_task（节拍源是 AE
     *   统计的 ISR，跟着传感器帧率走），与帧泵那 100 ms 的固定节拍彻底解耦 ——
     *   挂在帧泵上时 process() 只有 10 Hz，官方标定里所有按「帧」计的量
     *   （agc.exposure.frame_delay = 3 等）都被拉长三倍，推理见 cam_ipa_task。
     */
    if (st && st->samples)
        s_last_stats = *st;
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

    /*
     * 画质那几行紧跟其后：上面那行说的是「有没有帧」，它们说的是「帧对不对」，
     * 顺序就是排查顺序 —— 没帧的时候画质数字一律不必看。
     *
     * 判读（三块统计）：
     *   AE 帧=0 而 CSI 帧在涨    → 连续统计没启动，看「运行=」那格。
     *   25 块**全是 0**          → 窗口 bsize=0，见 init 里 ae_cfg 的 ⚠️。
     *   25 块全都相同的非零值    → 分块没生效（窗口与分辨率对不上）。
     *   遮住镜头 ⇒ 25 块全掉；只遮半边 ⇒ **只有一侧掉**。
     *   白点数一直是 0           → 白点框画错了，或者画面里确实没有接近中性的像素
     *                            （怼着单色物体）。换白纸或灰卡再看。
     *   平均G = Σg/白点数 应当落回 [98, 210]（官方 awb.range.green）——
     *                            落在框外说明白点框与实际画面不匹配。
     *   Σbin 应当 ≈ 921600（= 1280×720）—— 差很多说明直方图窗口配错了。
     *   alt 0（不取流）下三个「帧=」还在涨 → stop 路径漏了统计块。
     */
    ESP_LOGI(TAG, "[自检] 统计 AE=%s(帧 %" PRIu32 ") AWB=%s(帧 %" PRIu32
                  ") HIST=%s(帧 %" PRIu32 ") | 运行 AE=%s AWB=%s HIST=%s",
             step_str(s_st_aestat), s_ae_frames, step_str(s_st_awbstat), s_awb_frames,
             step_str(s_st_hist), s_hist_frames,
             step_str(s_st_aerun), step_str(s_st_awbrun), step_str(s_st_histrun));

    {
        uint8_t blocks[25];
        const uint32_t ae_frames = cam_ae_stat_snapshot(blocks);
        (void)ae_frames;   /* CONFIG_AIO_CAM_IPA 关掉时下面那行不编译 */
        ESP_LOGI(TAG, "[自检] AE 25 块 [%3u %3u %3u %3u %3u | %3u %3u %3u %3u %3u | "
                      "%3u %3u %3u %3u %3u | %3u %3u %3u %3u %3u | %3u %3u %3u %3u %3u]",
                 blocks[0], blocks[1], blocks[2], blocks[3], blocks[4],
                 blocks[5], blocks[6], blocks[7], blocks[8], blocks[9],
                 blocks[10], blocks[11], blocks[12], blocks[13], blocks[14],
                 blocks[15], blocks[16], blocks[17], blocks[18], blocks[19],
                 blocks[20], blocks[21], blocks[22], blocks[23], blocks[24]);

        uint32_t counted = 0, r = 0, g = 0, b = 0;
        (void)cam_awb_stat_snapshot(&counted, &r, &g, &b);
        ESP_LOGI(TAG, "[自检] AWB 白点数=%" PRIu32 " Σr=%" PRIu32 " Σg=%" PRIu32
                      " Σb=%" PRIu32 "（平均G=%" PRIu32 "，官方框 [98,210]；"
                      "r/g=%" PRIu32 ".%03" PRIu32 " b/g=%" PRIu32 ".%03" PRIu32 "）",
                 counted, r, g, b,
                 counted ? g / counted : 0,
                 g ? (uint32_t)((uint64_t)r * 1000 / g) / 1000 : 0,
                 g ? (uint32_t)((uint64_t)r * 1000 / g) % 1000 : 0,
                 g ? (uint32_t)((uint64_t)b * 1000 / g) / 1000 : 0,
                 g ? (uint32_t)((uint64_t)b * 1000 / g) % 1000 : 0);

        uint32_t bins[ISP_HIST_SEGMENT_NUMS], total = 0;
        (void)cam_hist_stat_snapshot(bins);
        for (int i = 0; i < ISP_HIST_SEGMENT_NUMS; i++)
            total += bins[i];
        ESP_LOGI(TAG, "[自检] HIST Σbin=%" PRIu32 "（应 ≈ %d）暗(bin0)=%" PRIu32
                      " 亮(bin15)=%" PRIu32,
                 total, CAM_SENSOR_W * CAM_SENSOR_H, bins[0],
                 bins[ISP_HIST_SEGMENT_NUMS - 1]);

#if CAM_IPA_ENABLE
        /*
         * ══ IPA 的**节拍**自检 ══ 「有没有真的对齐 30 Hz」只能由这一行回答。
         *
         *   处理/统计 ≈ 100% 且 单次最多=1 ⇒ 每份 AE 统计恰好消费一次 ⇒ **对齐了**。
         *                                    绝对频率看下面 IPA 那行的「拍数」。
         *   单次最多 ≥ 2                   ⇒ 任务没跟上，两份统计被合并成一拍，
         *                                    blob 少看了帧。看 CPU 负载与
         *                                    「下发码」（I2C 是否在阻塞）。
         *   超时兜底 持续涨                 ⇒ AE 统计断供，整条 IPA 掉回 10 Hz 兜底
         *                                    节拍，根因看上面「运行 AE=」那一格。
         *   跳过 持续涨而取流中             ⇒ 三块统计一份都没到（都没建起来）。
         *   栈余 < 512 B                   ⇒ CAM_IPA_TASK_STACK 该加大了。
         *   唤醒 = 0 而取流中               ⇒ 任务根本没建起来，看开机那条 warning。
         */
        ESP_LOGI(TAG, "[自检] IPA 节拍 唤醒=%" PRIu32 " 通知=%" PRIu32 " 处理=%" PRIu32
                      " 跳过=%" PRIu32 " 超时兜底=%" PRIu32 " 单次最多=%" PRIu32 " 条"
                      " | AE 统计交付=%" PRIu32 " ⇒ 处理/统计=%" PRIu32 "%%（应 ≈100）"
                      " | 优先级 %d 栈余 %u B",
                 s_ipa_wakes, s_ipa_notifies, s_ipa_runs, s_ipa_skips,
                 s_ipa_timeouts, s_ipa_batch_max, ae_frames,
                 ae_frames ? (uint32_t)((uint64_t)s_ipa_runs * 100 / ae_frames) : 0,
                 CAM_IPA_TASK_PRIO,
                 (unsigned)(s_ipa_task ? uxTaskGetStackHighWaterMark(s_ipa_task) : 0));
#endif
    }

    /*
     * 帧内容统计。**纯观测**，不参与任何控制律 —— 它回答的是「帧里有没有东西」：
     *   min == max        ⇒ 纯色（全黑/全白），不是真实画面
     *   校验和 帧间不变    ⇒ 取到的是同一块没被重写的缓冲
     *   R<G>B 比例固定    ⇒ 白平衡没起作用（IPA 没跑，或 CCM 没配上）
     */
    ESP_LOGI(TAG, "[自检] 帧内容 采样=%" PRIu32 " 亮度 均值=%u 最小=%u 最大=%u "
                  "校验和=0x%08" PRIx32 " | 通道均值 R=%u G=%u B=%u",
             s_last_stats.samples, s_last_stats.lum_mean, s_last_stats.lum_min,
             s_last_stats.lum_max, s_last_stats.checksum,
             s_last_stats.r_mean, s_last_stats.g_mean, s_last_stats.b_mean);

    ESP_LOGI(TAG, "[自检] 传感器 BLC(0x3902) 读=%s 值=%d"
                  "（0xc0=开着⇒基座≈0；0x80=关着⇒基座≈16，与官方 acc.blc 吻合。"
                  "本板 rev v1.0 无 ISP BLC，metadata 的 BLC 位由 cam_ipa.c 忽略）",
             step_str(s_st_blc_rd), s_blc_before);

    /* 官方 IPA 那几行排在最后：前面都正常了才轮到看算法在做什么。 */
#if CAM_IPA_ENABLE
    cam_ipa_report();
#else
    ESP_LOGW(TAG, "[自检] IPA=未编译（CONFIG_AIO_CAM_IPA 关闭）：ISP 只做去马赛克，"
                  "画面发绿+偏暗+带暗角、曝光固定 —— 排障档，不是产品形态");
#endif
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