## ADDED Requirements

### Requirement: foc product 产品接线

tspi-rk3566 的 `config.py` SHALL 声明 product `foc`，并通过 `:foc` 条件键复用 `amp-rtt` product 的全部 AMP 基建：U-Boot AMP loader（`CONFIG_AMP` + `CONFIG_ROCKCHIP_AMP`）、内核 amp dts（`tspi-rk3566-amp`）、rpmsg 字符设备（`CONFIG_RPMSG_CHAR` + `CONFIG_RPMSG_CTRL`）、amp 分区表（`_AMP_PARTITIONS`）、以及 `mode:foc = "rt-thread"` 的 scons 从核构建。`app:foc` SHALL 指向 `rk3568_amp_rtt_foc`。`default` / `amp` / `amp-rtt` 三个既有 product 的解析结果 SHALL 不受任何影响。

#### Scenario: lunch foc target 可选
- **WHEN** 执行 `lunch tspi-rk3566-foc-release`（或 `-debug`）
- **THEN** 配置解析成功，`config.amp.enabled` 为 True、`config.amp.mode` 为 `"rt-thread"`、`config.amp.app` 为 `"rk3568_amp_rtt_foc"`

#### Scenario: foc 复用 amp dts 与分区
- **WHEN** 解析 `tspi-rk3566-foc-*` 配置
- **THEN** `config.kernel.dts` 为 `"tspi-rk3566-amp"`，且分区表等于 `amp` / `amp-rtt` 所用的 `_AMP_PARTITIONS`（含 16MiB amp 分区）

#### Scenario: default product 不受影响
- **WHEN** 解析 `tspi-rk3566-default-*` 配置
- **THEN** `config.amp` 未启用、`config.kernel.dts` 仍为基础板 dts、分区沿用 SoC 默认布局、`tspi-rk3566-amp-foc` overlay 不出现在 `default_overlays` 中

### Requirement: 电机引脚整组从 Linux 摘出

新增 DTS overlay `components/board/tspi-rk3566/dtso/tspi-rk3566-amp-foc.dtso` SHALL 把电机相关引脚整组从 Linux 释放，交给 RT-Thread 从核独占：i2c2、pwm12、pwm13、pwm14 SHALL 置为 `status = "disabled"`；占用 gpio3_a5（EN）的 `xpt2046` 电阻触摸与占用 pwm 撞脚的 uart3 SHALL 保持 disabled；overlay SHALL NOT 为 gpio3_a5 / gpio3_a4 建立 Linux 侧 pinctrl claim。该 overlay SHALL 仅经 `default_overlays:foc` 在 foc product 启用，且经 `board_overlays` 声明编译。

#### Scenario: overlay 仅 foc 启用
- **WHEN** 解析 `tspi-rk3566-foc-*` 配置
- **THEN** `tspi-rk3566-amp-foc.dtbo` 出现在运行时启用的 overlay 列表（extlinux `fdtoverlays`）中

#### Scenario: Linux 不占用电机引脚
- **WHEN** foc product 系统启动、overlay 应用到 `tspi-rk3566-amp.dtb` 之后
- **THEN** Linux 侧 i2c2 / pwm12 / pwm13 / pwm14 节点均为 disabled，Linux pinctrl 不 claim gpio3_a5 / gpio3_a4

### Requirement: rk3568_amp_rtt_foc App 工程结构

`rk3568_amp_rtt_foc` SHALL 作为 `type: amp`、`build.system: scons` 的 RT-Thread AMP overlay app 存在于 `components/app/rk3568_amp_rtt_foc/`，包含 `app.yaml` 与 `applications/` 目录（叠加到 RT-Thread `rk3568-32` BSP 模板）。若需开启外设（如 `RT_USING_PWM` 及三个 PWM 通道），SHALL 经 app 根目录的 `.config` 片段声明增量，由 amp 构建器合并进 BSP `.config`。App SHALL NOT 修改 RT-Thread BSP 或 HAL SDK 本体。

#### Scenario: 构建产出从核固件
- **WHEN** 对 `tspi-rk3566-foc-*` 执行 `flange build`（amp mode=rt-thread 路径）
- **THEN** 该 app 的 `applications/` 叠加到 BSP 后 scons 构建成功，产出 `rtthread.bin` 并打包为 `amp.img`

### Requirement: App 自配电机引脚 IOMUX

由于 RT-Thread BSP 的 `board/iomux.c` 不在 overlay 可改范围内，`rk3568_amp_rtt_foc` SHALL 在从核启动初始化阶段由 app 代码经 `HAL_PINCTRL_SetIOMUX` 配置电机引脚复用：pwm12（gpio3_b7）、pwm13（gpio3_c0）、pwm14（gpio3_c4）配为对应 PWM 功能；gpio3_a5（EN）、gpio3_a4（FLIP）配为 GPIO；i2c2（gpio0_b5=SCL / gpio0_b6=SDA）配为 I2C 功能（为里程碑 2 占位）。

#### Scenario: 三相 PWM 引脚就绪
- **WHEN** 从核固件启动完成初始化
- **THEN** gpio3_b7 / gpio3_c0 / gpio3_c4 的 IOMUX 已切到 PWM 功能，三路 PWM 可输出

#### Scenario: EN/FLIP GPIO 就绪
- **WHEN** 从核固件启动完成初始化
- **THEN** gpio3_a5 / gpio3_a4 的 IOMUX 为 GPIO，可经 `rt_pin_write` 控制电机使能与方向翻转

### Requirement: 补齐 BSP 的 HAL PWM 门控

rk3568-32 AMP BSP 的 `hal_conf.h` 当前缺 PWM 模块门控（对 GPIO/PINCTRL/I2C/CAN/UART 等均有 `#ifdef RT_USING_xxx → #define HAL_xxx_MODULE_ENABLED`，唯独遗漏 PWM）。本变更 SHALL 在该 `hal_conf.h` 补 `#ifdef RT_USING_PWM → #define HAL_PWM_MODULE_ENABLED`，使 app 在 `.config` 开 `RT_USING_PWM` 后可直接调用 HAL_PWM API 驱动 PWM3。`drv_pwm.c` SHALL NOT 被修改（app 走 HAL 直驱，绕开 RT-Thread PWM device 框架）。

#### Scenario: 开 RT_USING_PWM 后 HAL_PWM 可用
- **WHEN** app `.config` 声明 `RT_USING_PWM=y` 并经 amp 构建器合并进 BSP `.config`、重生成 rtconfig.h
- **THEN** `HAL_PWM_MODULE_ENABLED` 被定义，`hal_pwm.c` 带实现编译，app 对 PWM3 调用 `HAL_PWM_Init`/`HAL_PWM_SetConfig`/`HAL_PWM_Enable` 可链接通过

### Requirement: 开环 SVPWM 三相驱动（里程碑 1）

`rk3568_amp_rtt_foc` SHALL 实现开环 SVPWM 驱动：以一个匀速递增的电角度 θ 与固定电压幅值 Uq 为输入，经反 Park（θ）→ 反 Clarke → SVPWM 生成三相占空比，按固定 PWM 周期同步刷新三路 PWM，把电机拖动旋转。里程碑 1 SHALL NOT 读取磁编码器、SHALL NOT 构成电流或速度闭环。代码结构 SHALL 使 θ 的来源可在里程碑 2 从「开环匀速」替换为「编码器真值」而不重写 SVPWM 与逆变换。

#### Scenario: 使能后电机旋转
- **WHEN** 电机使能（EN 有效）且电压幅值与电角速度为非零
- **THEN** 三相占空比按 SVPWM 随电角度周期性变化，电机持续旋转

#### Scenario: 去使能后停止输出
- **WHEN** 电机去使能（EN 无效）
- **THEN** 三相 PWM 输出停止驱动，电机不再被驱动

### Requirement: AS5600 磁编码器读取（里程碑 2）

`rk3568_amp_rtt_foc` SHALL 经 i2c2 读取 AS5600 磁编码器（从地址 0x36）的 RAW ANGLE（寄存器 0x0C/0x0D，12-bit）作转子位置，及状态寄存器（0x0B）判磁铁检测。I2C 访问 SHALL 走 HAL_I2C 直驱 + 轮询（`I2C_POLL` + 轮询 `HAL_I2C_IRQHandler`），SHALL NOT 依赖 I2C2 中断（避开 AMP 从核 GIC 中断路由）。`.config` SHALL 开 `RT_USING_I2C` 以触发 hal_conf.h 的 HAL_I2C 门控；SHALL NOT 开 `RT_USING_I2C2`（避免 drv_i2c 注册中断驱动设备抢 IRQ）。

#### Scenario: 读一次编码器
- **WHEN** 在 finsh 输入 `foc enc`
- **THEN** 打印 AS5600 原始角（0..4095）、换算机械角（度）与磁铁检测状态位

### Requirement: 编码器电角标定（里程碑 2）

极对数已知（本电机=7）下，`foc calib` SHALL 标定电角零点偏置与方向：施加电角 0 的电压矢量使转子对齐、读机械角作零点偏置；再正向步进一个小电角、读机械角，由机械角变化符号定方向。标定期间 SHALL 独占 PWM/EN（控制线程让出），完成后 SHALL 去使能并置标定完成标志。

#### Scenario: 标定成功
- **WHEN** 已 `foc uq` 设非零幅值后输入 `foc calib`
- **THEN** 转子先对齐后步进，命令回显极对数、零点偏置(mrad)与方向，且标定完成标志置位

#### Scenario: 未给电压幅值
- **WHEN** 在 `uq=0` 时输入 `foc calib`
- **THEN** 提示先设非零 uq，不驱动电机

### Requirement: 有感电压模式（里程碑 2）

`foc mode sensored` 且已标定时，控制线程 SHALL 把电角度来源从开环累加换成 `normalize(dir · 极对数 · (编码器机械角 − 零点偏置))`，施加固定 Uq（不采电流），使电机从静止即受正确定向磁场驱动而平滑旋转。未标定的 sensored SHALL 回退到开环行为。SVPWM、反 Park、PWM3 输出 SHALL 与里程碑 1 完全复用。

#### Scenario: 有感模式平滑旋转
- **WHEN** 标定后 `foc mode sensored`、`foc uq <非零>`、`foc en`
- **THEN** 电角度跟随 AS5600 真实转子位置，电机从静止平滑起转、不失步

#### Scenario: 未标定回退
- **WHEN** 未标定即 `foc mode sensored` 并使能
- **THEN** 控制线程回退到开环强拖，不使用编码器角

### Requirement: foc finsh 命令

`rk3568_amp_rtt_foc` SHALL 经 `MSH_CMD_EXPORT` 注册名为 `foc` 的 finsh/msh 命令，用于在板上从核控制台调整驱动参数。里程碑 1 该命令 SHALL 至少支持：使能/去使能、方向（经 FLIP）、电压幅值 Uq、电角速度。无参数或参数非法时 SHALL 打印用法提示。

#### Scenario: 命令改变驱动参数
- **WHEN** 在 RT-Thread finsh 控制台输入 `foc` 及其参数（如设电角速度与电压幅值）
- **THEN** 开环 SVPWM 驱动按新参数更新旋转速度/力矩，命令回显当前生效参数

#### Scenario: 无参数打印用法
- **WHEN** 输入 `foc` 不带参数
- **THEN** 打印命令用法（可用子命令与参数说明）

## ADDED Requirements（里程碑 3：闭环速度/位置控制）

### Requirement: 多圈位置与速度估计

控制线程 SHALL 每 tick 由 AS5600 机械角维护连续多圈机械位置 `pos_meas`（软件过零翻圈累加，单位 rad），并由其差分经 EMA 低通估计机械角速度 `ω_meas`（rad/s）。无独立测速硬件。

#### Scenario: 多圈累加
- **WHEN** 电机连续正转越过编码器 0/2π 边界多次
- **THEN** `pos_meas` 连续单调增长、不回绕（每翻一圈 +2π）

#### Scenario: 速度估计
- **WHEN** 电机以近似恒定转速旋转
- **THEN** `ω_meas` 收敛到该转速附近，低速时经 EMA 抑制量化噪声

### Requirement: 级联闭环控制（速度环 PI + 位置环 PID）

系统 SHALL 实现级联控制：位置环（PID，默认 Ki=Kd=0 即纯 P，输出限速 ±vlim）产生速度设定值，速度环（PI，抗积分饱和，输出 Uq clamp 到 SVPWM 线性区）产生电压幅值，注入里程碑 2 的 sensored 电压 FOC 末级。积分项仅位于速度环。

#### Scenario: 速度环消稳态误差
- **WHEN** speed 模式下给定目标转速、存在恒定负载
- **THEN** 稳态 `ω_meas` 收敛到目标（速度环积分消除稳态误差）

#### Scenario: 位置到位
- **WHEN** position 模式下给定目标角
- **THEN** 电机转向目标并停在目标角附近（纯 P 位置环 + PI 速度环，稳态位置误差趋于 0）

#### Scenario: Uq 饱和抗积分
- **WHEN** 速度环输出 Uq 达到限幅
- **THEN** 速度环积分冻结、不继续累加（防超调回不来）

### Requirement: 三种运行模式（去掉开环 spin）

`foc mode voltage|speed|position` SHALL 切换运行模式：voltage=手动直给 Uq；speed=速度环；position=位置→速度级联。里程碑 1 的开环匀速强拖模式 SHALL 移除（标定内部仍用固定电压矢量，不受影响）。去使能（`foc dis`）SHALL 清零速度/位置环积分、目标置为当前 `pos_meas`（bumpless）、拉低 EN、卸力 PWM。

#### Scenario: 模式切换
- **WHEN** 依次 `foc mode speed`、`foc spd <rad/s>`、`foc en`
- **THEN** 进入速度闭环、电机趋向目标转速

#### Scenario: 去使能 bumpless
- **WHEN** 运行中 `foc dis`
- **THEN** 积分器清零、目标=当前位置、EN 拉低、无输出；再 `foc en` 不产生跳变冲击

### Requirement: 运行时增益整定

`foc gain <name> <值>` SHALL 支持运行时（免重刷）调整：`spd.kp`/`spd.ki`（速度环）、`pos.kp`/`pos.ki`/`pos.kd`（位置环）、`vlim`（位置环限速）、`slew`（速度估计 EMA α）。增益默认全 0（安全）。`foc status` SHALL 打印全部模式、目标、测量、增益。

#### Scenario: 调增益即时生效
- **WHEN** 运行中 `foc gain spd.kp 0.5`
- **THEN** 速度环立即以新增益运行，无需重启/重刷
