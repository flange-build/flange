## 1. 前置查证（已完成，结论见下）

- [x] 1.1 查证 PWM 接线：pwm12/13/14 = PWM3 通道 0/1/2（`g_pwm3Dev` @ 0xFE700000 HAL 已有）。`drv_pwm.c` 只实例化 PWM0/1/2、无 PWM3。**结论**：不走 drv_pwm，app 走 HAL 直驱 PWM3。
- [x] 1.2 查证 HAL PWM 能力：`HAL_PWM_CENTER_ALIGNED` 与 PWM3 `GLOBAL_LOCK`（三通道原子刷新）均已支持。**但** `hal_conf.h` 缺 `RT_USING_PWM→HAL_PWM_MODULE_ENABLED` 门控（厂商遗漏）。**结论**：补 hal_conf.h 3 行（见任务组 2A）+ app .config 开 RT_USING_PWM + HAL 直驱；SVPWM 节拍用硬件 TIMER ISR（HAL_TIMER 已使能）。
- [ ] 1.3 查板卡原理图/BOM，确认三相栅极驱动芯片型号、EN(gpio3_a5) 语义（全局/分相）、死区与有源电平极性；结论写进 app 代码注释（阻塞上板 7.x，不阻塞代码骨架；先按「全局 EN + 高有效」假设并留注释）

## 2A. 补 SDK PWM 能力（rk3568-32 BSP hal_conf.h）

- [x] 2A.1 `components/amp/rockchip/rt-thread/bsp/rockchip/rk3568-32/hal_conf.h`：仿 `#ifdef RT_USING_PIN → HAL_GPIO/PINCTRL` 模式，补 `#ifdef RT_USING_PWM → #define HAL_PWM_MODULE_ENABLED`（补厂商遗漏，加注释说明）

## 2. foc product 接线（config.py）

- [x] 2.1 `components/board/tspi-rk3566/config.py`：`products` 列表加 `"foc"`
- [x] 2.2 `amp` 段增 `enabled:foc=True` / `mode:foc="rt-thread"` / `app:foc="rk3568_amp_rtt_foc"`
- [x] 2.3 `bootloader` 段增 `+defconfig:foc=["CONFIG_AMP=y","CONFIG_ROCKCHIP_AMP=y"]`
- [x] 2.4 `kernel` 段增 `dts:foc="tspi-rk3566-amp"` 与 `+defconfig:foc=["CONFIG_RPMSG_CHAR=y","CONFIG_RPMSG_CTRL=y"]`
- [x] 2.5 增 `partitions:foc = _AMP_PARTITIONS`
- [x] 2.6 `boot` 段：`board_overlays` 追加 `"tspi-rk3566-amp-foc.dtbo"`，增 `default_overlays:foc=["tspi-rk3566-amp-foc.dtbo"]`
- [x] 2.7 验证：`lunch tspi-rk3566-foc-release` 解析成功；diff default/amp/amp-rtt 三 product 解析结果，确认字节级不变

## 3. 电机引脚 overlay（tspi-rk3566-amp-foc.dtso）

- [x] 3.1 复制 `dtso/tspi-rk3566-bldc.dtso` → `dtso/tspi-rk3566-amp-foc.dtso`，改文件头注释（语义：整组引脚从 Linux 摘给 RT-Thread）
- [x] 3.2 反转引脚语义：i2c2 / pwm12 / pwm13 / pwm14 全部改 `status="disabled"`；保留 uart3、xpt2046 的 disabled；删除 `&pinctrl` 的 motor_en/motor_flip 组（Linux 不再 claim）
- [x] 3.3 验证：`flange build`（或单独构建 device-tree-overlay）编译出 `tspi-rk3566-amp-foc.dtbo` 无冲突

## 4. rk3568_amp_rtt_foc app 骨架

- [x] 4.1 `flange create app --type amp --mode scons rk3568_amp_rtt_foc` 生成骨架；核对 `app.yaml`（type=amp / build.system=scons）
- [x] 4.2 写 `.config` 片段：开 `RT_USING_PWM`（触发 hal_conf.h 的 HAL_PWM 门控；不需 `BSP_USING_PWMxx`，走 HAL 直驱）。I2C 留里程碑 2 不开
- [x] 4.3 `applications/` 增 IOMUX 初始化：`HAL_PINCTRL_SetIOMUX` 配 pwm12(gpio3_b7)/pwm13(gpio3_c0)/pwm14(gpio3_c4) 为 PWM，gpio3_a5(EN)/gpio3_a4(FLIP) 为 GPIO，i2c2(gpio0_b5/b6) 为 I2C（占位）

## 5. 开环 SVPWM 驱动（里程碑 1）

- [x] 5.1 实现 SVPWM 末级：输入 (Ualpha, Ubeta) → 三相占空比，经 HAL_PWM 直驱 PWM3 三通道（center-aligned + GLOBAL_LOCK 原子刷新），更新节拍由硬件 TIMER ISR 驱动
- [x] 5.2 实现反 Park（θ, Ud=0, Uq）→ (Ualpha, Ubeta) 逆变换；θ 源做成可替换（里程碑 1 = 开环匀速累加器，注释标明里程碑 2 换编码器真值）
- [x] 5.3 电机使能/去使能逻辑：EN(gpio3_a5) 经 `rt_pin_write` 控制；去使能时停止三相驱动输出
- [x] 5.4 方向经 FLIP(gpio3_a4) 或电角度累加方向控制

## 6. foc finsh 命令

- [x] 6.1 实现 `foc` 命令（仿 `common/tests/mbox_test.c` 的 `MSH_CMD_EXPORT` 模式）：支持 使能/去使能、方向、电压幅值 Uq、电角速度；参数生效后回显当前参数
- [x] 6.2 无参数/非法参数时打印用法提示

## 7. 上板验证（里程碑 1）

- [x] 7.1a `flange build amp` 产出 amp.img（编译验证）：foc.o/main.o 零错误零警告编译、rtthread.elf 链接成功（HAL_PWM/PINCTRL/GPIO/CRU 全解析）、amp.img 340KB 产出
- [x] 7.1b `flange flash` 上板：固件启动、banner 打印正常
- [x] 7.1c 修复 msh 出不来：控制线程 HAL_DelayUs 忙等（优先级 5 > finsh 20）饿死 finsh → 改 rt_thread_mdelay 让出调度器，上板确认 msh 提示符恢复
- [x] 7.2 开环 SVPWM 上板：修正 PWM mux（func2/2/1）后电机在开环 SVPWM 下可转动——里程碑 1 达成。（先前"动一下即卡死"主因是 PWM mux 错写 func5、三相未真正接到引脚）

## 8. AS5600 有感 FOC 电压模式（里程碑 2）

- [x] 8.1 查证 AMP BSP 的 I2C：drv_i2c 已实例化 i2c2 但默认中断驱动；hal_conf.h 已有 RT_USING_I2C→HAL_I2C 门控。**结论**：走 HAL 直驱轮询（`I2C_POLL`），绕开 AMP GIC 中断
- [x] 8.2 `.config` 加 `RT_USING_I2C=y`（触发 HAL_I2C 门控；不开 RT_USING_I2C2 避免 drv_i2c 抢中断）
- [x] 8.3 `as5600.c/.h`：HAL_I2C 直驱轮询读 RAW ANGLE(0x0C) + 状态(0x0B)
- [x] 8.4 foc.h/foc.c：极对数=7、mode(open/sensored)、编码器电角换算、有感模式分支
- [x] 8.5 `foc calib`：对齐电角 0 定零点偏置、正向步进定方向（标定期独占 PWM/EN）
- [x] 8.6 `foc mode/enc` 子命令 + status 扩展；foc_start 初始化 AS5600
- [x] 8.7 编译验证：as5600.o/foc.o/main.o 零错误、HAL_I2C 链接通过、rtthread.bin 产出
- [x] 8.8a 修 PWM mux bug：内核权威 rk3568-pinctrl.dtsi 证实 pwm12/13=func2、pwm14=func1（原凭记忆写的 func5 全错，里程碑 1 三相 PWM 未真正接到引脚，是电机不转的真因之一）；i2c2=func1 原本正确
- [x] 8.8b I2C 诊断增强：foc enc 区分 超时(总线无响应)/NODEV(NACK)/协议错 + 打印 clk 与 hal_err
- [x] 8.8c 修 I2C 超时根因：foc i2cdiag 定位——IOMUX 正确(b5/b6 sel=1)但 I2C2.CLKDIV 恒 0=控制器被 Linux 留在复位态（i2c2 dtb disabled）。加 HAL_CRU_ClkResetAssert/Deassert 脉冲解复位
- [x] 8.8d 修 I2C 超时终极根因：foc i2cdiag 立即读回证实——Linux 主核 clk_disable_unused() 把 i2c2 时钟当"未使用"门控关闭（i2c2 dtb disabled），盖过从核 init 时的使能。CRU 是主/从核共享资源。修复：把时钟门控使能从 init 挪到每次传输前（clk_disable_unused 启动后期跑一次、之后不再碰，故运行时开门控即稳定）
- [x] 8.8 上板验证 `foc enc`：读到 AS5600 真实角度、转轴 raw 值跟随变化、MD 磁铁检测正常 ✓
- [x] 8.9a 修标定 90° 偏置 bug：反 Park(Vq) 使 foc_apply(θ) 的磁场在电角 θ+90°；原标定对齐调 foc_apply(0) 把转子拉到电角 90° 却当作 0 记录 offset → 运行时磁场落在 d 轴、只有保持转矩不转（症状:转一下即锁、推一下动一下）。改对齐为 foc_apply(−π/2)，磁场落电角 0、转子 d 轴真到 0
- [x] 8.9 上板 `foc uq <值>` → `foc calib` → `foc mode sensored` → `foc en`：确认电机从静止平滑旋转
- [ ] 8.10 核实硬件假设（EN 极性/栅驱型号，task 1.3）；据实翻转 FOC_EN_ACTIVE_HIGH/FOC_PWM_POLARITY 如需

## 9. 收尾

- [x] 9.1 更新 `wiki/log.md` / `wiki/boards/tspi-rk3566.md` 记录 foc product、里程碑 1+2 结果

## 10. 闭环速度/位置控制（里程碑 3）

- [x] 10.1 多圈位置追踪 foc_pos_update()：读编码器机械角、过零翻圈累加 pos_meas（rad）
- [x] 10.2 速度估计：pos 差分 + EMA 低通得 ω_meas（α 可调）
- [x] 10.3 速度环 PI foc_speed_pi()：ω_err→Uq，抗积分饱和 + Uq 限幅 [−0.55,0.55]
- [x] 10.4 位置环 PID foc_position_pid()：pos_err→ω_set，默认纯 P（Ki/Kd=0），输出限速 ±vlim
- [x] 10.5 模式重构：删开环 spin，新增 voltage/speed/position 三模式分发；dis 时 bumpless 复位
- [x] 10.6 命令扩展：foc mode/spd/pos/gain（spd.kp/ki、pos.kp/ki/kd、vlim、slew）；status 打印增益
- [x] 10.7 编译验证
- [x] 10.8a 写经验默认增益（spd.kp=0.01/ki=0.1、pos.kp=5、vlim=20、slew=0.1；保守起步、安全）
- [ ] 10.8b 上板精细整定到满意手感（用户进行中）
