## Why

Radxa Dragon Q8B 当前镜像能够启动，但两个 DWC3 均被固定为 host，导致 adbd 无 UDC 可绑定。
内核还被锁定到固定 commit，无法持续使用 RSDK 对应 `radxa/kernel` 分支的最新 Q8B 实现；
此前参考 Armbian 增加的 QPS615 AXI 半频属性不属于 RSDK 路线。

## What Changes

- Q8B 内核改为跟踪 `radxa/kernel` 的 `linux-7.0.11` 分支 HEAD，不再声明固定 commit。
- 修正浮动分支与 named repo 的缓存语义，确保每次构建先同步分支，并让源码 HEAD 变化级联失效下游缓存。
- 浮动分支 HEAD 未变化时跳过 mixed reset，保留内核源码时间戳与 make 增量编译缓存。
- 浮动分支 HEAD 更新时优先使用 hard reset，只更新时间戳实际变化的文件；不兼容的文件系统回退到 mixed reset。
- Qualcomm 内核编译使用项目目录下的持久化 ccache，跨构建复用编译结果。
- 保留一份最小板级 patch，将 `usb_0_dwc3`（`a600000.usb`）固定为 peripheral；
  `usb_1_dwc3`（`a800000.usb`）保持 host。
- Q8B 同样应用现有 DWC3 clear-stall 请求保留补丁，配合 adbd 的 ep0 枚举自愈逻辑。
- 修复 TC956x 驱动未清零 IRQ-domain 配置结构体导致两个有线网卡 probe 返回 `-EINVAL`。
- 删除 `toshiba,axi-bus-frequency-half` 板级改动，不再混用 Armbian kernel patch 路线。
- 通过 flange 额外 config 裁掉 Q8B 明确不用的调试信息、独显和 PCIe 网卡模块，缩短构建时间。

## 非目标

- 不复制 Armbian 的 Q8B DTS 或 TC9563/stmmac 驱动补丁。
- 不修改 rootfs 的 adbd 组件或网卡用户态配置。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `qualcommsc8280xp-radxa-dragon-q8b`: Q8B 必须跟踪指定 Radxa kernel 分支，并固定两个 DWC3 的设备/主机角色。

## Impact

- 修改 SC8280XP kernel 仓库配置、额外 config、构建缓存、DWC3/TC956x 补丁路由和 Q8B 板级 DTS patch。
- 浮动分支组件不再命中组件缓存；每次构建都会 fetch 并执行该组件构建，以保证使用远端 HEAD。
- 远端 HEAD 未变化时只恢复 patch 改动，不重写未修改源码的时间戳。
- 远端 HEAD 更新时由 Git 仅重写实际变化文件，并由 ccache 复用未变化编译单元。
- 分支 HEAD 更新可能改变构建结果，这是显式选择的滚动更新策略。
