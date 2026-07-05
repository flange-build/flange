## Why

tspi-rk3566 已打通 AMP RT-Thread 从核（cpu3 跑 RT-Thread、Linux↔RT-Thread rpmsg echo 上板验证）。下一步要把这个从核用起来做**实时电机控制**：让 RT-Thread 直接驱动一台三相无刷电机（BLDC/PMSM），最终走 FOC（Field-Oriented Control，磁场定向控制）。实时电流/换相环必须跑在协处理器上（Linux 不适合硬实时），AMP 架构正是为此准备的，现在补上第一个真实负载。

## What Changes

- 新增 product `tspi-rk3566-foc`：复用 `amp-rtt` 的全部 AMP 基建（U-Boot AMP loader、`tspi-rk3566-amp` 内核 dts、rpmsg 字符设备、amp 分区表、mode=rt-thread 的 scons 构建），仅把从核固件换成新 FOC app。
- 新增 RT-Thread AMP app `rk3568_amp_rtt_foc`（`type: amp` / `build.system: scons`，overlay 形态）：
  - 启动时由 app 自行配置 IOMUX（i2c2、pwm12/13/14、gpio3_a5=EN、gpio3_a4=FLIP）——BSP 的 `board/iomux.c` 不在 overlay 可改范围内，故引脚复用由 app 代码经 `HAL_PINCTRL_SetIOMUX` 完成。
  - **里程碑 1（本次范围）**：开环 SVPWM（反 Park → 反 Clarke → SVPWM → 三相占空比），给匀速递增电角度把电机拖起来，不读编码器、不闭环。代码骨架即完整 FOC 的下半截。
  - 新增 `foc` msh/finsh 命令，控制 使能/方向(FLIP)/电压幅值 Uq/电角速度。
- 新增 DTS overlay `components/board/tspi-rk3566/dtso/tspi-rk3566-amp-foc.dtso`（由 `tspi-rk3566-bldc.dtso` 复制并反转语义）：把 i2c2 + pwm12/13/14 + gpio3_a5/a4 整组从 Linux **摘掉**（disabled/不 claim），整组交给 RT-Thread 独占，避免双核抢同一组 pinctrl/GRF 寄存器。仅 foc product 经 `default_overlays:foc` 启用。
- `default` / `amp` / `amp-rtt` 三个既有 product 完全不受影响（所有改动走 `:foc` 条件键 + 新增文件）。

## 里程碑 2（本变更已扩入）：AS5600 有感 FOC 电压模式

里程碑 1（开环 SVPWM）上板发现开环强拖从静止易失步（转子跟不上匀速旋转磁场，抖一下即锁死）——这正是 FOC 要用编码器解决的。故本变更扩入里程碑 2 的第一步「有感电压模式」：

- i2c2 使能（`.config` 开 `RT_USING_I2C` 触发 hal_conf.h 的 HAL_I2C 门控），AS5600 走 **HAL 直驱 + 轮询**（与 PWM 一致，绕开 AMP 从核 GIC 中断路由；不用 drv_i2c 中断路径）。
- 新 `as5600.c/.h`：读 RAW ANGLE（0x0C）12-bit 转子角、状态（0x0B 磁铁检测）。
- 电角 = `normalize(dir·极对数·(机械角 − 零点偏置))`，极对数=7（本电机）。
- `foc calib`：施加电角 0 矢量对齐转子读机械角定零点偏置，正向步进定方向符号。
- `foc mode open|sensored`、`foc enc`（读编码器调试）子命令；SENSORED 模式把控制线程的 theta 源从开环累加换成编码器真值，SVPWM/反 Park/PWM3 全复用。

## Non-Goals（非目标）

- **不做电流环 FOC**：电流采样、正 Clarke/Park、id/iq PI 电流环、速度环——留到后续。里程碑 2 是**有感电压模式**（θ 用编码器真值 + 固定 Uq，不采电流），已足够让电机从静止平滑转起来。
- **不改动 AMP 通用机制**：`amp.py` 构建器、内核 amp dts patch、rpmsg link-id 约定一律复用，不修改。**例外**：rk3568-32 AMP BSP 的 `hal_conf.h` 缺 `RT_USING_PWM → HAL_PWM_MODULE_ENABLED` 门控（厂商遗漏，GPIO/I2C 等均已按此模式接线），本次补上这 3 行以补齐 SDK 的 PWM 能力——属「补 SDK 本身缺失的能力」，不算业务逻辑改动。drv_pwm.c 不动（app 走 HAL 直驱、绕开 RT device 框架）。
- **不实现 Linux↔RT-Thread 的电机遥测/控制 rpmsg 通道**：里程碑 1 仅用板上 finsh `foc` 命令控制；rpmsg 控制面留待后续。
- **不做电机参数辨识、保护（过流/堵转/温度）逻辑**。

## Capabilities

### New Capabilities
- `tspi-rk3566-foc`: tspi-rk3566 的 FOC 电机驱动能力——foc product 的产品接线（复用 amp-rtt 基建 + `:foc` 条件键）、`rk3568_amp_rtt_foc` RT-Thread AMP app（app 自配 IOMUX、开环 SVPWM 三相驱动、`foc` finsh 命令）、以及把电机引脚整组从 Linux 摘给 RT-Thread 的 `tspi-rk3566-amp-foc` overlay。

### Modified Capabilities
<!-- 无。foc 复用现有 AMP 机制（amp-firmware-build / amp-runtime-bringup / amp-app-scaffold / board-config），不改动其任何 spec 级行为。 -->

## Impact

- 新增文件：
  - `components/board/tspi-rk3566/dtso/tspi-rk3566-amp-foc.dtso`
  - `components/app/rk3568_amp_rtt_foc/`（`app.yaml` + `applications/`：main + SVPWM/命令源，可选 `.config` 片段开 `RT_USING_PWM` + 三通道）
- 修改文件：
  - `components/board/tspi-rk3566/config.py`：`products` 加 `foc`；`amp`/`bootloader`/`kernel`/`partitions`/`boot` 各段增 `:foc` 条件键（复制 `:amp-rtt` 语义，`app:foc` 指向新 app，`default_overlays:foc` 启用新 overlay）。
  - `components/amp/rockchip/rt-thread/bsp/rockchip/rk3568-32/hal_conf.h`：补 `#ifdef RT_USING_PWM → #define HAL_PWM_MODULE_ENABLED`（3 行，补厂商遗漏的 PWM 门控）。
- 复用（不改）：`builder/platforms/rockchip/amp.py`（mode=rt-thread 路径）、`drv_pwm.c`、HAL 源（`hal_pwm`/`hal_gpio`/`hal_i2c`/`HAL_PINCTRL`，仅引用）、内核 patch `0003-add-tspi-rk3566-amp-dts.patch`。
- 硬件依赖（写代码时需查证，不阻塞提案）：三相栅极驱动芯片型号 / EN 语义、SVPWM 所需的中心对齐互补 PWM 与刷新率是否被 rockchip `drv_pwm`/`hal_pwm` 支持。
