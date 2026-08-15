/*
 * SC202CS 的 SCCB 探测。实现说明见 camera_csi.h。
 */
#include "camera_csi.h"
#include "board_power.h"
#include "tab5_pins.h"
#include "esp_log.h"
#include <inttypes.h>
#include <stdio.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_sccb_intf.h"
#include "esp_sccb_i2c.h"
#include "sc202cs.h"

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
