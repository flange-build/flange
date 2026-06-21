## 真因最终结论（2026-06，逐次上板 + 反汇编坐实）

> ⚠️ **本文档下方的「根因再诊断」及各 Decision 记录的是探索过程；多条根因假设（mkimage/缺
> boost、错板 DT、OP-TEE、BL31 版本、SGRF firewall、cfdab2f 异源、`0001` ufs-invalidate
> patch、u-boot 分支 v2024.10 vs v2026.01）已逐一上板证伪。最终真因如下。**

**UFS 启动崩溃真因 = 编译器工具链。** Ubuntu 24.04 默认 `gcc-13` 编老 rockchip u-boot
（2017.09 基）产出的整体二进制布局，让开机 malloc 的 UFS GPT 读 buffer 落到 RK3576 UFS DMA
写不进的坏物理地址 → 控制器报 `OCS_SUCCESS` 但数据静默不落、proper 读到堆残渣
（`0xFDxxxxxx`，恒为 `buffer+0x2100000`）→ `part_get_info_efi` Synchronous Abort。反汇编对比：
`ufs_send_scsi_cmd`/`ufshcd_cache_flush_and_invalidate` 在 gcc-10/13 下**逐指令一致**——
gcc-13 没把 UFS 驱动本身编错，是**整体布局效应**（不同内联/寄存器分配）；radxa bsp 用
`gcc-10.2.1` 布局安全、实测能引导 UFS（公开 39cd993 源即可，与 cfdab2f 无关）。

**修法 = 全平台 u-boot/kernel 默认用 gcc-10**：`builder/base.py` 的
`ComponentBuilder.CROSS = /opt/aarch64-gcc10/bin/aarch64-linux-`（kernel.org crosstool
gcc-10.5，见 `docker/Dockerfile`），各 platform builder 不再覆盖 CROSS。

**最终干净配方：** rk3576 u-boot 分支 `next-dev-v2026.01`（与其他 rockchip SoC 统一）；
idbloader `boot_merger`（rkbin DDR/boost + **自编** SPL）；board `defconfig=
rock-4d-spi-rk3576_defconfig`（对板 DT）；OP-TEE 经平台 `0006` patch 进 FIT；BL31 v1.24
（不 override）；自编 spi.img（不用 prebuilt）。下方 Decision 1/3/5 仍有效；Decision 2
「SPL 用 rkbin prebuilt」已改为**自编 SPL**；Decision 4「prebuilt→自编」有效。

---

## Context

RK3576 ROCK 4D 上一变更（已归档 `2026-06-20-add-rk3576-radxa-rock-4d-ufs`）锁定 radxa
官方预编 spi.img，因 flange 自编 6 次上板全崩在读 UFS。本变更让 flange 自编可引导 UFS 的
spi.img，基于一轮 4 路构建链路审计 + 一轮 3 维度对抗式审查（含字节核验）。

硬证据：
- **armbian** `rockchip64_common.inc:232-247`：RK3576 是唯一不走 mkimage 的 RK35xx，专用
  `boot_merger RK3576MINIALL.ini`；`FlashBoost=rk3576_boost` 进 `IDB_PATH` 输出的 idbloader。
  其 board 配置 `BOOTCONFIG="rock-4d-spi-rk3576_defconfig"` + `BOOT_FDT_FILE=rk3576-rock-4d-spi.dtb`。
- **官方 prebuilt 字节**：sector 64（0x8000）= `52 4B 4E 53`=`RKNS`（boot_merger NEWIDB v2），
  无 mkimage 旧魔数 `0x0FF0AA55`；u-boot.itb 在 sector 16384（8 MiB）；其 proper DT 含
  `radxa,rock-4d`、不含 `rk3576-evb`。
- **flange rkbin**（`develop-v2026.01`）已含 `tools/boot_merger`、stock `RK3576MINIALL.ini`
  （`FlashBoot=rk3576_spl_v1.08.bin`、`[OUTPUT] IDB_PATH=rk3576_idblock_v1.10.108.img`、
  `NEWIDB=true`）+ boost/ddr/bl31。flange 当前**已在跑** boot_merger（仅读 `[OUTPUT] PATH=`
  产 miniloader），IDB_PATH 产物已物理存在、被丢弃。
- **radxa u-boot `next-dev-v2026.01`**（已 checkout 核验）`configs/` 同时存在 `rk3576_defconfig`
  （`DEFAULT_DEVICE_TREE="rk3576-evb"`）与 `rock-4d-spi-rk3576_defconfig`
  （`DEFAULT_DEVICE_TREE="rk3576-rock-4d-spi"`）；两者存储驱动几乎相同
  （均 `CONFIG_UFS=y`/`ROCKCHIP_UFS=y`/`SPI_FLASH=y`），核心差异是 DT。

## 根因再诊断（修正上一变更结论）

上一变更归档的根因是「flange 用 `mkimage -T rksd` → idbloader 缺 `rk3576_boost` → SPL 环境
不全 → 读 UFS 崩」。本轮两条字节核验**动摇该结论**：

1. **遗留自编 `idbloader.img` 头部 = `RKNS`**（NEWIDB、boost 已在），不是 mkimage 旧魔数 —
   说明上次自编最后某轮**已经用 boot_merger 风格 idbloader**，若它上过板仍崩，则「缺 boost」
   非真因。
2. **被忽略的独立缺陷**：flange 自编 u-boot proper 用 SoC 层 generic `rk3576_defconfig`
   → `DEFAULT_DEVICE_TREE="rk3576-evb"`。`rk3576-evb` DT 没有 ROCK 4D 的 SPI NOR 控制器
   pinmux（`&sfc0 pinctrl-0=<&fspi0_pins>`、`&spi_nor okay`）与板级节点。即便 SPL 把 itb
   读进 RAM 并跳入 proper，该 proper 也是「错板」固件 → 访问 SPI/存储失败。

**修正后的根因假设**：之前崩溃存在**两个独立缺陷**——(A) idbloader 装配方式（应 boot_merger
而非 mkimage）、(B) proper DT 错板（应 rock-4d-spi 而非 evb）。**(B) 很可能是实际主因**（被
完全忽略），(A) 是「RK3576 正确装配方式」（armbian/官方字节坐实、仍须做）。本变更同时修 A+B，
并在上板时用「干净复现」区分二者贡献（见 Migration）。

## Goals / Non-Goals

**Goals:**

- flange 容器内自编出能引导 UFS 的 spi.img（idbloader + u-boot.itb），取代下载预编。
- 修复 A：RK3576 idbloader 经 boot_merger 装配，含 `rk3576_boost`（NEWIDB）。
- 修复 B：proper u-boot 用对板 defconfig（`rock-4d-spi-rk3576_defconfig`，DT=rk3576-rock-4d-spi）。
- 最小改动：拾取 boot_merger 已产出的 `IDB_PATH`；复用现有 `build_spi_image`（offset 已对）
  与 self-build u-boot.itb 路径。

**Non-Goals:**

- 自编 SPL（Option B：sed `FlashBoot=./spl/u-boot-spl.bin`）——仅作 fallback。
- 字节级复现官方 prebuilt（官方用自编 SPL，本方案用 rkbin SPL）。
- 改其他 RK35xx 的 idbloader mkimage 路径。

## Decisions

### Decision 1：idbloader 装配 mkimage → boot_merger（整段分流，拾取 IDB_PATH）

RK3576 idbloader 改用 `boot_merger` 产出的 `[OUTPUT] IDB_PATH=rk3576_idblock_v*.img`，取代
`mkimage -T rksd`。
- 实现要点（修审查 blocker）：当 `bootloader.idbloader_method == "boot_merger"`，compile()
  必须**用 if/else 整段跳过** `_parse_loader_ini`+`idbloader_spl`+`mkimage`（现 bootloader.py
  解析 loader_ini 至 mkimage 的整段），改为复用 compile() 末尾**已有的那次** `boot_merger`
  run（不额外再跑一次），run 后用新增 `_extract_idb_path` 解析 ini 的 `[OUTPUT] IDB_PATH=`、
  `shutil.copy2(firmware_dir/idb_path, src_dir/idbloader.img)`，且**不得**在分支内提前 return
  （末尾 `_firmware_dir`/`_ini_prefix` 赋值必须执行，否则 collect() 抛 AttributeError）。
- `rkbin.mkimage_chip` 字段**保留不动**：boot_merger 分支提前分流后不触达 mkimage 校验，留着
  零副作用（其他 RK35xx 仍需）。
- 备选：自行实现 NEWIDB 打包——否决，boot_merger 闭源且 rkbin 已提供。

### Decision 2：idbloader 的 SPL 用 rkbin prebuilt（Option A），不自编

用 stock `RK3576MINIALL.ini` 的 `FlashBoot=rk3576_spl_v1.08.bin`，不改 ini、不自编 SPL。
- 为何：用户选定；最简（boot_merger 已跑、零 ini 改动、无需 `CONFIG_SPL`）；审查实测 rkbin
  SPL v1.08 内含完整 UFS 栈（`ufs_start`/`ufshcd_*`/`ufs_rockchip_rk3576_init`）、SPI NOR 启动、
  FIT 加载、GPT 修复逻辑——「rkbin SPL 起不了 UFS」最坏假设已被证伪。
- 残留不确定项：rkbin SPL（`fwver:v1.08`）与自编 proper（next-dev-v2026.01）非同源。SPL→proper
  交接靠 FIT 自描述 load/entry 地址，**大概率成立**，但 SPL↔proper ABI 漂移仍是已知风险。
- 备选 Option B：`sed FlashBoot=./spl/u-boot-spl.bin` + 开 `CONFIG_SPL` 自编 SPL——与官方字节
  同配方、已证能起 UFS。**记为 fallback**：上板若 SPL→proper 交接 hang 即切此路。

### Decision 3：idbloader 装配方式声明在 SoC 层

`rk3576/config.py` 声明 `bootloader.idbloader_method="boot_merger"`，非 board 层。
- 为何：「RK3576 idbloader 须 boot_merger」是 SoC 特性、与存储介质无关（armbian 按 `BOOT_SOC`
  判定）；未来 RK3576 其他板同样适用。目前仅 ROCK 4D 一板，放 SoC 层零回归。

### Decision 4：board bootloader 来源 prebuilt → 自编

ROCK 4D 去 `prebuilt_spi_image`，加 `flash_spi_loader=True`，`flash.py` 经 `build_spi_image`
组装（idbloader@64 / itb@16384）。同时清理 misdiagnosis 期的 `idbloader_spl == "uboot"`
注释/分支段（用符号定位，非硬编码行号）——Option A 不自编 SPL，那段（写于已证伪的判断）矛盾。
board config 中「锁 prebuilt、不自编」的 in-code 注释一并改写为自编。

### Decision 5：proper u-boot 用对板 defconfig（修审查 blocker）

board 层覆盖 `bootloader.defconfig="rock-4d-spi-rk3576_defconfig"`（DT=rk3576-rock-4d-spi），
**不沿用** SoC 层 generic `rk3576_defconfig`（DT=rk3576-evb）。
- 为何：见「根因再诊断」(B)。evb DT 缺 ROCK 4D 的 SPI NOR pinmux + 板级节点 → 错板 proper。
  `rock-4d-spi-rk3576_defconfig` 已核验存在于 radxa u-boot next-dev-v2026.01，正是官方 SPI
  启动配方（含 SPL/FIT/UFS/MTD + 正确 DT），armbian 亦用此。
- 这是与 Decision 1（idbloader）正交的修复：DT 在 proper（u-boot.itb），SPL（rkbin）与之无关。

## Risks / Trade-offs

- [rkbin SPL v1.08 ↔ 自编 proper（next-dev-v2026.01）非同源、handoff hang] → FIT 自描述地址
  使其大概率成立；上板串口须**三点确认**：(1) SPL banner、(2) `Jumping to U-Boot(0x...)` 后
  proper banner、(3) proper 内 `ufs` 枚举成功；缺一即切 Option B（自编 SPL）。
- [归档根因「缺 boost」未干净复现、可能 DT 才是真因] → 上板第一步做干净复现实验（见 Migration），
  实证 A/B 贡献后再据此固化 design 根因结论。
- [boot_merger `IDB_PATH` 文件名随 rkbin 版本漂移] → 从 ini 动态解析 `IDB_PATH=`（精确
  `startswith("IDB_PATH=")`，与 `_extract_output_path` 的 `PATH=` 不互相误匹配，已核验）。
- [`rock-4d-spi-rk3576_defconfig` 存在性] → 已核验存在（前置依赖消除）；tasks 仍保留一条
  容器内存在性确认，避免 bring-up 漂移。
- [rkbin branch-tracking 无 commit pin，blob 版本可能更新] → 既有风险，本变更不扩大。
- [boot_merger 是 x86 闭源二进制、需 docker 容器跑] → 已验证可跑（prebuilt 路径现已在跑）。

## Migration Plan

- 仅影响 ROCK 4D 构建；其他板无变化。回滚：恢复 `prebuilt_spi_image`、移除 `flash_spi_loader`。
- **上板第一步＝干净复现实验**（区分 A/B 真因）：先用「现存 RKNS idbloader（boost 在）+ 自编
  proper（**对板 rock-4d-spi DT**）」上板，观察 UFS 是否枚举：
  - 枚举成功 → 主因是 B（DT 错板），A（boot_merger）为正确装配方式的加固；
  - 仍崩 → 真因不在 idbloader 装配/DT，转查 SPL↔proper 非同源（切 Option B）。
- 上板前先离线自检 spi.img（sector 64=`RKNS` + `strings` 验 boost/ddr/bl31/spl 版本 + proper
  DT 含 rock-4d 不含 evb），降低刷砖风险。

## Open Questions

- `rk3576-rock-4d-spi`（u-boot DT）是否含 `&ufs okay` 使 proper 能枚举 UFS？上板串口确认。
- rkbin SPL v1.08 ↔ radxa proper handoff 是否需特定 load addr 对齐？上板三点确认覆盖。
- 干净复现若证实「缺 boost」非真因，是否回写订正已归档 2026-06-20 的根因结论？（文档层面，
  非本变更代码范围）
