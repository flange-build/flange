/*
 * SC202CS 的 SCCB 探测 + MIPI-CSI/ISP 取流。实现说明见 camera_csi.h。
 */
#include "camera_csi.h"
#include "board_power.h"
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
     *   有版本门的是我们**一个都没用**的可选子模块：BLC(isp_blc.c:29)、
     *   WBG(isp_wbg.c:29)、AWB(isp_awb.c:82)、crop(isp_crop.c:29) 要 rev ≥ 3.0，
     *   LSC(isp_lsc.c:57) 要 rev ≥ 1.0。所以修好 CSI 不会再撞 ISP 的墙。
     *
     * **不做 AE/AWB 闭环** —— 闭环控制律要么引
     * espressif/esp_ipa（会把 esp_video 的一半拖进来），要么自己写；本阶段用
     * esp_cam_sensor 模式表里的默认曝光与增益（sc202cs_isp_info[0] 的
     * exp_def = 0x3dc、gain_def = 0）。
     * ⚠️ **代价**：固定室内光照下画面正常，但换光照环境会过曝或欠曝，且不会自动
     *    恢复。真要自动曝光，下一阶段优先自己写 30 行 P 控制器，别引 esp_ipa。
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
