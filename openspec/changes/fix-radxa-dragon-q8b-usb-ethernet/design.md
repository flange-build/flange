## Context

RSDK 的 Q8B kernel 来源是 `https://github.com/radxa/kernel.git` 的 `linux-7.0.11` 分支。
Q8B 应直接跟随该分支，而不是叠加 Armbian edge 的 DTS 差异。该分支 DTS 已包含 QPS615/TC9563
及两个 MAC 的板级描述，但将 `usb_0_dwc3` 与 `usb_1_dwc3` 固定为 host。

现有 `SourceManager` 已定义“仅 branch、无 commit/tag”代表跟随远端，但构建缓存会在源码同步前命中；
同时 named repo 位于 `.build/sources/repos/<name>`，旧哈希逻辑只检查组件旧路径，未混入其 HEAD。

## Goals / Non-Goals

**Goals:**

- 每次构建 Q8B kernel 都同步并使用 `linux-7.0.11` 远端 HEAD。
- named repo HEAD 变化必须使 kernel 及其下游缓存失效。
- `usb_0_dwc3` 固定为 peripheral 供 ADB 使用，`usb_1_dwc3` 保持 host。
- 网卡实现只采用 Radxa 分支原生代码与 DTS。

**Non-Goals:**

- 不锁定 RSDK 某一发布包的 `src` gitlink。
- 不加入 `toshiba,axi-bus-frequency-half` 或复制 Armbian 驱动补丁。
- 不改变 adbd 脚本、rootfs 包集合或网络管理策略。

## Decisions

### 决策 1：仓库仅声明 repo 与 branch

移除 SC8280XP kernel 的 `commit`。复用 `SourceManager` 现有浮动分支语义，每次 ensure 执行
fetch 并重置到 `origin/linux-7.0.11`。

### 决策 2：浮动分支不使用组件缓存

缓存判断若发现实际源码仓库声明 branch 且未声明 commit/tag，直接判定组件需构建，使源码同步
一定发生。哈希源码时解析 `from_repo`，从 `.build/sources/repos/<name>` 读取真实 HEAD，确保下游
组件能感知分支推进。fetch 后先比较本地与远端 HEAD：相同时只恢复 tracked patch 并清理未跟踪
文件，跳过 mixed reset，避免全树 index stat 失效后 checkout 重写源码时间戳；HEAD 变化时优先
执行 hard reset，让 Git 只重写实际变化文件。若大小写不敏感文件系统导致 hard reset 失败，则回退
到现有 mixed reset 与 checkout 兼容路径。

### 决策 3：板级 patch 固定 USB 角色

仅将 `usb_0_dwc3`（`a600000.usb`）的 `dr_mode` 从 `host` 改为 `peripheral`，供 ADB gadget
绑定；`usb_1_dwc3`（`a800000.usb`）保留上游已有的 `host` 配置，不在 patch 中重复修改。

SC8280XP 平台同时复用 QCS6490 已验证的 DWC3 clear-stall 请求保留补丁，避免主机清除 endpoint stall
时取消 adbd 正在等待的请求。两个平台保留内容一致的 patch，并由测试防止后续漂移。

### 决策 4：通过额外 config 裁剪确定无用的模块

使用 SC8280XP 配置的 `kernel.disable_configs`，由现有 builder 生成 `flange_overrides.config`
并执行 `olddefconfig`，不新增或修改 kernel config patch。首批关闭：

- DWARF 调试信息（选择 `DEBUG_INFO_NONE` 并关闭 `DEBUG_INFO_DWARF5`）；
- AMDGPU 与 Nouveau 独显驱动，保留 Q8B 的 DRM MSM/Adreno；
- Chelsio、Intel、Mellanox、Mucse PCIe 网卡，保留 QPS615 所需的 STMicro/TC956x、QCA808x 及 USB 网卡。

M.2 E-Key Wi-Fi vendor 驱动全部保留，因为插槽允许用户更换无线模组，不能视为绝对无用。

### 决策 5：使用持久化 ccache

复用 Docker 镜像已安装的 ccache，将缓存目录固定为项目内 `.build/cache/ccache`，并只在 Qualcomm
内核主编译命令覆盖 `CC` 与 `HOSTCC`。不改变其他平台和工具链，也不引入新的缓存服务。

## Risks / Trade-offs

- **[上游分支回归]** → 浮动分支天然不可复现；出现问题时从构建日志记录 HEAD，再临时恢复 commit pin。
- **[构建耗时增加]** → 浮动 kernel 每次都重新进入构建；这是确保 fetch 不被缓存绕过的直接代价。
- **[首次启用 ccache 仍会重编]** → Kbuild 检测到编译器命令变化会重建一次；缓存预热后复用结果。
- **[大小写不敏感文件系统]** → hard reset 失败时自动回退到 mixed reset 兼容路径。
- **[网口仍未枚举]** → 通过串口收集 `lspci -nn` 与 PCIe/TC956x dmesg，按 RSDK 同版本输出定位，不再引入 Armbian DTS 属性。
- **[扩展卡驱动被裁剪]** → 本次只保证 Q8B 板载硬件；如需对应 PCIe 独显或网卡，在产品配置中重新启用具体 symbol。

## Migration Plan

1. 同步 `linux-7.0.11` HEAD，应用固定 USB 角色 patch 并构建 kernel/DTB。
2. 刷写后验证 `a600000.usb` UDC/ADB、`a800000.usb` host 及两个 netdev。
3. 如上游 HEAD 回归，记录可用提交并另行决定是否恢复固定版本策略。

## Open Questions

无。
