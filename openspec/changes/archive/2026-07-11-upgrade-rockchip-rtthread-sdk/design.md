## Context

flange 原先携带 Rockchip RT-Thread 3.1.3 vendor 树，并通过临时 BSP staging 构建
RK3568 AArch32 AMP 固件。升级到 4.1.1 后，vendor 树新增大量子模块占位和默认外设，
同时修改了 serial control 与 rpmsg-lite API。直接同步会出现三类问题：复制断链失败、
app 重复维护公共 Kconfig、BSP 默认 GMAC1 在 UART7 之后覆盖同一组 pinmux。

AMP 固件运行在 cpu3，Linux 保留 cpu0/cpu1/cpu2、UART2 和 GIC distributor 所有权。
因此 RT-Thread 的 upstream 通用默认值不能直接视为本产品的最终配置。

## Goals / Non-Goals

**Goals:**

- 使 RT-Thread 4.1.1 vendor 树在 Docker staging 中可重复构建。
- 由 flange 统一维护单核 Linux AMP 公共配置，app 只描述板级差异。
- 保证 Orange Pi CM4 从复位开始就能通过 UART7_M2 输出标准 RT-Thread banner。
- 通过分层测试和上板验证尽早发现 SDK 默认值、API 和 pinmux 回归。

**Non-Goals:**

- 不修改 Linux stock rpmsg 驱动或现有 mailbox 协议。
- 不把 vendor SDK 的所有 Kconfig 默认值改成 flange 产品默认值。
- 不支持 RK3568 RT-Thread SMP；cpu3 固件始终为单核实例。

## Decisions

### 1. 使用平台基线而不是复制完整 app 配置

最终配置按 `BSP .config → flange AMP 基线 → app .config` 合并。平台基线固定关闭
`RT_USING_SMP`，并启用 `RT_USING_RPMSG_LITE`、`RT_USING_LINUX_RPMSG`、
`RT_USING_WITH_LINUX`。app 只覆盖 console、I2C 和板级资源冲突。

替代方案是给每个 app 重复四个选项，或修改每个 Rockchip BSP 默认配置。前者会漂移，
后者会污染 vendor 默认行为，因此不采用。

### 2. app 显式声明负向资源选择

Orange Pi CM4 UART7 app 显式关闭 GMAC1 和 UART2。GMAC1_M1 与 UART7_M2 共用
GPIO4_A2/A3，且 BSP 初始化顺序会让 GMAC1 后写覆盖 UART7；UART2 则由 Linux debug
console 使用。不能依赖当前 BSP 默认值为 `n`，因为 SDK 升级可能改变默认值。

### 3. staging 隔离 vendor 子模块状态

构建器只复制需要写入的 `bsp/rockchip/common` 与目标 BSP，其余目录使用只读 symlink。
复制时忽略断链 symlink，并排除 `common/hal`，随后显式链接到 flange 管理的 HAL SDK。
这样不要求 vendor 子模块的 `.git` 元数据存在，也不会把构建产物写回 SDK。

### 4. 在最窄兼容层适配 4.1.1 API

rpmsg-lite 调用显式传入 `RL_BLOCK`；RK3568 platform 使用 HAL GIC route API；serial core
在 open/close 时继续向 Rockchip UART 驱动发送 4.1.1 的 `RT_DEVICE_CTRL_OPEN/CLOSE`
通知。兼容改动保留在对应 glue 层，不回退整个新 serial/rpmsg 实现。

### 5. 验证最终产物而非只检查源码

测试覆盖配置合并和负向资源项；构建后检查最终 `.config`、ELF/map 与 `amp.img`；上板
要求标准 banner、app cpu 日志、RPMsg link-up、name-service 和双向 echo 全部通过。

## Risks / Trade-offs

- [vendor 树体积大，提交难审阅] → vendor 同步独立提交，兼容和文档提交保持小且可追踪。
- [新 SDK 再次新增冲突默认外设] → app 使用负向配置并增加回归测试，升级时比较最终配置。
- [忽略断链 symlink 掩盖真正依赖] → 对必需的 HAL 显式存在性检查并建立受控 symlink，
  缺少实际编译依赖仍会在 SCons 阶段失败。
- [只看到 MSH 可用而误判启动正常] → 把 banner 早期输出列为独立验收项，不用手工
  `version` 命令替代启动期验证。

## Migration Plan

1. 独立提交 RT-Thread 4.1.1 vendor 快照。
2. 合入 staging、平台基线、API 兼容与 app 负向配置。
3. 强制重建 `orangepi-cm4-amp-rtt-debug`，检查最终配置和固件字符串/调用关系。
4. 单刷具名 `amp` 分区并校验镜像哈希，重启验证 UART7 与 RPMsg。
5. 若运行回归，回退兼容提交和 vendor 提交即可恢复 3.1.3 基线。

## Open Questions

无。
