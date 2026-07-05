## Context

tspi-rk3566 已有成熟的 AMP RT-Thread 从核链路（见 `openspec/changes/archive/2026-07-02-add-amp-rt-thread-mode`）：cpu3 由 AArch64 切 AArch32 当协处理器，Linux 跑 3 核当 master，`amp-rtt` product 经 `:amp-rtt` 条件键接好 U-Boot AMP loader、内核 amp dts（`tspi-rk3566-amp`，patch `0003` 注入）、rpmsg 字符设备、amp 分区、以及 `mode=rt-thread` 的 scons 从核构建（`builder/platforms/rockchip/amp.py` 的 `_compile_rtthread`）。

本次要在这条链路上挂第一个真实负载：RT-Thread 从核直接驱动三相无刷电机，架构从第一天起就朝 FOC（磁场定向控制）搭，里程碑 1 先做开环 SVPWM 让电机转起来。

关键约束（均已核对源码）：
- **RT-Thread app = overlay**：`amp.py` 的 `_compile_rtthread` 只把 app 的 `applications/`（拷入 staged BSP）+ 可选 `.config`（按符号合并进 BSP `.config`）叠上去，**绝不碰 BSP 的 `board/`**。故引脚 IOMUX 无法走 BSP 的 `board/rk3568_evb1/iomux.c`。
- **外设驱动齐备但默认关**：BSP `.config` 默认 `RT_USING_PIN=y`，但 `RT_USING_I2C` / `RT_USING_PWM` 均 `is not set`；`common/drivers` 有 `drv_i2c.c`/`drv_pwm.c`/`drv_gpio.c`，HAL 有 `hal_i2c`/`hal_pwm`/`hal_gpio`/`HAL_PINCTRL`。
- **product 是纯声明**：`products` 列表 + `:product` 条件键（`builder/config/merge.py:resolve_conditions` 单值精确匹配，不支持一键多 product），故新 product 需把 `:amp-rtt` 那套键复制成 `:foc`。
- **引脚归属**（已与用户确认）：i2c2 + pwm12/13/14 + gpio3_a5/a4 整组交给 RT-Thread，Linux 侧全部释放，避免双核抢 pinctrl/GRF。

## Goals / Non-Goals

**Goals:**
- 新增 `tspi-rk3566-foc` product，最大化复用 `amp-rtt` 基建，改动面收敛到「1 个 config.py + 1 个 dtso + 1 个 app」。
- app 从第一天即 FOC 结构（Clarke/Park/SVPWM 三件套），里程碑 1 仅把 θ 源接成开环匀速，里程碑 2 换成编码器真值即闭环，SVPWM 与逆变换零返工。
- 三个既有 product（default/amp/amp-rtt）解析结果字节级不变。

**Non-Goals:**
- 闭环 FOC（编码器读取、电流采样、正 Clarke/Park、id/iq PI 环、速度环）——里程碑 2。
- 改动任何 AMP 通用机制（amp.py / BSP / 内核 patch / rpmsg link-id）。
- Linux↔RT-Thread 电机遥测/控制 rpmsg 通道；电机保护（过流/堵转/温度）。

## Decisions

### 决策 1：foc = amp-rtt 的特化，走 `:foc` 条件键复制

foc product 与 amp-rtt 的唯一实质差异是从核固件 app（`app:foc` = `rk3568_amp_rtt_foc`）与电机引脚 overlay。其余（U-Boot AMP、amp dts、rpmsg、分区、mode=rt-thread）全等。

因 `resolve_conditions` 不支持一键多 product，实现上把 `config.py` 中每个带 `:amp-rtt` 的键**复制**一份为 `:foc`（`amp.enabled/mode/app`、`bootloader.+defconfig`、`kernel.dts/+defconfig`、`partitions`）。这与文件现有注释「条件键不支持一键多 product」的既定风格一致。

- **备选**：抽公共 helper 让 amp/amp-rtt/foc 共享——但 config.py 已明确选择显式复制（可读性优先，DRY 让位于「每个 product 一眼看全」）。沿用既有风格，不引入新抽象。

### 决策 2：dtso 走 overlay（复用 amp dts + boot 叠加），语义相对 bldc.dtso 反转

foc product `dts:foc = "tspi-rk3566-amp"`（复用 amp 全量 dts 拿 AMP 基建），电机引脚变更走运行时 overlay `tspi-rk3566-amp-foc.dtbo`，经 `board_overlays` 声明编译、`default_overlays:foc` 启用，boot 时叠加到 `tspi-rk3566-amp.dtb`（i2c2/pwm12 等 label 都在，可正常应用）。

overlay 语义相对 `bldc.dtso` **反转**：bldc 把 i2c2/pwm 打开给 Linux；amp-foc 把 i2c2/pwm12-14 全部 `disabled`、不建 motor pinctrl 组——整组让给 RT-Thread。

- **备选**：再写一个全量 dts patch（把引脚释放烤进 amp dts 的 foc 变体）——更重、要动内核 patch，且用户明确要求走 overlay 复制自 bldc.dtso。否决。

### 决策 3：IOMUX 由 app 代码配，不改 BSP

overlay 机制只带 `applications/` + `.config`，摸不到 BSP 的 `iomux.c`。故 app 在从核启动初始化阶段自行调 `HAL_PINCTRL_SetIOMUX(GPIO_BANKx, GPIO_PIN_xx, PIN_CONFIG_MUX_FUNCn)` 配 pwm12-14 / i2c2 / gpio3_a5/a4。模式照搬 BSP `board/common/iomux_base.c` 的 `i2c0_m0_iomux_config` 等函数。

- **备选**：给 BSP 打 patch 加 iomux 函数——破坏「SDK 只读、app 是 overlay」模型，且 rt-thread app 无 patch 机制。否决。

### 决策 4：里程碑 1 用开环 SVPWM，不用六步

硬件为 3 路 PWM + 全局 EN 的互补栅驱拓扑（三相始终导通），天然适配 SVPWM，无法做经典六步的悬空相。且 SVPWM 是 FOC 的标准末级，代码即 FOC 下半截。里程碑 1 喂「开环匀速 θ + 固定 Uq」，θ 源在里程碑 2 替换为编码器真值即闭环。

- **备选**：六步换相——被 3 PWM+全局 EN 拓扑限制、且与 FOC 目标不同源，用户已改选 SVPWM。否决。

### 决策 5：补 hal_conf.h 的 PWM 门控 + app 走 HAL 直驱 PWM3（不用 drv_pwm）

**查证发现**：rk3568-32 AMP BSP 根本没接 PWM——`hal_conf.h` 对 CRU/GPIO/PINCTRL/I2C/CAN/UART 都有 `#ifdef RT_USING_xxx → #define HAL_xxx_MODULE_ENABLED`，**唯独漏了 PWM**；`drv_pwm.c` 只实例化 PWM0/1/2（无 PWM3，而 pwm12/13/14 = PWM3 通道 0/1/2，`g_pwm3Dev` @ 0xFE700000 在 HAL 里已有）。app overlay（`applications/` + `.config`）改不到 `hal_conf.h`。

**决策**：在 BSP `hal_conf.h` 补 3 行 `#ifdef RT_USING_PWM → #define HAL_PWM_MODULE_ENABLED`（与既有 GPIO/I2C 门控同模式，补齐厂商遗漏的 SDK 能力）；app `.config` 开 `RT_USING_PWM`（触发该门控，使 `hal_pwm.c` 带 body 编译）；app **直接调 HAL_PWM** 驱动 PWM3（`HAL_PWM_Init(PWM3,...)` / `HAL_PWM_SetConfig` / `HAL_PWM_Enable`），**不碰 `drv_pwm.c`、绕开 RT-Thread PWM device 框架**。GPIO 用现成 `RT_USING_PIN` + `rt_pin_write`。I2C 留里程碑 2 再开 `RT_USING_I2C`。

理由：① SVPWM 要三通道中心对齐（`HAL_PWM_CENTER_ALIGNED` 已有）+ 每周期同步刷新（PWM3 `GLOBAL_LOCK` 原子更新，HAL 已支持），RT device 的 per-channel ioctl 不便表达，HAL 直驱是 FOC 正道；② 补 drv_pwm 的 PWM3 实例既无必要又是更大的 SDK 改动，HAL 直驱只需 hal_conf.h 3 行。

- **备选（app 自带 PWM3 寄存器 MMIO 驱动，SDK 零改）**：可保 SDK 完全不动，但要在 app 侧重写 ~120 行 center-aligned + global-lock 寄存器代码，重复造 HAL 已有的轮子。用户已确认「SDK 能力缺失就补 SDK」，故取补 hal_conf.h。否决。

## Risks / Trade-offs

- **[SVPWM 需中心对齐互补 PWM + 每周期同步刷新占空比]** → 已查证：`HAL_PWM_CENTER_ALIGNED` 与 PWM3 `GLOBAL_LOCK`（多通道原子更新）在 HAL 里均已支持，走 HAL 直驱（见决策 5）。SVPWM 更新节拍由 app 定时器 ISR 驱动（`HAL_TIMER` 已在 hal_conf.h 使能），待 4.x/5.x 实现时对 `hal_pwm.h` 定具体调用序列。
- **[三相栅驱芯片型号 / EN 语义未知]** → 需查原理图确认 EN 是全局使能还是可分相；死区、有源电平极性需按芯片手册定。里程碑 1 代码留注释标明待确认点，不阻塞骨架落地。
- **[双核抢 pinctrl/GRF]** → 已由 dtso 把整组引脚从 Linux 释放规避；RT-Thread 独占 IOMUX 配置。需验证 Linux 侧确实不再触碰这些寄存器。
- **[amp 布局分区变更]** → foc 复用 `_AMP_PARTITIONS`，与 amp/amp-rtt 布局一致；从非 amp 布局首次切 foc 需整盘刷写（与 amp product 同约束，已知）。

## Migration Plan

1. 加 config.py `:foc` 条件键 + 新 dtso + 新 app 骨架（本变更实现阶段）。
2. `lunch tspi-rk3566-foc-debug` → `flange build`，验证 amp.img 产出、default/amp/amp-rtt 解析不变（可 diff resolve 结果）。
3. 整盘刷写上板，从核 finsh 控制台验证 `foc` 命令与开环 SVPWM 电机旋转。
4. 回退：foc 是纯增量（新 product + 新文件），删除 `:foc` 键与新文件即回到现状，既有 product 不受影响。

## Open Questions

- 三相栅极驱动芯片型号、EN(gpio3_a5) 的语义（全局/分相）、死区与有源电平极性？（查板卡原理图/BOM；里程碑 1 代码留注释标明待确认，先按「全局 EN + 高有效」假设）
- SVPWM 更新节拍用哪个硬件 TIMER 做 ISR、频率取多少（如 10~20kHz）？（实现 5.x 时对 `hal_pwm.h`/`hal_timer.h` 定；PWM3 `GLOBAL_LOCK` 保证三通道占空比原子生效）

**已解决**：~~rockchip PWM 是否支持中心对齐 + 同步刷新~~ → 支持（`HAL_PWM_CENTER_ALIGNED` + PWM3 `GLOBAL_LOCK`），走 HAL 直驱；~~PWM 通道 Kconfig 符号~~ → 不走 drv_pwm，无需 `BSP_USING_PWMxx`，仅在 hal_conf.h 补 `RT_USING_PWM→HAL_PWM` 门控（见决策 5）。

---

# 里程碑 3：有感电压 FOC 闭环控制（级联速度/位置环）

## Context

里程碑 2 的有感电压模式（编码器电角 + 固定 Uq，θ_e 来自 AS5600）已上板读通编码器、平滑旋转。里程碑 3 在其上加闭环：**去掉开环 spin 模式**，基于 AS5600 位置反馈（**无电流采样**）实现**速度控制**与**位置控制**。经与用户确认：级联结构、多圈位置、机械单位（rad/rad·s⁻¹）、位置环 PID 结构但默认纯 P。

## 架构（级联，全在现有 1kHz 控制线程内）

```
位置环(PID,默认纯P)      速度环(PI)            电压 FOC（里程碑2 现成）
target_pos ─┬─[Kp,Ki,Kd]─→ ω_set ─┬─[Kp,Ki]─→ Uq ─→ foc_apply(θ_enc, sign·Uq)
            │  (限速 ±vlim)        │  (抗饱和)          ↑
        pos_meas               ω_meas          θ_enc=enc_dir·pp·(mech−offset)
        (多圈累加)             (位置差分+EMA)   （里程碑2 通路，不动）
```

- 最内层复用里程碑 2 的 sensored 电压 FOC 末级，外环只产生 Uq（及其符号）。
- 三模式共用该级联，按注入层分：voltage 直接给 Uq；speed 从速度环注入；position 走完整级联。

## Decisions

### 决策 3.1：级联，积分只放内环（速度 PI），位置环默认纯 P
两积分器串联（位置 I + 速度 I）难稳、抗饱和棘手；工业伺服（位置 P→速度 PI→电流 PI）即此结构。级联下**纯 P 位置环 + PI 速度环的位置稳态误差理论为 0**（pos_err≠0 → ω_set≠0 → 速度环持续驱动至到位）。位置环仍做成 **PID 结构但 Ki/Kd 默认 0**：电压模式有静摩擦、接近目标时 ω_set 过小可能贴不到位，按需加少量 pos.ki 主动消残差；pos.kd 一般不需要（速度环已提供阻尼）。
- **备选**：位置直接 PID→Uq（非级联）。位置环无速度限制/阻尼、高增益易超调振荡。否决。

### 决策 3.2：多圈位置（软件翻圈累加）
AS5600 单圈绝对（0~2π）。每 tick 读机械角，与上次比较：Δ>π 判负向翻圈、Δ<−π 判正向翻圈，累加 turns。`pos_meas = turns·2π + mech`（连续多圈 rad）。target 同单位、可任意多圈。

### 决策 3.3：速度估计 = 多圈位置差分 + EMA 低通
无独立测速硬件。`ω_raw=(pos_meas−pos_prev)/dt`；12-bit 编码器在 1kHz 下低速量化噪声大，过 EMA：`ω_meas += α·(ω_raw−ω_meas)`，α 可调（默认偏小以抑噪）。必要时速度环降到每 N tick 跑一次改善低速分辨率（先按 1kHz + EMA）。

### 决策 3.4：三模式，删开环 spin
`foc mode voltage|speed|position`。删除里程碑 1 的开环匀速强拖（`foc speed <erad/s>` 那套）与其 omega_e 状态；标定内部仍用固定电压矢量（不受影响）。voltage 模式保留（手动 Uq，查线序/力矩方向/标定用）。

### 决策 3.5：限幅 / 抗饱和 / bumpless
- Uq clamp `[−UQ_MAX, +UQ_MAX]`，UQ_MAX=0.55（SVPWM 线性区 0.577 留裕度）。
- 速度环抗积分饱和：Uq 触限时冻结积分累加。
- 位置环输出 ω_set clamp `±vlim`（防大位置误差狂冲）。
- `dis`：清零速度环/位置环积分、target=当前 pos_meas（bumpless）、EN 拉低、PWM 卸力。

## Components（新增/改动，全在 foc.c/foc.h）

- `foc_pos_update()`：读编码器 → 更新多圈 pos_meas → 差分+EMA 得 ω_meas。每 tick 调。
- `foc_speed_pi()`：ω_err → Uq（PI + 抗饱和 + 限幅）。
- `foc_position_pid()`：pos_err → ω_set（PID，默认 P；限速）。
- 控制线程按 mode 分发：voltage=直给 Uq；speed=foc_speed_pi；position=foc_position_pid→foc_speed_pi。
- 命令扩展：`mode/spd/pos/gain`；`enc_dir`/`dir` 分离沿用里程碑 2。

## Risks / Trade-offs

- **[无电流环 → 力矩=电压开环]** 负载/反电动势影响速度精度、力矩非线性。→ 里程碑 3 目标是位置/速度闭环，可接受；电流环留里程碑 4（非本次）。
- **[低速测速量化噪声]** → EMA 滤波；调 α；必要时降速度环速率。已列为整定项。
- **[位置双积分不稳]** → 默认 pos.ki=0；加 I 时带抗饱和、小步整定。
- **[EMA/差分相位滞后]** 高增益下可能振荡 → 增益默认 0、上板从小往大整定，status 打印便于观察。

## Open Questions（里程碑 3）

- 速度环是否需降到 <1kHz 以改善低速测速分辨率？先 1kHz+EMA，上板看噪声再定。
- vlim / UQ_MAX / EMA α 的合理默认值？先给保守默认，上板整定。
