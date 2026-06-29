## Context

flange 当前能完整构建 Linux 主系统（kernel / bootloader / rootfs / boot / recovery / image），但 Rockchip AMP 协处理器固件完全未接入。commit `a84e5c52` 把 Rockchip AMP SDK 落盘到 `components/amp/rockchip/`（hal 裸机 + rt-thread RTOS 两套），`builder/` 全仓 0 处引用。

**目标硬件**：首板 tspi-rk3566。RK3566/RK3568 同 die、同 4×A55、无独立 MCU——所谓 AMP = 把一个 Cortex-A55 切到 **AArch32（32 位）** 当从核，跑裸机 HAL 或 RT-Thread。`amp.img` 是 `mkimage` 用 `.its` 打的 **FIT 多核镜像**（每核带 `load` 地址 + `cpu` mpidr + payload）。

**已实地验证的运行时基座（无需改动）**：
- 内核 `MAILBOX` / `ROCKCHIP_MBOX` / `RPMSG_ROCKCHIP_MBOX` / `RPMSG_VIRTIO` / `ROCKCHIP_AMP` 已 `=y`；
- U-Boot AMP loader 源码已在树（`drivers/cpu/rockchip_amp.c`，按 GPT 分区名 `part_get_info_by_name("amp")` 加载），只是 `CONFIG_AMP` 默认关；
- 内核树自带 `rk3568-amp.dtsi`（reserved-memory / rockchip-amp / rpmsg / `&mailbox` 全套参考），但目标板主 DTS 未 include；
- AMP 保留内存窗口（约 120–131 MB）与 RK3566 现有布局（ramoops ≤2 MB、OP-TEE @132 MB）不冲突。

**约束**：所有编译在 Docker 容器内完成（宿主零编译依赖）；改源码树走 patch（构建会 `git reset` 复位）；目标板 extlinux 启动、默认不应用 overlay；遵循「框架与平台数据分离」与「简单优先」。

## Goals / Non-Goals

**Goals:**
- 用一条 `flange build` 产出含 `amp.img` 的固件，`flange flash` 刷入设备。
- 端到端打通：U-Boot 加载从核 → Linux 与从核经 rpmsg 通信 → 用户态 app 经 `/dev/rpmsg*` 直接收发。
- 在 app 体系中支持 `flange create app --type amp` 创建协处理器应用工程。
- amp 全程可由配置开关 `amp.enabled` 控制，默认关，不影响既有板。

**Non-Goals:**
- per-core 混装 hal/rt-thread（本轮整张 amp.img 单一来源二选一）。
- 独立 MCU 核（`*-mcu`，Cortex-M0 / RISC-V）的 OSA 分区刷写链路。
- 安全启动 / FIT 签名链（默认未签名，仅验证 U-Boot 不强制校验）。
- 多板普及与其他平台（仅 tspi-rk3566 复用 rk3568）。
- 重构既有 exec/service/lib/test 四类 app 的 deb 打包链路（amp app 在 `type` 维度旁路分叉，不动既有行为）。

## Decisions

### 决策 1：amp = 一等构建组件 + amp app = app 体系新 type（分层）

amp.img 既要进构建图被增量管理、又要进分区/刷写，与 `recovery`/`app` 同构；而用户的协处理器应用逻辑需要脚手架。二者是**互补两层**，不是二选一：

- **amp 组件**（`builder/platforms/rockchip/amp.py` + `DEPENDENCY_GRAPH` 节点）= 把选中的固件源打成 amp.img 并接入分区/刷写；
- **amp app**（`flange create app --type amp`）= 承载用户应用逻辑的工程，由 amp 组件编译。

**备选与否决**：纯 app-type 方案（把 amp.img 塞进现有 app→deb 链路）——否决，因为 app 的核心假设（产物是装进 rootfs 的 deb、用 `*-linux-gnu-` 工具链、走 `_CONVENTION_MAP` 映射到 rootfs 路径）对 amp 全部不成立；amp app 必须在 `type` 维度旁路分叉（`build_one` 顶部 `type=="amp"` early-return），不打 deb、不进 rootfs。

### 决策 2：产品形态 = Linux + 1 个 A55 从核（amp_linux.its）

用 `amp_linux.its`：U-Boot 先把 1 个 A55（cpu3，AArch32）拉成裸机/RTOS 从核，再引导 64 位 Linux 到 cpu0。最贴合「Linux 主系统 + 实时协处理器」诉求。4 核分工 = cpu0/1/2 给 Linux（启用 amp 后 Linux 跑 **3 核**）、cpu3 专给 AMP（DTS 用 `/delete-node/ &cpu3;` 把第 4 核从 Linux 摘掉，见决策 8）。

**实现要点**：hal 的 stock `mkimage.sh` 默认指向 `amp.its`（即下方被否决的 4 核变体），构建器须覆盖其 `-f` 为 `amp_linux.its`，使 hal 路径不会误产出 4 核全裸机镜像；rt-thread 的 `mkimage.sh` 已默认 `amp_linux.its`。首板 tspi-rk3566 用 mode=hal，正落在此覆盖路径上。

**备选与否决**：`amp.its`（4 核全裸机、无 Linux，整片当 MCU）——否决，与诉求不符且会让出全部 A55。

### 决策 3：hal / rt-thread = 单一枚举 `amp.mode`（hal | rt-thread）

整张 amp.img 单一固件来源，`mode` 一个字段天然互斥（胜过两个 bool），符合「简单优先」。

**备选与否决**：per-core 固件来源列表（匹配 SDK 实证的同 amp.img 跨核混装能力）——否决于本轮（列入非目标），单核混装无意义，配置与构建复杂度不划算；保留为后续演进，单核是其退化情形。

### 决策 4（关键纠错）：amp 分区 = 非 raw 具名 GPT 分区

U-Boot AMP loader 按 GPT 分区**名** `part_get_info_by_name("amp")` 定位固件；而 `image.py` 对 `type=="raw"` 的分区**跳过建 GPT 条目**（只 dd 不入表）。因此 amp **必须**是非 raw 具名分区（用 `ext4` 占位）：`parted` 写出名为 `amp` 的 GPT 条目但**全程不 mkfs**（image.py 无任何 mkfs，boot/rootfs 同样声明 ext4 却靠 dd 预制镜像填内容），dd 进偏移的裸 FIT 块原样保留、`fdt_check_header` 通过。

**备选与否决**：`type: raw`——否决，会让 GPT 无 amp 条目、U-Boot 永远 `-ENODEV`、从核不被拉起。这是探索阶段两条调研线初稿的错误，已实地读源码纠正。

### 决策 5：内存布局单一事实源，构建期注入三方

`CPUn_MEM_BASE/SIZE`、`SHMEM_BASE/SIZE`、`LINUX_RPMSG_BASE/SIZE`、从核 `load` 地址在 SoC 配置中定义一次，权威值对齐 `amp_linux.its` 与 `rk3568-amp.dtsi`（从核 `load=0x02800000`、`SHMEM_BASE=0x07800000`、`LINUX_RPMSG_BASE=0x07c00000`）。三方注入方式：

- **build.sh / .its 两腿**：由 `RockchipAmpBuilder` **重写** `build.sh` 中的地址赋值行（或绕过 build.sh 直接以权威地址调 `make`/`scons`），并据此重写 `.its` 的 load 地址。**不能用预设环境变量**——build.sh 内部对 `SHMEM_BASE`/`LINUX_RPMSG_BASE` 无条件 `export`、对 `CPUn_MEM_BASE` 顶层硬编，会覆盖预设 env（env 注入是 no-op）。
- **DTS 第三腿**：DTS 走静态 board kernel patch、无法在构建期消费 config 常量，故由一个构建期/校验期**交叉比对**保障（见决策 8 与 Risks）：patch 内地址与 SoC 常量不一致即失败。

**理由**：SDK 自带示例值本身不自洽（hal `build.sh` 活跃块 CPU3=`0x05800000` vs `amp_linux.its` amp3 `load=0x02800000`，正确值在被注释的 Linux+HAL 块里）；三方任一不一致 → 从核加载到错地址或共享内存错位 → 跑飞/通信失败。绝不沿用 SDK 的 TODO 示例值。

### 决策 6：裸机工具链 = Docker 镜像内装官方 gcc-arm-none-eabi-10-2020-q4

在 `docker/Dockerfile` 装 newlib 版 `arm-none-eabi-` 工具链并钉 **gcc-10**。

**备选与权衡**：
- vendoring 到 `components/amp/rockchip/prebuilts/...`（Makefile/rtconfig 会自动探测）——否决：往 git 塞数百 MB 二进制，污染仓库；
- `apt install gcc-arm-none-eabi`——否决：发行版版本不可控（未必 gcc-10）。
- **采用**：Dockerfile 内解压官方 gcc-10-2020-q4 tarball，并对 rt-thread 用 `RTT_EXEC_PATH` 环境变量覆盖其写死的 prebuilts 路径（`rtconfig.py` 已支持 `os.getenv`）。既钉 gcc-10（与 flange 既有 u-boot/kernel 约定一致、规避 gcc-13 隐蔽 miscompile 教训）、又不污染 git 仓。

### 决策 7：U-Boot CONFIG_AMP 经 bootloader defconfig patch

往 `rk3568_defconfig` 追加 `CONFIG_AMP=y` + `CONFIG_ROCKCHIP_AMP=y` 的 patch，放 `components/platform/rockchip/patches/bootloader/`。两者**成对**启用（仅开 `CONFIG_AMP` 会因 `arm64_switch_amp_pe`/`amp_cpus_on` 无定义而链接失败）。

**备选与否决**：移植 amlogic 的 list-defconfig + fragment 机制到 rockchip——否决：需改 `bootloader.py` 构建代码，而 patch 路线零代码改动、与现有 rockchip bootloader patch（0002/0004/0006）约定一致。依赖 `ROCKCHIP_SMCCC`/`RKIMG_BOOTLOADER` 在 rk3568 已 `=y`，成对开启可编译且空 amp 分区时早退不破坏正常启动（已静态验证 + 同树 8 个 defconfig 旁证）。

### 决策 8：AMP 专用 DTS = 独立 dts 文件，由 amp product 选用

AMP 需要的 DTS 改动有三类：① `#include "rk3568-amp.dtsi"`（reserved-memory / rockchip-amp / rpmsg / 使能 `&mailbox`）；② `/delete-node/ &cpu3;`（把第 4 核从 Linux 摘掉，参照上游 `rk3568-evb1-ddr4-v10-linux-amp.dts:27`，启用后 Linux 跑 3 核）；③ UART：AMP 从核 console 用 **UART4**（HAL 固件默认 + `rk3568-amp.dtsi` 既有，零固件改动；tspi-rk3566 上 uart4 默认空闲，Linux 不占用，故无需额外禁用；Linux 调试 console 仍是 UART2/ttyFIQ0、互不冲突）。

这些改动 SHALL 放进一个**独立的 dts 文件**（如 `tspi-rk3566-amp.dts` = `#include` tspi 基础 dts + 上述三类改动），经一个 board kernel patch **新增**该文件到内核树，由 amp product 的 `kernel.dts` 选用。

**为什么是独立文件而非直接改主 dts 的 patch**：flange 的 kernel patch 按 **board** 生效、对该板**所有 product**应用。若把删 cpu3 / amp 节点写成改主 dts 的 patch，会污染非 amp 的 `default` product（让它也变 3 核、也挂 amp 节点）。新增一个独立 dts 文件对 default product 无害（它不 `kernel.dts` 选它），只有 amp product 选用——干净隔离。

**备选与否决**：运行时 overlay——否决：目标板 extlinux 默认不应用 overlay，dts 文件 + product 选用保证启动即生效。

**一致性保障**：amp dts 文件里的 reserved-memory / amp-cpus entry 地址无法构建期消费 config 常量，故新增构建期/校验期交叉比对——与 SoC 内存布局常量逐项比对，不一致即失败，把 DTS 这条手工腿纳入决策 5 的单一事实源。

### 决策 9：RPMSG_CHAR/CTRL 经 kernel.defconfig raw inline 注入

在 SoC 的 `kernel.defconfig` list 追加 `CONFIG_RPMSG_CHAR=y` + `CONFIG_RPMSG_CTRL=y`（走 `kernel_base.py` 的 raw inline 机制，与现有 `CONFIG_DRM_GUD=y` 同款）。没有任何已开选项会 select 这两项，必须显式开，否则用户态无 `/dev/rpmsg*`。

### 决策 10：amp 源码增量哈希

`cache.compute_hash` 为 amp 混入 `components/amp/rockchip/<mode>` 工程目录内容哈希（仿 `_mix_app_sources`）。amp 源在仓库内、不走 `.build/sources`，现有 `_mix_source_tree` 抓不到——不补则改源假命中、刷入旧固件难排查。

### 决策 11：amp app 经「应用槽位」喂入 amp.img（分层落地）

amp 组件（决策 1）构建的工程根是 SDK 的 per-SoC 工程，其「应用槽位」= hal 的 `project/<soc>/src` 或 rt-thread 的 `applications/`。配置键 `amp.app`（可选）指定一个 amp app：amp 组件构建前把该 amp app 源码 **stage 进应用槽位**，再跑 build.sh/scons + mkimage，把用户逻辑打进 amp.img。`flange create app --type amp <name>` 生成的工程结构即对应该槽位（用户 `main.c`/应用源 + 引用 SDK hal/rt-thread 作 base）。

- `amp.app` 这个独立收集键**不进** `rootfs.custom_packages`（不被 `AppBuilder.build_all` 的 `gather_custom_packages` 迭代成 deb），由 amp 组件单独消费。
- 未指定 `amp.app` 时回退 SDK 自带示例固件（MVP，足以端到端跑通 rpmsg）。
- `flange build app <name>`（单独）可编出固件快速迭代；`flange build`（整体）经 amp 组件把它纳入 amp.img。

**理由**：这把探索阶段「amp app 与 amp 组件源耦合」的开放问题收敛为确定的数据流，让「在 app 体系支持 amp app」端到端闭合，而非停留在能单独编、却进不了 amp.img。

**备选与否决**：让 amp app 自己独立产出整张 amp.img（不复用 amp 组件）——否决：与分层模型重复、且绕开 amp 组件的分区/刷写/增量接线。

### 决策 12：AMP 配置承载为 tspi-rk3566 的 `amp` product（非新板）

AMP 是同一块 tspi-rk3566 的不同人格（3 核 + uart4 让给 AMP + amp 分区），用 product 维度表达：`tspi-rk3566` 的 `config.py` 声明 `"products": ["default", "amp"]`，amp product 经条件键（`+key:amp` / `key:amp` 后缀，参照 `orangepi-5-plus` 的 `wks55fhd001wct-bringup` product）开 `amp.enabled/mode`、覆盖 `kernel.dts` 为专用 amp dts、追加 `RPMSG_CHAR/CTRL`。lunch target = `tspi-rk3566-amp`。

**备选与否决**：独立新板 `tspi-rk3566-amp`——否决：要复制整套 tspi 板配置、两边维护；product 复用板基线、符合 flange 既有先例。`default` product 不受影响（不选 amp dts、amp.enabled 缺省关）。

- **[FIT 签名被强制校验]** `amp_linux.its` 声明了 `signature(sha256,rsa2048,key-name-hint="dev")`，但 mkimage 默认不传 `-k`、产出未签名 FIT。若目标 U-Boot 强制 FIT 校验则拒绝加载 → 从核起不来。**Mitigation**：实现期先核 u-boot `.config` 的 `CONFIG_FIT_SIGNATURE`；rk3568 非安全启动通常不强制；若强制再配 dev key 签名（列为开放问题）。
- **[cpu3 隔离已定，代价 = Linux 3 核]** 用 `/delete-node/ &cpu3;`（上游 evb 确定做法）把第 4 核摘给 AMP，启用 amp 后 Linux 跑 3 核。**Trade-off**：损失 1 个 A55 算力换实时协处理器，仅 amp product 生效、`default` product 仍 4 核。**Mitigation**：上板用 `nproc`/`/proc/cpuinfo` 确认 Linux 见 3 核、cpu3 跑 AMP 固件。
- **[uart4 占用]** AMP 用 UART4，需确保 Linux 不占用。**Mitigation**：tspi-rk3566 默认 uart4 空闲（dts 无 uart4 引用），无需额外禁用；上板确认 uart4 引脚物理引出可用（否则改用其他空闲 uart，需同步改 HAL 固件 console + dtsi）。
- **[内存地址冲突/错位]** **Mitigation**：已复核 RK3566 现有布局不与 AMP 窗口冲突；用决策 5 的单一事实源保证三方一致；上板用 `/proc/iomem` 与 rpmsg 自检验证。
- **[插入 amp 分区需重排 offset + 首次整盘重刷]** rk3566 现有分区已排满（rootfs 取 remaining）。**Mitigation**：实现期规划 amp 分区 offset/size（按实际 `hal*.bin`/`rttN.bin` 体积，2–16 MiB 量级），文档明确首次升级需整盘重刷。
- **[amp 分区容量不足]** 官方各板范例尺寸不一（0x1000–0x8000 扇区）。**Mitigation**：按目标 mode 实际编出的固件体积定，留余量。
- **[Docker 镜像增大]** 新增 gcc-arm-none-eabi-10 工具链。**Mitigation**：仅装一份官方 tarball，不进 git；amp 关闭的板不受运行影响。

## Migration Plan

amp 默认 `enabled: False`，对既有板**零影响**；仅 tspi-rk3566 opt-in。落地按可独立验证的里程碑推进（单提案内）：

1. **构建侧**：amp 组件 + Docker 工具链 + 增量哈希 → `flange build amp` 产出合法 FIT `amp.img`（`mkimage -l` 校验）。
2. **落盘侧**：非 raw amp 分区 + image/flash 接线 + `validate_amp` → `flange build` 产出含 amp 分区的 `raw.img`、`flange flash --list` 含 amp。
3. **启动侧**：U-Boot `CONFIG_AMP` → 上板确认 U-Boot 加载 amp FIT 并拉起 cpu3、Linux 正常起。
4. **通信侧**：board DTS AMP 节点 + 内核 `RPMSG_CHAR/CTRL` → 上板确认 `/dev/rpmsg*` 出现、rpmsg 收发通。
5. **app 侧**：`flange create app --type amp` 脚手架 + 独立构建路径 + amp 组件按 `amp.app` 把用户工程 stage 进应用槽位纳入 amp.img（决策 11）。

**Rollback**：任一里程碑出问题，置 `amp.enabled = False` 即整体回退到无 amp 的既有行为（U-Boot patch 仅在该板 defconfig 生效，空 amp 分区时早退无害）。

## Open Questions

- ~~**FIT 签名最终策略**~~：**已解决**——实测 tspi/rp-pro u-boot `.config` 均 `# CONFIG_FIT_SIGNATURE is not set`，不强制 FIT 校验，未签名 amp.img 可直接加载，无需 dev key。
- **amp 分区精确 offset/size**：取决于实际固件体积与 rk3566 分区重排方案。
- **mode=rt-thread 的工具链**：A 核 AArch32 与 hal 共用 `arm-none-eabi-`；rt-thread 的 RISC-V `*-mcu`（`riscv-none-embed-`）本轮非目标，是否后续补。
- **应用槽位 stage 的精确实现**：amp app 源码如何 stage 进 SDK 工程 `src/`/`applications/`（覆盖还是叠加、构建系统收录约定）——架构已定（决策 11），具体 stage 机制实现期细化。
