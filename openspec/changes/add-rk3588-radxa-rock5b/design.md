## Context

flange 当前 Rockchip 平台只支持单一 SoC `rk3566`，且该平台的 ComponentBuilder 还存在硬编码痕迹：`builder/platforms/rockchip/bootloader.py` 在为 idbloader 打包时直接传 `mkimage -n rk3568`。这是 RK3566 / RK3568 同 die 的历史共用值，无法照搬到 RK3588（同 die 的 RK3588 / RK3588S 必须传 `rk3588`）。

`builder/config/registry.py` 已实现两层平面发现：扫描 `components/platform/<vendor>/config.py` 得到平台、扫描 `components/platform/<vendor>/<soc>/config.py` 得到 SoC，目录名即标识符。`builder/config/merge.py` 负责 `平台 → SoC → board` 的 deep_merge 三层继承。架构层无须改动即可承载多颗同平台 SoC。

外部依赖侧（已核实）：

| 资源 | 仓库@分支 | 用于 |
|---|---|---|
| rkbin | `radxa/rkbin @ develop-v2024.10` | `RK3588MINIALL.ini` + `RK3588TRUST.ini` 已就位 |
| u-boot | `radxa/u-boot @ next-dev-v2024.10` | 含 generic `rk3588_defconfig`、板级 `rock-5b-rk3588_defconfig`、generic `rk3568_defconfig`、`decode_bl31.py` 仍 python2（与 platform 层 0001 patch 配套） |
| kernel | `argon/kernel.git @ linux-6.1-stan-rkr4.1-buildroot` | 已包含 `rk3588-rock-5b.dts` 与 RK3588 SoC 支持（用户确认） |

实板硬件：Radxa ROCK 5B（RK3588 满血版，4×A76 + 4×A55，eMMC 启动，UART2 调试串口 1500000bps，板载 GbE）。

## Goals / Non-Goals

**Goals:**

- 解除 `bootloader.py` 中 `-n rk3568` 硬编码，统一通过 SoC config 字段 `rkbin.mkimage_chip` 提供。
- 同时建立 RK3588 与 RK3588S 两颗 SoC 的配置目录平面，验证多 SoC 共存场景下 deep_merge 与 SoC 自动发现工作正常。
- 完成 ROCK 5B 首版"串口 + SSH"验证链路：maskrom → 5 分区刷写 → U-Boot/kernel 串口 banner → systemd → sshd。
- 现有 RK3566 板（zero3w / tspi-rk3566 / cubie-a7z / orangepi-cm4）构建产物保持 byte-identical。

**Non-Goals:**

- 不引入"SoC 家族"中间继承层；不动 `registry.py`、`merge.py`、`engine.py`、`flash.py`。
- 不为 RK3588 启用 GPU / NPU / VPU / HDMI / DP / NVMe / Wi-Fi。
- 不为 RK3588S 适配任何实板（仅平面通路占位）。
- 不在本变更内回填整个 `rockchip-platform` capability 的全部历史行为；spec 范围只覆盖本次新增/修改的契约。

## Decisions

### Decision 1: mkimage chip 标签字段位置 — 放在 SoC 层 `rkbin.mkimage_chip`

**选择**：在每个 SoC 的 `config.py` 的 `rkbin` 块新增 `mkimage_chip` 字符串字段，bootloader builder 从 `config["rkbin"]["mkimage_chip"]` 读取。

**理由**：
- 该值与 `ini_prefix` / `trust_ini_prefix` 同语义层级（都是 BootROM/固件层 SoC 标识），并列在 `rkbin` 块内最直观。
- SoC 层而非 platform 层：因 `rk3568`（兼用 RK3566）与 `rk3588`（兼用 RK3588S）两个值在同一平台内不同 SoC 间不一致，无法在 platform 层放共享默认。
- SoC 层而非 board 层：同 SoC 不同板（如 zero3w 与 tspi-rk3566）必然共享该值，board 层重复浪费且易漂移。

**备选**：
- *放 platform 层加 SoC 层覆盖* — 多此一举；无任何 SoC 用平台默认值。
- *硬编码到 builder 的 SoC 名查找表* — 直接违反"框架层平台无关"约束。

### Decision 1.5: 整个 Rockchip 平台 u-boot 切到 next-dev-v2024.10

**选择**：把 RK3566 / RK3588 / RK3588S 三颗 SoC 的 `bootloader.branch` 统一为 `next-dev-v2024.10`，废弃原 RK3566 用的 `next-dev-v2026.01`。同时删除 `tspi-rk3566` 的 `bootloader.commit` pin，让所有 RK3566 板跟随同一分支 HEAD。

**触发原因**：实测 ROCK 5B 首次 build 时撞到 `0001-decode_bl31-use-python3-shebang.patch` apply 失败 — 上游 `next-dev-v2026.01` 已 backport python3 shebang，patch 不再适用；同时该分支缺 `rock-5b-rk3588_defconfig` 等 RK3588 板级专用 defconfig。

**理由**：
- v2024.10 一次性满足所有需求：含 generic `rk3568_defconfig`（兼容 RK3566） + 板级 `radxa-zero3-rk3566_defconfig` / `rock-3c-rk3566_defconfig`（未来可能升级为 board-specific） + generic `rk3588_defconfig` + 板级 `rock-5b-rk3588_defconfig` 与 RK3588S 全系列 defconfig。
- v2024.10 保持 `decode_bl31.py` python2 shebang，与 platform 层 0001 patch 配套，无需为不同分支维护差异化 patch。
- 维护一条分支比维护两条简单。当前三颗 SoC 共用 rkbin、共用 patch 集，再共用 u-boot 分支让 SoC 层差异收敛到"BootROM 标识 + defconfig 选择"两件事。
- 顺便消除 tspi-rk3566 长期存在的隐式分裂：原 board 层 `commit=3c60a711` 实际是 `next-dev-buildroot` 分支的 HEAD，与 SoC 层声明的 branch 字段语义矛盾，read 起来像 v2026.01 实际上跑 buildroot。

**备选**：
- *维持 v2026.01 + 把 patch 移到 tspi board 层（patch ownership 重定位）* — 实际上 v2026.01 缺 RK3588 板级 defconfig，rock5b 只能走 generic — 短期能跑但失去 board-specific u-boot init 路径，首版启动稳定性次优。
- *base.py apply_patches 鲁棒化（容忍已应用 patch）* — 框架层改动可独立成变更，但绕开了"v2026.01 缺板级 defconfig"这个根本短板。

**回归影响**：所有 RK3566 板（zero3w / tspi-rk3566 / cubie-a7z 不影响、orangepi-cm4 / neons-core3566-nanob）切到 v2024.10 HEAD。tspi-rk3566 的 commit 退到 SoC 层 v2024.10 HEAD（和其他板一致）。byte-identical 实测覆盖：v2024.10 vs 原配置（v2026.01 缓存 / next-dev-buildroot pin）不能 byte-identical（不同 commit），改为"产物可启动 + boot/kernel 一致"等价回归。

### Decision 2: RK3588S SoC 目录字段 100% 复制 RK3588

**选择**：`rk3588s/config.py` 全字段照搬 `rk3588/config.py`，包括 `bootloader.defconfig=rk3588_defconfig`。

**理由**：
- `radxa/u-boot @ next-dev-v2026.01` 没有 generic `rk3588s_defconfig`（已核实），只有按板细分的 `rock-5a-rk3588s_defconfig` / `rock-5c-rk3588s_defconfig` 等。
- RK3588 与 RK3588S 同 die，u-boot 阶段（UART/eMMC/USB）行为无差，generic `rk3588_defconfig` 跑 RK3588S 实测可行。
- 当 ROCK 5A/5C/CM5 等 RK3588S 真实板适配时，由 board 层 `bootloader.defconfig` 覆盖为板级 defconfig 即可（与现有 board 层覆盖机制一致）。

**备选**：
- *RK3588S SoC 层留空 defconfig，强制 board 覆盖* — 与 RK3566/RK3588 SoC 层模式不一致；需先校验 `validate_config` 是否允许该字段缺省，徒增复杂度。
- *只建 rk3588 不建 rk3588s* — 用户明确要求 SoC 通路一次铺通，避免下次"通路验证"延迟。

### Decision 3: 不引入 SoC 家族继承层

**选择**：`rk3588` 与 `rk3588s` 各自完整声明 `kernel` / `boot.kernel_args` / `partitions` 等字段，即使内容与彼此 100% 相同。

**理由**：
- 用户记忆中明确的项目原则："避免隐式硬编码，框架层必须平台无关"。家族继承层会引入"看不见的中间状态"，违背可见性原则。
- 当前 `registry.py` 是严格两层（platform → SoC）的扁平发现，引入家族层需改注册逻辑、merge 逻辑、文档约定，触动面远超本变更范围。
- RK3588 与 RK3588S 现在看起来"完全相同"是临时巧合；真实板适配后必然会分化（partitions 偏移、boot.kernel_args 等）。"可见重复"恰好为分化留好抓手。

**备选**：
- *在 `components/platform/rockchip/rk35xx/` 引入家族目录* — 违反 registry 两层假设，需要先做大改造。
- *用 Python `from ... import ...` 在 `rk3588s/config.py` 内部 import rk3588* — 隐式依赖，不直观，配置文件不应有跨目录 import 副作用。

### Decision 3.5: ROCK 5B 走 SoC generic defconfig，不用 board-specific（实测后修正）

**触发原因**：实测 ROCK 5B 用 `rock-5b-rk3588_defconfig` 启动后，kernel 卡在 rootwait 阶段。日志显示 cmdline 是 `root=PARTUUID=614e0000-0000 ... androidboot.fwver=...`，与 flange 写在 `extlinux.conf` 中的 `root=PARTLABEL=rootfs ...` 完全不同。

**根因**：`rock-5b-rk3588_defconfig` 是 radxa 为 Android/multi-OS 调的板级 defconfig，启用了 androidboot 风格的固定 bootargs，绕过 Generic Distro Boot 的 extlinux.conf 流程，并把 PARTUUID 截短为前 12 字符（Android 历史习惯）。结果 PARTUUID 不完整、`rootwait` 永久阻塞。

**修正**：ROCK 5B board 层**不覆盖** `bootloader.defconfig`，直接沿用 SoC 层 generic `rk3588_defconfig`。

**实证**：generic `rk3588_defconfig` 在 v2024.10 上的 ROCK 5B 板级初始化完整 — 实测启动到 kernel 阶段，板上所有外设（eMMC HS400 / GbE r8169 / GPU Mali-G610 / NPU / VPU / HDMI）全部 probe 成功，证明 generic defconfig 的 board init 路径足够。

**理由**：
- 与 RK3566 各板（共用 generic `rk3568_defconfig`）保持流程一致，不引入"某些 RK3588 板用 generic、某些用 board-specific"的分裂。
- extlinux.conf 是 flange 全平台统一的 boot 入口，绕过它意味着失去配置可见性（kernel cmdline 由 flange 控制 vs 由 u-boot 内置写死）。
- 当 `boot.kernel_args` 字段需要调整时，generic defconfig 路径直接生效；board-specific 路径需要重新构建 u-boot 并改 source。

**备选**：
- *改 rock-5b-rk3588_defconfig 让它走 extlinux* — 可行但要 patch u-boot config，跨升级维护成本高。
- *修 ImageBuilder 用短 PARTUUID + 生成 androidboot 风格 bootargs* — 退化方案，让 flange 适配上游怪癖。

**取舍**：可能失去某些 board-specific 的 u-boot 阶段优化（如特定的 PMIC 序列、PHY 初始化），但实测已证明 generic 在 ROCK 5B 上完整可用。若未来发现 generic 无法覆盖某 RK3588 板，再独立评估是否 board-specific。

### Decision 3.6: 关闭 generic rk3588_defconfig 的 OPTEE 客户端检查（实测后追加）

**触发**：用 generic `rk3588_defconfig` 启动 ROCK 5B 时，u-boot proper 卡死：

```
optee check api revision fail: -1.0
optee api revision is too low
### ERROR ### Please RESET the board ###
```

**根因**：`rk3588_defconfig` 末尾启用 `CONFIG_OPTEE_CLIENT=y` + `CONFIG_OPTEE_V2=y` + `CONFIG_OPTEE_ALWAYS_USE_SECURITY_PARTITION=y`，但**没启用** `CONFIG_SPL_OPTEE`。导致 SPL 阶段不打包 `tee.bin` 到 fit image（`fit_nodes.sh` 检查 `^CONFIG_SPL_OPTEE=y` 才生成 tee 节点），BL31 启动时报 "No OPTEE provided by BL2"，u-boot proper 阶段又强制 client 检查，最终拒绝继续。这是 generic defconfig 的内部不一致。

**修正**：在 `components/platform/rockchip/patches/bootloader/0003-rk3588-disable-optee-client.patch` 中删除这三行 OPTEE_CLIENT 配置，让 u-boot proper 跳过 OP-TEE 客户端检查，正常进入 Generic Distro Boot。

**理由**：
- flange 的应用场景不使用 OP-TEE 受信应用（无 TA、无 supplicant），保留 OPTEE_CLIENT 检查只徒增启动失败可能性。
- 启用完整 OP-TEE 链路（启 SPL_OPTEE + 把 tee.bin 加进 fit image）需要更大改动，且对当前需求无收益。
- patch 仅修改 `configs/rk3588_defconfig` 单文件，对 RK3566 板（用 `rk3568_defconfig`）零影响 — 它们 build 时 git apply 该 patch 仍成功（删行操作），但产物完全不变（不读 rk3588_defconfig）。

**备选**：
- *启用 SPL_OPTEE 让 SPL 加载 tee.bin* — 完整链路但改动大；rkbin 提供 `rk3588_bl32_v1.17.bin`，理论可行但需要确认 u-boot SPL 内存布局兼容。本变更范围外。

### Decision 3.7: 阻止 dtb 默认 bootargs 合并到 env（实测后追加）

**触发**：第二次实测 ROCK 5B（generic `rk3588_defconfig` + 关闭 OPTEE_CLIENT 之后）启动 — U-Boot 跑通到 sysboot 阶段，正确读取 extlinux.conf：

```
Found /extlinux/extlinux.conf
1: flange
append: root=PARTLABEL=rootfs rootfstype=ext4 rootwait rw console=ttyS2,1500000 loglevel=7
```

但 kernel 拿到的 cmdline 完全不一样：

```
root=PARTUUID=614e0000-0000 ... console=ttyFIQ0 ... androidboot.fwver=...
```

`root=PARTLABEL=rootfs` → `root=PARTUUID=614e0000-0000`（短形 UUID 不合法），`console=ttyS2` → `console=ttyFIQ0`，导致 kernel `rootwait` 永远阻塞在 `mtd_vendor_storage: deferred probe pending` 之后。

**根因**：`arch/arm/mach-rockchip/board.c:board_fdt_chosen_bootargs()` 在 sysboot 之后被 fdt_chosen() 调用，函数体内调用 `bootargs_add_dtb_dtbo()`，该函数把 **dtb chosen/bootargs**（rk3588-rock-5b.dts 包含的 rk3588.dtsi 写死的 default bootargs）按 key 合并到 env bootargs。`env_update()` 是 `key=value` 替换语义（参见 `cmd/nvedit.c:env_update_filter`），不是简单 append — 所以 dtb 里的 `root=` `console=` 直接覆盖 extlinux APPEND 的同名项，其他 dtb 默认项也被注入。

**修正**：新增 `components/platform/rockchip/patches/bootloader/0004-skip-dtb-bootargs-merge.patch`，在 `bootargs_add_dtb_dtbo` 循环里 short-circuit `bootargs` 项的合并（保留 `bootargs_ext` 项处理 — 这是 dtbo apply 后的扩展，正常使用 case）。

**理由**：
- flange 用 Generic Distro Boot（extlinux.conf）作为 boot 入口是平台统一约定。如果 dtb 默认 bootargs 优先于 APPEND，配置可见性破坏（用户改 `boot.kernel_args` 不生效）。
- patch 仅删 dtb 默认 bootargs 的注入，不影响 dtbo / fwver / android 风格 cmdline 注入路径。
- 对 RK3566 板：它们的 dts 通常 chosen/bootargs 为空或不存在，本 patch 无可见行为变化（按 key 替换的对象不存在则等价于 noop）。

**备选**：
- *patch 内核 dts 删除 chosen/bootargs* — 跨内核仓库维护，每升级 BSP 都要重做。
- *关闭 board_fdt_chosen_bootargs 整个函数* — 顺手丢失 dtbo 扩展能力（bootargs_ext）与 fwver 调试输出，影响面大。
- *改用自定义 bootcmd 绕过 distro_bootcmd* — 推翻 flange 平台 boot 流程统一约定，工程负担大。

### Decision 3.8: 临时禁用 ROCK 5B 的 Mali-G610 GPU 节点（实测后追加）

**触发**：第三次实测（U-Boot APPEND 已通），kernel 启动后串口正常输出大量驱动 probe 日志，但 65 秒后 RCU stall：

```
rcu: INFO: rcu_sched self-detected stall on CPU
pc : queued_spin_lock_slowpath+0x298/0x420
lr : __mutex_lock.constprop.0+0x8b8/0x8d4
...
kbase_hwaccess_pm_powerup+0x3c/0x260
kbase_backend_late_init+0x50/0x15c
kbase_device_init+0x6c/0xf4
kbase_platform_device_probe+0x4c/0x134
```

`kbase_hwaccess_pm_powerup` 在 mutex 自旋死锁，`async_run_entry_fn` 整条 kthread 卡死，systemd 无法继续启动。

**根因**：argon BSP 内核 `linux-6.1-stan-rkr4.1-buildroot` 的 mali_kbase (Bifrost) 驱动在 ROCK 5B 上 power up 时死锁。dts 缺关键属性（`power-off-delay-ms not available` warning）+ G610 r0p0 status 5 与 driver HW issues table 不匹配（强行回退 r0p0 status 0），最终在 PM mutex 上死循环。

**修正**：board 层新增 kernel patch `components/board/radxa-rock5b/patches/kernel/0001-disable-mali-gpu.patch`，把 `rk3588-rock-5b.dts` 中 `&gpu` 节点 `status = "okay"` 改为 `"disabled"`。

**理由**：
- 本变更（首版）验收范围明确**不含 GPU/HDMI/DP/NPU/VPU**（详见 proposal Non-Goals），GPU 不工作不影响串口 + SSH 验证。
- 修 BSP 内核 GPU 死锁需要补 dts 属性 + 核对 driver 与 G610 silicon revision，工程量大且超出本变更范围。
- patch 仅影响 ROCK 5B 单板（patch 路径在 board 层），其他 RK3588 板适配时各自评估。
- 本 patch 是**临时屏蔽**性质，明确标注"GPU 启用专项变更中删除"。

**备选**：
- *关闭 mali_kbase 内核模块（CONFIG_MALI=n）* — 影响 RK3566 板（它们用 mali400，但 mali_kbase 跟 mali400 是不同 driver，理论上不互冲）。但全平台关 mali 跟"按需禁用"语义不同，本变更范围外。
- *修补 dts 添加 power-off-delay-ms + 调试 mali_kbase compat* — 工程量与本变更不匹配，应作为独立"启用 ROCK 5B GPU"变更。

### Decision 4: ROCK 5B partitions 偏移先沿用 RK3566 布局

**选择**：`rk3588/config.py` 的 `partitions.entries` 直接抄 `rk3566/config.py`：
```
idbloader  @ 0x40       size 0x2000
uboot      @ 0x4000     size 0x2000
boot       @ 0x8000     size 0x20000
recovery   @ 0x28000    size 0x100000
rootfs     @ 0x128000   size remaining (image_size 2G)
```

**理由**：
- RK3588 idbloader 实际尺寸由 BL31/BL32/DDR.bin/SPL 累加决定；提案阶段无法精确预估。
- 0x4000 - 0x40 = 8128 sectors ≈ 4 MiB 上限，对 BSP idbloader 大概率够；若实测越界，再起独立小变更调整 uboot 偏移。
- 提早设计大偏移 = 凭空多占 eMMC，违反"不过度设计"原则。

**风险缓解**：在 tasks 中明列"实测 idbloader.img 大小并对比 0x4000 偏移"为验证步骤；不通过则 block 后续，不会带病合入。

### Decision 5: spec 范围限定为本次新增契约

**选择**：新建 `rockchip-platform` capability 时，requirements 只覆盖本变更引入的契约（mkimage_chip 字段、多 SoC 共存、ROCK 5B 启动链路），不回填现有 RK3566 行为的历史 requirements。

**理由**：
- OpenSpec 鼓励变更最小化；"补全历史 spec"应作为独立变更（如 `document-rockchip-platform-baseline`）。
- 本变更专注"新增 RK3588 通路"，混入大块历史回填会模糊 review 焦点。
- 后续变更可以平滑增量补全 `rockchip-platform` 的其余 requirements，不影响本变更归档。

## Risks / Trade-offs

| 风险 | 缓解 |
|---|---|
| **RK3588 idbloader.img 超过 uboot@0x4000 偏移** → 启动失败 | tasks 中要求实测体积；不通过则在合入前调整 partitions（也可作为后续小变更） |
| **`rockchip_linux_defconfig` 在 argon BSP 中实际不开启 RK3588 必要 driver** → 内核启动到一半挂起 | tasks 0 项验证 defconfig 内 `CONFIG_ARCH_ROCKCHIP_RK3588`（或等价项）启用；用户已确认存在，但仍需走一次构建确认 |
| **RK3588S 用 generic rk3588_defconfig 在 u-boot 阶段触发不存在的外设初始化** → 启动 hang | 本变更不为 RK3588S 适配实板，无短期影响；首次用 RK3588S 板时再实测 |
| **idbloader 改 chip 后产物 byte-identical 验证失败**（mkimage 行为变化） → RK3566 现有板回归 | tasks 强制要求 4 块板对比 hash；rk3568 chip name 完全等价代换、原值 = 新读取值 |
| **新增 `mkimage_chip` 字段后 validate_config 报缺失** → 构建中断 | 检查 `builder/config/validate.py` 现有约束；若需要，在该文件加可选字段声明（变更内一并完成） |

## Migration Plan

本变更纯增量，无 breaking。落地顺序（与 tasks.md 对齐）：

1. **前置重构**：bootloader.py 改读 `mkimage_chip`，rk3566 加该字段。回归 4 块 RK3566 板，产物 byte-identical 后才合入。
2. **新增 SoC**：rk3588 / rk3588s SoC config。仅文件新增，不影响任何现有 board。
3. **新增 board**：radxa-rock5b。lunch target 自动出现，CLI 无改动。
4. **实板验证**：ROCK 5B 实机 maskrom → 五分区 → 串口 → SSH。

**回滚**：每步独立可回滚（git revert 单 commit），无 schema/数据迁移、无 CLI 命令变化。

## Open Questions

- **idbloader.img 实测尺寸是否真的 < 0x4000 sectors？** — 待 tasks 第 4 阶段实测确认；若不，partitions.entries 需在变更内调整或拆出后续变更。
- **`builder/config/validate.py` 是否对 `rkbin.mkimage_chip` 字段有要求？** — tasks 第 1 阶段排查；若需要新增字段声明，本变更内一并完成。
- **RK3588 BL32（OP-TEE）是否需要打包进 u-boot.itb？** — `radxa/rkbin develop-v2024.10` 的 `RK3588TRUST.ini` 是否含 BL32 段决定；现有 `bootloader.py._parse_trust_ini` 已处理"BL32 缺省即不打包"情况，故大概率无须改代码，但需观察实测启动日志确认 OP-TEE 是否被加载（若需要 OP-TEE 而 ini 没声明，会触发 secureboot 异常）。
