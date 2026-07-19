## Context

RK3506 当前使用 U-Boot/FIT 启动 CPU2 RT-Thread，Linux DTS 直接创建 Rockchip RPMsg
virtio 设备，不使用 remoteproc。内存和通信事实源已经固定：

```text
CPU2 MPIDR       0xF02
普通共享内存     0x03b00000 / 1 MiB
RPMsg vring/pool 0x03c00000 / 2 MiB
CPU2 firmware    0x03e00000 / 1 MiB
link-id          0x02
endpoint         0x3003 / rpmsg-ap3-ch0
mailbox          mailbox0 / mailbox2，IRQ 176
```

Fluxion Runtime 是一个约 10 KiB 量级的可变泛型值，必须由一个控制线程独占。FTS parser
属于主机工具，不应进入目标固件。现有 Web `fluxion.telemetry/v1` 是只读遥测协议，控制
必须使用独立通道。

## Goals / Non-Goals

**Goals:**

- Fluxion 仓库中的 OOT AMP App 能被 `flange build amp` 直接解析、挂载和构建。
- CPU2 运行主机编译后的静态 FTS plan，上电和任意异常都保持 PWM safe。
- RPMsg 支持能力发现、租约、心跳、受限命令、应用 ACK、遥测和故障状态。
- Linux bridge 把遥测映射为现有 `/healthz` + `/telemetry`，并提供独立 `/control`。
- OOT 修改不会因缓存误命中而遗漏。

**Non-Goals:**

- 不加载 remoteproc resource table。
- 不在快环执行 RPMsg、JSON、socket、文件或阻塞锁。
- 不在没有载板原理图和 HIL 证据时实现猜测性的真实 HAL 引脚映射。
- 不动态替换未知 Swift 类型或在电机运行中激活算法包。

## Decisions

### 决策 1：FTS 主机编译，CPU2 只运行静态产物

Web/主机执行 FTS lexer、parser、语义、安全和硬件能力校验，生成
`FOCStaticPipelinePlan`、`FOCStaticOrchestrationPlan` 与配置常量。Embedded Swift
archive 链入 RT-Thread 固件，CPU2 不携带 parser、Foundation 或文件系统依赖。

### 决策 2：Runtime 单一所有者与固定容量跨线程边界

- PWM/ADC ISR 只锁存采样并唤醒高优先级控制线程。
- 控制线程独占静态存储中的 Swift Runtime，在 tick 边界消费 SPSC 命令队列。
- RPMsg 接收线程只做线协议校验、租约状态更新和入队。
- telemetry port 只复制 latest snapshot；低优先级 RPMsg 线程降采样发送，拥塞时覆盖旧帧。
- stop、租约超时、协议故障和硬件 fault 必须触发独立的 board `force_safe`。

### 决策 3：单端点、小端、496 字节以内二进制协议

首版复用已验证的 `0x3003/rpmsg-ap3-ch0`。所有帧使用 24 字节 `FXT1` header：

```text
magic:u32 version:u8 type:u8 flags:u16
sequence:u32 request_id:u32 payload_len:u16 reserved:u16 crc32:u32
```

CRC 覆盖 header 前 20 字节和 payload。总长度不得超过 496 字节。命令显式编号，不复用
Swift enum 内存布局。标量命令使用 `COMMAND=5`；成对 D/Q 给定使用
`REFERENCE_SET=6` 的固定 16 字节 payload：

```text
session:u32 kind:u8 reserved[3] value_d:f32 value_q:f32
```

目标端必须先一次性校验 reserved、kind、finite、向量范围、session、单调 sequence 与对应
per-kind atomic capability，再以一个队列项、一次 lease authorize、一个 control tick 边界和
一次 Swift Runtime 事务同时提交 D/Q；任一检查失败都不得半更新。一个 `REFERENCE_SET`
只关联一个 request_id 和一个 applied/rejected ACK。current/voltage 的 atomic capability 分离，
不能把两条标量 request 宣称为原子事务。

### 决策 4：deadman lease 是控制权限，不是普通心跳

Linux bridge 获取随机 session 的有界租约并周期续租。CPU2 只接受当前 session 且序号
单调的命令；超时、Linux 重启、RPMsg 断开或显式 disarm 时，立即停止 Runtime 并
`force_safe`。Web 不能直接打开 `/dev/rpmsg*`，只连接单一 Linux daemon。

### 决策 5：board HAL 失败关闭

Fluxion OOT app 定义 Current Sensor、Rotor、PWM、Timebase、Fault 的 C hook ABI。默认
production profile 在 hook 未实现、能力不匹配或 `powerStageConnected=false` 时初始化
失败并保持安全。确定性 loopback 仅用于 host/固件构建验收，必须在能力和 health 中声明
`simulated=true`。

### 决策 6：外层容器挂载整个 OOT git worktree

FINAL_CONFIG 的 `external_apps.local_path` 在宿主和容器中分别以项目根解析。shell 在宿主
解析最终绝对路径，查找其 git worktree root，并按相对 Flange 根的位置映射到
`/workspace` 对应路径。挂整个 worktree 而非 App 子目录，使 OOT `Package.swift` 能安全
引用同仓库 Fluxion targets；重复 worktree 去重。

### 决策 7：default 与 fluxion product 分离

`atk-rk3506b-default-*` 不变，继续用于启动/RPMsg 回归。`fluxion` product 才注册两个
本地 OOT App、选择 FOC AMP 固件并安装 bridge。这样 FOC 实验失败时仍有已验证救援基线。

### 决策 8：Embedded Swift ABI 从 RT-Thread BSP 派生并做双重门禁

RK3506 RT-Thread BSP 的 `rtconfig.py DEVICE` 是 CPU/浮点 ABI 单一事实源：Cortex-A7、
NEON-VFPv4、ARM state、hard-float。Swift 使用工具链现有 module 对应的
`armv7-none-none-eabi` triple，并把 BSP flags 通过 `-target-cpu` 与 `-Xcc` 传给 Swift；
`-Xcc -mfloat-abi=hard` 决定 Swift `@_cdecl`/导入 C 边界采用 AAPCS-VFP。
`armv7-none-none-eabihf` 没有 Swift 标准库 module，不能只为名称直观而切换。

当 BSP 声明 `-mfloat-abi=hard` 时，builder 在复制 Swift archive 后和 SCons 最终链接
`rtthread.elf` 后分别执行固定裸机工具链的 `readelf -A`，并要求
`Tag_ABI_VFP_args: VFP registers`。缺失时构建失败，禁止把 soft/base PCS Swift 对象与
hard-float RT-Thread 对象混链。

RK3506 BSP 及其预编译 newlib/libm/libgcc 使用 variable-size enum ABI，因此 Swift C importer
显式使用 `-Xcc -fshort-enums`，并在 archive 与最终 ELF 两个阶段要求
`Tag_ABI_enum_size: small`。builder 不改写 staged BSP 的全局 CFLAGS；强制 BSP 使用
32-bit enum 会与随工具链提供的系统库冲突并产生大量 enum-size 链接告警。线协议仍只使用
固定宽度整数，不依赖任一 C/Swift enum 的内存布局。

### 决策 9：最终 ELF heap 必须由符号与 section 双重证明

`amp.runtime.minimum_heap_size` 是 SoC runtime profile 的必填正整数 byte 数；RK3506B
Fluxion profile 当前要求至少 512 KiB。SCons 最终链接后、生成可刷写 FIT 前，builder 使用
固定裸机工具链执行 `nm -n --defined-only` 与 `readelf -SW`，同时读取
`__heap_begin`/`__heap_end` 和 `.heap`。符号范围与 section 地址/大小必须一致、必须落在
`cpu_base..cpu_base+dram_size` 内，且可用容量不得低于配置门槛；缺符号、范围不一致、越界或
容量不足均失败关闭。

## Risks / Trade-offs

- **1 MiB firmware 余量需持续观测**：2026-07-19 的真实 Docker debug 构建中，最终 ELF
  `Data Size` 为 276.59 KiB，heap 为 653 KiB；相对 512 KiB 门槛仍有 141 KiB 余量，因此
  保留 1 MiB carveout。后续体积增长由 binary/FIT 上限和最终 ELF heap 双门禁拒绝，不能
  静默裁剪安全或诊断代码。
- **20 kHz 调度/WCET 未实测**：首版线程/定时器接线只能证明构建和逻辑；真实电流环前必须
  测 WCET、抖动、deadline miss，并完成 ADC/PWM 同步。
- **功率板资源未知**：RK3506 BSP 有 PWM/SARADC/I2C 能力，但 Linux DTS 资源所有权、
  pinmux、3-PWM/6-PWM、deadtime、编码器和 EN/FAULT 尚不能从 ATK 主板信息推导。
- **在线调参不成立**：现有 Swift Runtime 配置和 controller 参数在初始化时复制；本 change
  只允许高层给定和模式命令，热调需另行设计事务化 tuning revision。
- **本地 OOT 禁用缓存命中**：开发构建时间增加，但避免旧固件/旧 rootfs 的安全风险。

## Open Questions

- 目标功率板的型号、原理图、PWM 拓扑、电流采样拓扑和编码器接口是什么？
- CPU2 快环使用哪个 PWM/ADC 同步触发源和 GIC route，Linux DTS 需摘除哪些资源？
- 在真实 20 kHz 负载下，各线程 stack high-water mark 是否仍满足当前 heap 余量？
