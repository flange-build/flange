# Rockchip AMP SDK 升级与排障记录

本文记录 2026-07-10 至 2026-07-11 对 Rockchip HAL SDK 与 RT-Thread SDK 的升级过程。
RT-Thread 从 3.1.3 升级到 4.1.1，目标板为 Orange Pi CM4，cpu3 运行 AArch32
RT-Thread AMP，console 使用 UART7_M2，Linux 运行在 cpu0/cpu1/cpu2。

本文不是 vendor changelog，而是 flange 本地集成的升级方法、实际故障与验证依据。

## 最终结果

- Rockchip HAL 与 RT-Thread SDK 已同步到新版源码布局。
- `components/amp/rockchip/hal/middleware` 纳入版本控制，使用 SDK 自带 rpmsg-lite。
- RT-Thread 4.1.1 可在 Docker staging 中构建，不受断链子模块占位影响。
- RT-Thread AMP 由 flange 平台基线统一保持单核并启用 Linux RPMsg 协同。
- Orange Pi CM4 从复位开始通过 UART7_M2 输出 RT-Thread banner、版本与 app 日志。
- MSH、mailbox、RPMsg name-service 与 Linux↔AMP 双向 echo 均已上板验证。

## 升级原则

### 先提交旧基线，再替换 vendor 树

vendor SDK 更新前必须保证工作区干净，并记录旧版本中所有 flange 本地修改所在的
commit。替换后先查看这些 commit 涉及的路径，而不是只看新旧整树 diff：

```bash
git show --name-status <local-change-commit>
git diff <before-sdk-commit> -- <affected-path>
git log --oneline -- <affected-path>
```

本次依靠已有 Orange Pi CM4 AMP commit 找回了 UART7 iomux、UART7 IRQ、RPMsg platform
和 ISR table 配置。若升级前没有独立 commit，这些改动会淹没在一万多个 vendor 文件差异中。

### vendor 同步与产品修复分批提交

建议提交顺序：

1. vendor SDK 快照；
2. flange 构建/staging 与 API 兼容；
3. app/board 产品配置和测试；
4. wiki 与 OpenSpec。

后续升级可直接把新 vendor 快照与第 2、3 类 commit 对比，快速识别被覆盖的产品改动。

## 问题与解决方案

### 1. HAL middleware 被 `.gitignore` 隐藏

**现象**

新版 HAL 已包含 `middleware/rpmsg-lite`、OpenAMP、sdhci 等源码，但外层仓库看不到这些
新增文件，RK3568 看似仍缺 rpmsg-lite platform。

**根因**

HAL SDK 自带 `.gitignore` 使用 `/middleware` 忽略整个目录。对 vendor 自己的多仓库工作流
可能合理，但 flange 以 vendored source 交付，忽略后构建所需源码不会进入主仓库。

**修复**

删除 `/middleware` ignore 规则，完整跟踪 middleware。原先 flange 临时维护的
`hal/rpmsg-lite-port` 被 SDK 自带实现取代。

**经验**

同步 vendor 树后必须同时检查 tracked 与 untracked 文件。只执行 `git diff` 看不到被
`.gitignore` 吞掉的关键目录，应补充：

```bash
git status --short --untracked-files=all
git check-ignore -v <suspect-path>
```

### 2. RT-Thread staging 在断链 symlink 上失败

**现象**

`flange build amp` 在 `shutil.copytree` 阶段失败，错误包含：

- `drivers/rockit`
- `drivers/rkadk`
- `drivers/common_algorithm`
- `drivers/rga/librga`
- `common/hal/*/.git`

**根因**

新版 RT-Thread vendor 树保留了多个子模块或嵌套仓库占位，但主仓库没有其目标内容或
`.git` 元数据。原 staging 会递归复制整个目录并跟随 symlink，遇到断链即失败。

**修复**

- 顶层 SDK 与非目标 BSP 使用只读 symlink。
- 只复制需要写入的 `bsp/rockchip/common` 与 `rk3568-32`。
- `copytree` 使用 `ignore_dangling_symlinks=True`。
- 排除 vendor `common/hal`，再显式链接到 flange 的
  `components/amp/rockchip/hal`。
- 编译对象、SCons 状态和最终 ELF 继续全部落在临时 staging。

**经验**

不要把 vendor 的仓库组织方式当成构建输入。构建器应显式声明实际需要的源码边界，
对必须依赖的目录做存在性检查，对非必需子模块占位保持容忍。

### 3. 本地 UART7、ISR_COUNT 与 GIC route 被覆盖

**现象**

SDK 替换后，Orange Pi CM4 的 UART7 console 和 RPMsg mailbox 路由相关代码消失或不能编译。

**根因**

这些能力原本是 flange 在 RK3568 BSP 上的本地适配，整树同步会用 vendor 版本覆盖。新版
RT-Thread 还移除了旧的 `rt_hw_interrupt_set_route` 接口。

**修复**

- 恢复 UART7 Kconfig、board descriptor、UART7_M2 iomux 和 `UART7_IRQn` GIC route。
- 保持 RK3568 rpmsg `ISR_COUNT=0x1e0`，使 INTID 222 可作为 ISR table index。
- RPMsg platform 改用 `HAL_GIC_SetIRouter`，并包含 `hal_gic.h`。
- `CPU_GET_AFFINITY(3, 0)` 继续表示 GICv3 路由目标 cpu3 的 MPIDR affinity，
  它不是 RT-Thread scheduler 的 CPU mask。

**经验**

恢复本地功能时要按新 SDK API 重新表达语义，不能机械贴回旧代码。尤其要同时检查
Kconfig、board、driver、HAL 和最终 `.config`，只恢复某一层通常只能通过编译，不能运行。

### 4. RPMsg-Lite API 签名变化

**现象**

旧 app 调用 `rpmsg_lite_wait_for_link_up(inst)`，在新版 rpmsg-lite 下不能编译。

**根因**

新 API 增加 timeout 参数。

**修复**

两份 RT-Thread AMP app 均改为：

```c
rpmsg_lite_wait_for_link_up(inst, RL_BLOCK);
```

这保持原有永久等待 Linux master link-up 的行为。

### 5. RT-Thread 4.1.1 默认启用 SMP

**现象**

固件可构建，但 cpu3 上的 RT-Thread 启动异常，UART console 行为不稳定。关闭 SMP 后 MSH
恢复可操作。

**根因**

新版 RK3568 BSP 默认 `.config` 启用 `RT_USING_SMP`。在 flange AMP 模型中，cpu0/cpu1/cpu2
属于 Linux，RT-Thread 只能使用 cpu3。SMP 初始化会尝试管理或拉起不属于它的 CPU，破坏
既定的 PSCI/GIC 所有权边界。

**修复**

新增 flange 管理的 `components/platform/rockchip/amp/rt-thread.config`：

```text
# CONFIG_RT_USING_SMP is not set
CONFIG_RT_USING_RPMSG_LITE=y
CONFIG_RT_USING_LINUX_RPMSG=y
CONFIG_RT_USING_WITH_LINUX=y
```

配置顺序固定为：

```text
BSP .config → flange AMP 基线 → app .config
```

基线目录纳入 amp 内容哈希，每次都执行 `scons --useconfig=.config` 重生成 `rtconfig.h`。

**经验**

产品公共约束不能依赖 vendor BSP 默认值，也不应复制到每个 app。平台基线负责运行模型，
app 只维护 console、I2C 和板级资源选择。

### 6. serial control API 变化

**现象**

新版 Rockchip UART 驱动处理 `RT_DEVICE_CTRL_OPEN/CLOSE`，旧 serial core 使用
`RT_DEVICE_CTRL_HW_OPEN/HW_CLOSE`，而同步后的 serial core 不再发送等价通知。

**风险**

UART device refcount 与 MSH 可以正常，但底层 clock gate 生命周期不再与 open/close 对称。

**修复**

在 4.1.1 serial core 的 open/close 路径恢复底层通知，并使用新版常量
`RT_DEVICE_CTRL_OPEN/CLOSE`。这是一项驱动生命周期兼容修复。

**注意**

它不是本次启动 banner 丢失的最终根因。排障时保留该修复，但继续追查了 pinmux 状态。

### 7. MSH 正常但启动 banner 和 app 日志丢失

**现象**

- UART7 MSH 可交互。
- 手工执行 `version` 能打印 RT-Thread 4.1.1 banner。
- 冷启动看不到标准 banner，也看不到 `cpu3 up` 和 RPMsg 的 `remote init`。
- 只看到 Linux RPMsg online 后的 `link up` 与 endpoint announce。

**排除过程**

1. 最终 `.config` 确认 console 为 UART7、SMP 已关闭。
2. ELF 反汇编确认 `rtthread_startup()` 调用 `rt_hw_board_init()` 后调用
   `rt_show_version()`。
3. ELF strings 确认 banner、app 日志和 RPMsg 日志均已链接进固件。
4. 手工 `version` 成功，证明 formatter、UART baud rate 和 MSH 输出路径可用。
5. 早期 direct write 仍不可见，而 Linux `rockchip-amp` 应用 pinctrl 后日志开始可见，
   将范围收敛到启动期 UART pinmux/clock 所有权。

**最终根因**

新版 RK3568 BSP 默认打开：

```text
CONFIG_RT_USING_GMAC1=y
CONFIG_RT_USING_UART2=y
```

`rt_hw_iomux_config()` 先配置 UART7_M2，随后调用 `gmac1_m1_iomux_config()`。GMAC1_M1
同样使用 GPIO4_A2/A3，后写把 UART7 pinmux 覆盖为 GMAC function 3。Linux 启动后，
`rockchip-amp` 根据 DTS 再次应用 `uart7m2_xfer`，UART7 才恢复，因此晚期日志和 MSH 正常。

**修复**

Orange Pi CM4 UART7 app 显式声明：

```text
# CONFIG_RT_USING_GMAC1 is not set
# CONFIG_RT_USING_UART2 is not set
```

关闭 GMAC1 解决 GPIO4_A2/A3 冲突；关闭 UART2 避免 AMP 初始化 Linux 的 debug console。
最终固件反汇编确认 `rt_hw_iomux_config()` 不再调用 UART2 或 GMAC1 pinmux。

**经验**

- “运行后 console 可用”不代表“启动期 console 正确”。
- 看不到日志时先证明代码是否执行，再区分软件输出路径与物理 pin/clock。
- vendor Kconfig 的新增默认 `y` 与代码改动同样危险；必须比较最终配置。
- pinctrl 冲突要检查调用顺序，两个驱动都“配置正确”仍可能由后写者覆盖。

### 8. RPMsg link-up 与 echo 验证

RT-Thread app 保持以下协议：

- link-id `0x10`
- endpoint `rpmsg-ap3-ch0`
- endpoint address `0x3003`
- Linux→cpu3 mailbox IRQ 为 MBOX0_CH3_A2B / INTID 222
- app 在 RPMsg 初始化前把 222 增量加入 AMP GIC 白名单

上板验证不能只看到 `rpmsg: link up`。完整通过标准为：

1. UART 输出 remote init、link-up 和 endpoint announce；
2. Linux dmesg 出现 `creating channel rpmsg-ap3-ch0`；
3. `/dev/rpmsg_ctrl0` 存在；
4. Linux 创建 endpoint 后，写入消息能读回 Swift/RT-Thread app 的回复。

## 验证清单

### 构建前

- [ ] 旧 vendor 状态与 flange 本地修改均已有 commit。
- [ ] `git status --ignored` 检查关键 middleware/board 路径。
- [ ] 对照旧本地 commit 列出必须恢复的文件和行为。

### 构建后

- [ ] `flange build amp` 完成，DTS 地址交叉校验通过。
- [ ] 最终 `.config` 关闭 SMP、GMAC1、UART2，启用 UART7 和三个 RPMsg 公共选项。
- [ ] `rtconfig.h` 与最终 `.config` 一致。
- [ ] ELF/map 中存在 `rt_show_version`、app cpu 日志与 RPMsg endpoint。
- [ ] `rt_hw_iomux_config` 不在 UART7 后调用冲突 pinmux。
- [ ] SDK 源树没有新增 `.o`、`.sconsign`、ELF 或 SwiftPM 中间产物。

### 上板后

- [ ] UART7 115200 baud 从复位开始输出标准 RT-Thread banner/version。
- [ ] banner 后出现 `rk3568_amp_uart7_rtt_demo: cpu3 up`。
- [ ] MSH 可交互，`version` 输出与启动 banner 版本一致。
- [ ] RPMsg remote init、link-up、announce 顺序完整。
- [ ] Linux dmesg、`/dev/rpmsg_ctrl0` 和双向 echo 均正常。
- [ ] 写入 amp 分区前后校验 `amp.img` 与分区前缀 SHA-256 一致。

## 下次升级 SOP

1. 在独立升级分支上确认工作区干净。
2. 记录 HAL/RT-Thread 旧版本和当前 AMP 上板基线。
3. 先同步 HAL，解除必要 middleware ignore，构建并提交。
4. 再同步 RT-Thread，先提交 vendor 快照或至少保持 vendor 路径独立提交。
5. 用旧产品 commit 的 path list 审计 UART、GIC、ISR_COUNT、RPMsg 和 linker 配置。
6. 比较 BSP 新旧 Kconfig 默认值，重点检查 SMP、console、GMAC、UART 和共享外设。
7. 应用 flange 平台基线与 app 负向资源配置。
8. 执行单元测试、容器构建、最终配置/ELF 检查。
9. 单刷 amp 分区，依次验证早期 UART、MSH、RPMsg channel 和双向 echo。
10. 更新本文与 OpenSpec，再按 vendor、兼容、文档分批提交。
