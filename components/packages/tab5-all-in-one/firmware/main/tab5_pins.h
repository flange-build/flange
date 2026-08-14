#pragma once
/*
 * M5Stack Tab5 板级常量。
 * 引脚值取自 esp-bsp bsp/m5stack_tab5（Apache-2.0）与官方原理图，勿凭记忆改。
 */

/* 内部 I2C：IO 扩展 / 触摸 / 音频 codec / IMU / RTC 共用 */
#define PIN_I2C_SDA        31
#define PIN_I2C_SCL        32

/* 显示 */
#define PIN_LCD_BL         22    /* 背光 LEDA */
#define IOEXP_ADDR         0x43  /* PI4IOE5V6408-1：管 LCD/TOUCH/SPEAKER/CAMERA 使能 */
#define ST7123_I2C_ADDR    0x55  /* ST7123 显示触控一体，存在即表明是 ST7123 批次 */
#define GT911_I2C_ADDR     0x14  /* GT911 触摸，存在即表明面板为 ILI9881C */
#define PIN_TOUCH_INT      23    /* GT911 INT；触摸电源使能在 IO 扩展 0x43 的 PIN5，board_power_init() 已拉高 */

/* Tab5 Keyboard：独立的 STM32F030 I2C 从机，挂在与内部 I2C 分离的另一条总线上。
 * INT 低有效（键盘固件拉低表示有事件），故 ESP 侧上拉 + 下降沿触发。 */
#define PIN_KBD_SDA        0
#define PIN_KBD_SCL        1
#define PIN_KBD_INT        50
#define KBD_I2C_ADDR       0x6D

/* ── 音频 ────────────────────────────────────────────────────────
 * I2S 的收发数据线**物理独立**（DOUT/DSIN 是两根脚），SCLK/LRCK/MCLK 共用，
 * 因此可以在一个 I2S 端口上组成真全双工 —— 不需要 Cardputer 上那套
 * 「扬声器与麦克风抢同一根 WS 脚」的半双工仲裁。
 * 取自 esp-bsp bsp/m5stack_tab5（Apache-2.0）。 */
#define PIN_I2S_MCLK       30
#define PIN_I2S_SCLK       27   /* BCLK  ⚠️ 同时是 USB 内部全速 PHY1 的 D+，见下 */
#define PIN_I2S_LRCK       29   /* WS */
#define PIN_I2S_DOUT       26   /* ESP → ES8388，播放；⚠️ 同时是 PHY1 的 D−，见下 */
#define PIN_I2S_DSIN       28   /* ES7210 → ESP，录音 */

/*
 * ⚠️⚠️⚠️ **配置 G26/G27 会顺手关掉 USB-C 的焊盘** —— 本板最贵的一个坑，
 *        排查烧了七八次板，写清楚，别再踩第二次。
 *
 * ── 事实 1：ESP32-P4 的两条内部全速(FSLS) PHY 的 D−/D+ 复用在 GPIO 上 ──
 *     PHY0: D− = G24, D+ = G25     ← Tab5 的 USB-C 接在这里
 *     PHY1: D− = G26, D+ = G27     ← 正好就是本板的 I2S DOUT 与 BCLK
 *   依据 components/soc/esp32p4/register/hw_ver1/soc/io_mux_reg.h:167-170
 *       USB_INT_PHY0_DM/DP_GPIO_NUM = 24 / 25
 *       USB_INT_PHY1_DM/DP_GPIO_NUM = 26 / 27
 *
 * ── 事实 2：哪条 PHY 归谁，是可以换的，而我们**换了** ──
 *   LP_SYS.usb_ctrl.sw_usb_phy_sel 决定 USJ 与 USB_WRAP(OTG1.1) 各拿哪条 PHY。
 *   默认 USJ→PHY0、OTG→PHY1；app_main.c 的 route_fsls_phy0_to_otg() 把它对调成
 *   **OTG→PHY0(G24/G25)、USJ→PHY1(G26/G27)** —— 必须这么换，因为 USB-C 物理接的
 *   就是 G24/G25。见 hal/usb_wrap_ll.h 的 usb_wrap_ll_phy_select()。
 *
 * ── 事实 3（真正的根因）：IDF 的 GPIO HAL 把「谁用哪条 PHY」写死了 ──
 *   components/esp_hal_gpio/esp32p4/include/hal/gpio_ll.h:676-686
 *       static inline void gpio_ll_func_sel(gpio_dev_t *hw, uint8_t gpio_num, uint32_t func)
 *       {
 *           // Disable USB PHY configuration if pins (24, 25) (26, 27) needs to
 *           // select an IOMUX function
 *           // We only consider the default connection here: PHY0 -> USJ, PHY1 -> USB_OTG
 *           if (gpio_num == 24 || gpio_num == 25)      USB_SERIAL_JTAG.conf0.usb_pad_enable = 0;
 *           else if (gpio_num == 26 || gpio_num == 27) USB_WRAP.otg_conf.usb_pad_enable = 0;
 *           IO_MUX.gpio[gpio_num].mcu_sel = func;
 *       }
 *   注释里那句 "We only consider the default connection here" 就是炸弹引信：
 *   **我们恰恰破坏了那个默认假设。**
 *
 *   而 usb_pad_enable 是**跟着 mux 走的**（每个控制器一位，经 sw_usb_phy_sel 路由到
 *   它当前那条 PHY —— 否则 usb_new_phy() 置位 USB_WRAP 那一位之后 USB-C 根本不会通）。
 *   于是：
 *       i2s_channel_init_std_mode() → i2s_gpio_check_and_set()
 *         → gpio_func_sel(26/27, PIN_FUNC_GPIO) → gpio_ll_func_sel()
 *           → USB_WRAP.otg_conf.usb_pad_enable = 0
 *             → 换过 PHY 之后这一位管的是 **PHY0 = G24/G25 = USB-C**
 *               → **USB-C 的焊盘被关掉**
 *
 *   注意：G26/G27 上从头到尾**只有 I2S 一个驱动器**，PHY1 的焊盘并没有被打开
 *   （OTG 的 usb_pad_enable 早已随 mux 走到 PHY0；USJ 那一位则在启动早期就被 IDF
 *   清零了，见下）。所以这**不是**「两个驱动器抢一个焊盘」的模拟问题，
 *   而是一次**寄存器误伤**：I2S 配脚顺手把 USB-C 的焊盘开关拨到了 0。
 *
 * ── 实测吻合（这是坐实根因的那组数据）──
 *   CONFIG_AIO_AUDIO_FULL + CONFIG_AIO_AUDIO_I2S_GPIO_NO_USB_PADS（整套音频照跑，
 *   只把 G26/G27 让开）：GUD 显示正常、声卡与麦克风都枚举出来，只是没声音
 *   （DOUT/BCLK 确实没接出去）。⇒ I2S 外设、时钟、GDMA、codec I2C、esp_codec_dev、
 *   数据泵、UAC 描述符、端点/FIFO 全部无罪，**只要碰这两个脚就死**。
 *   反过来碰了就死的症状是「D+ 还拉着、主机看得到设备、EP0 一个控制传输都不应答、
 *   CPU 不复位」—— 正是焊盘被关掉、PHY 停止收发的样子。
 *
 * ── 修法（app_main.c）──
 *   引脚是硬连线的，改不了；IDF 的 gpio_ll_func_sel() 也不能改。只能**在它误伤之后
 *   把开关拨回来**，并让误伤发生在 USB 还没上电的时候：
 *     1. codec_audio_init()（I2S + 两颗 codec）排在 tinyusb_driver_install() **之前**
 *        —— 那时 USB 还没连上主机，误伤无害；随后 tinyusb_driver_install() 内部的
 *        usb_new_phy() → usb_wrap_hal_init() → usb_wrap_ll_phy_set_defaults() 会把
 *        otg_conf.usb_pad_enable 重新置 1（esp_hal_usb/usb_wrap_hal.c:11-19）。
 *        这样**不存在**「USB 已枚举却被短暂拔掉」的窗口。
 *     2. 装完 TinyUSB 再显式跑一遍 otg_fsls_pads_repair() 兜底。
 *   细节与另外两条兜底动作见 app_main.c 的 otg_fsls_pads_repair()。
 *
 * ── 另一条独立的误伤路径（同一 bug 家族，已一并兜底）──
 *   gpio_ll.h:93-111 的 gpio_ll_pullup_dis() 也写死了同一套假设：对 G27 调它会写
 *   USB_WRAP.otg_conf.pad_pull_override = 1 / dp_pullup = 0，换过 PHY 之后就是
 *   **拿掉 G25(D+) 的上拉** ⇒ 主机直接看不到设备。当前 I2S 路径不走这条
 *   （i2s_gpio_check_and_set() 只调 gpio_func_sel / gpio_input_enable /
 *   esp_rom_gpio_connect_out_signal），但修复里顺手把 override 清回 0。
 *
 * ── 为什么 esp-bsp / M5Stack 自己的固件不会踩到 ──
 *   Tab5 原理图（官方 PDF）的网名把三对脚分得很清楚：
 *       U1 pin 49/50  USB2_OTG_D−/D+                → USB-A 母座（高速 PHY 专用焊盘）
 *       U1 pin 52/53  GPIO24/USB1P1_0− , GPIO25/…+  → USB_DEVICE_DM/DP → USB-C J8
 *       U1 pin 55/56  GPIO26/USB1P1_1− , GPIO27/…+  → I2S_DIN_MOSI_GPIO26 / I2S_SCLK_GPIO27
 *   也就是说 **PHY1 上根本没有接任何 USB 连接器**。而 esp-bsp bsp/m5stack_tab5 的
 *   bsp_usb.c 走的是 usb_host_install()，在 P4 上解析成**高速控制器 + UTMI PHY**
 *   （独立焊盘），从不碰 G24~G27；esp-bsp 全仓库对 usb_phy / usb_wrap / phy_sel /
 *   pad_enable 零命中，也没有任何 example 同时开音频与 USB。
 *   我们是**第一个**在这块板上把全速 OTG 换到 PHY0 的，所以这条路上没有前人的脚印。
 *   （P4 官方 errata 13 条里也没有 USB / GPIO 相关项；IDF 的 P4 GPIO 文档只提醒
 *    G24/G25 被 USB-JTAG 占用，对 G26/G27 与双 PHY 的相互作用只字未提，
 *    datasheet 甚至把 G26/G27 归为「可自由使用、无限制」的 Priority 2。）
 *
 * ⓘ LP_SYS.usb_ctrl 的 sw_hw_usb_phy_sel / sw_usb_phy_sel 这两位在公开 TRM 里是
 *   **reserved**（IDF 头文件的描述也只有 "need_des"）。TRM 只文档化了 eFuse 那条
 *   静态换法。也就是说我们用的是一条未公开的运行时寄存器路径 —— 它能用（实机已验），
 *   但别指望文档，也别指望 IDF 的其它部分知道我们换过。
 *   另注：usb_wrap_ll_phy_select() 在 v5.4.3 / v5.5.1 及更早版本有 switch 漏 break
 *   的 bug，phy_idx=0 是静默空操作（espressif/esp-idf#17831 修）。本工程用的
 *   IDF v6.0 已含 break，不受影响。
 *
 * ── 顺带澄清一条**曾经写在这里的错误结论**（别再照抄）──
 *   「USJ 从 bootloader 起就使能着 PHY1 的焊盘，跟 I2S 打架」——**不成立**。
 *   CONFIG_USJ_ENABLE_USB_SERIAL_JTAG=n 时，IDF 在 app_main 之前就已经清掉了
 *   USB_SERIAL_JTAG.conf0.usb_pad_enable 并门控了 USJ 时钟：
 *       esp_system/port/soc/esp32p4/clk.c:238-242 → esp_hal_clock/esp32p4/clk_gate_ll.h:330-336
 *           REG_CLR_BIT(USB_SERIAL_JTAG_CONF0_REG, USB_SERIAL_JTAG_USB_PAD_ENABLE);
 *           REG_CLR_BIT(HP_SYS_CLKRST_SOC_CLK_CTRL2_REG, ..._USB_DEVICE_APB_CLK_EN);
 *   所以 CONFIG_AIO_USJ_RELEASE_PHY_PADS 那档**是空操作**（还多余地把 USJ 时钟又打开了）。
 */

/* 喇叭功放使能：与 LCD_EN(PIN4) / TOUCH_EN(PIN5) 同在 0x43 那颗 PI4IOE5V6408 上
 * （esp-bsp 的 BSP_SPEAKER_EN = IO_EXPANDER_PIN_NUM_1，其 BSP_IO_EXPANDER_ADDRESS
 * 即 ..._ADDRESS_LOW = 0x43）。功放**没有**独立 GPIO：esp-bsp 的
 * BSP_POWER_AMP_IO = GPIO_NUM_NC，所以 es8388_codec_cfg_t.pa_pin 那条路是空操作
 * （es8388.c 见 pa_pin == -1 直接 return），必须由我们经 IO 扩展自己驱动。 */
#define IOEXP_PIN_SPEAKER_EN  IO_EXPANDER_PIN_NUM_1

/* ⚠️ 两种 I2C 地址形式必须分开定名：i2c_master_probe() 收 **7 bit**，而
 * esp_codec_dev 的 audio_codec_i2c_cfg_t.addr 收 **8 bit**（驱动内部再 >>1，见
 * platform/audio_codec_ctrl_i2c.c）。混用的症状是 codec 初始化失败，或把寄存器
 * 写到别的器件上 —— 而 I2C 写没有任何反馈。 */
#define ES8388_I2C_ADDR7   0x10 /* 播放 codec，内部 I2C（实测 i2cscan 已应答） */
#define ES8388_I2C_ADDR8   0x20 /* == ES8388_CODEC_DEFAULT_ADDR */
#define ES7210_I2C_ADDR7   0x40 /* 双麦录音前端 */
#define ES7210_I2C_ADDR8   0x80 /* == ES7210_CODEC_DEFAULT_ADDR */

/* 面板原生分辨率（竖屏）与 DSI 参数 */
#define PANEL_W            720
#define PANEL_H            1280
#define DSI_LANE_NUM       2
#define DSI_LANE_MBPS      1000
#define DSI_PHY_LDO_CHAN   3     /* LDO_VO3 → VDD_MIPI_DPHY */
#define DSI_PHY_LDO_MV     2500

/*
 * 对 host 声明的 GUD 分辨率（横向）。USB-C 只有 12 Mbps 全速，720p 整帧 1.84MB
 * 约需 1.8 秒，交互不可用；640×360 整帧 460KB，且相对面板恰为整数 2 倍，
 * PPA 放大无插值伪影。GUD_W*2 == PANEL_H、GUD_H*2 == PANEL_W（因为要旋转 90°）。
 */
#define GUD_W              640
#define GUD_H              360
#define GUD_SCALE          2

_Static_assert(GUD_W * GUD_SCALE == PANEL_H, "GUD 宽度放大后应等于面板高度(旋转 90°)");
_Static_assert(GUD_H * GUD_SCALE == PANEL_W, "GUD 高度放大后应等于面板宽度(旋转 90°)");
