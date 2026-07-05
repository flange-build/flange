---
title: rk3568_amp_rtt_foc
type: app
status: wip
sources:
  - components/app/rk3568_amp_rtt_foc/app.yaml
  - components/app/rk3568_amp_rtt_foc/.config
  - components/app/rk3568_amp_rtt_foc/applications/foc.c
  - components/app/rk3568_amp_rtt_foc/applications/foc.h
  - components/app/rk3568_amp_rtt_foc/applications/as5600.c
related:
  - "[[tspi-rk3566]]"
  - "[[AMP 协处理器与 rpmsg]]"
  - "[[amp 构建器]]"
updated: 2026-07-06
---

## TL;DR

tspi-rk3566 `foc` product 的 RT-Thread AMP 从核固件：cpu3 直接驱动三相无刷电机，AS5600 磁编码器位置反馈、**无电流采样**，做有感电压 FOC 的级联速度/位置闭环。finsh 命令 `foc`。

## 控制架构（全在 1kHz 控制线程）

`位置环 PID(默认纯 P) → ω_set → 速度环 PI(抗饱和) → Uq → 反 Park+SVPWM → HAL_PWM PWM3`

- 电角 = `enc_dir·pp·(mech−offset)`（pp=7，calib 测 enc_dir/offset）
- 多圈位置累加 + 差分/EMA 测速；三模式 voltage/speed/position；机械 rad 单位

## 关键代码位置

- `foc.c`：`foc_ctrl_entry`（分发）、`foc_pos_update`/`foc_speed_pi`/`foc_position_pid`、`foc_calib`、`foc_modulate`（SVPWM）
- `as5600.c`：HAL_I2C 直驱轮询；`as5600_ungate_clk` 每次传输前调
- 引脚/PWM/GPIO：`foc_iomux_init`/`foc_pwm_init`

## 易踩坑（AMP + FOC）

- **PWM mux**：pwm12/13=func2、pwm14=func1（取自内核 rk3568-pinctrl.dtsi，非凭记忆）
- **I2C 时钟**：CRU 主/从核共享，Linux `clk_disable_unused` 会门控 disabled 的 i2c2 + 留其于复位态 → **每次传输前重开门控**（HAL_CRU_ClkEnable 三门控：PCLK/CLK_I2C2 + 共享 CLK_I2C）+ 脉冲解复位
- **标定 90°**：反 Park(Vq) 使 `foc_apply(θ)` 磁场落 θ+90°；对齐须 `foc_apply(−π/2)` 才把转子 d 轴拉到电角 0
- **忙等饿死 finsh**：控制线程用 `rt_thread_mdelay` 让出，勿 `HAL_DelayUs` 自旋
- **gpio3_a4 是栅驱故障脚**（输入只读），方向由软件（转矩矢量符号）做

## 延伸阅读

- 演进（里程碑 1 开环→2 有感→3 闭环）见 `openspec/changes/archive/…-foc-svpwm`
- HAL 直驱 PWM3/I2C2 的 SDK 缺口补法见 [[amp 构建器]]
