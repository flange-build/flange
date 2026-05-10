## Context

flange 已支持 Rockchip 与 Allwinner A733 两个 SoC 阵营。两者在引导链上的形态差异很大：

| 平台 | 第一阶段 | 拼装工具 | 写入位置 |
|---|---|---|---|
| Rockchip | `idbloader.img`（rkbin DDR + miniloader） | `mkimage -T rksd -n <chip>` | LBA 64 of user area |
| Allwinner A733 | `boot0_*.bin`（eGON header） | `boot_package_create.py` | offset 16 KiB of user area |
| **Amlogic S905D3** | `bl2.bin`（DDR init） + `bl30.bin` / `bl301.bin`（SCP） + `bl31.img`（TF-A） + `u-boot.bin` | `aml_encrypt_sm1` | **eMMC hw boot0 partition (offset 0x200)** |

Amlogic 的引导链是三家中最厚的：BL2 / BL30 / BL301 / BL31 全部 vendor blob，加上 SoC 家族特定的 DDR 固件（lpddr4_1d.fw 等），最终用 `aml_encrypt_sm1` 工具签出 `u-boot.bin.sd.bin`。flange 框架层（`registry.py` / `merge.py` / `engine.py` / `flash.py`）已实现的两层 SoC 自动发现 + FlashStrategy 接口足够承载这次扩张，无须改动。

外部依赖侧（已核实）：

| 资源 | 仓库@分支 / 来源 | 用于 |
|---|---|---|
| u-boot | `u-boot/u-boot @ v2024.10` | 主线 u-boot，含 `khadas-vim3l_defconfig`（自 v2019.10） |
| FIP blobs + 工具 | `LibreELEC/amlogic-boot-fip @ master`，**board** 子目录 `khadas-vim3l/` | bl2.bin / bl30.bin / bl301.bin / bl31.img / DDR fw（多种）+ `aml_encrypt_g12a` 工具（SM1 复用 G12A 工具链）+ `acs.bin` / `acs_tool.py` / `blx_fix.sh` 辅助工具 + `Makefile`（`include ../g12a.inc`）|
| kernel | `torvalds/linux @ v6.12`（mainline LTS） | 含 `arch/arm64/boot/dts/amlogic/meson-sm1-khadas-vim3l.dts`，支持到 2030 |
| WLAN/BT 通用固件 | Ubuntu `firmware-brcm80211` apt 包（来自 linux-firmware） | `brcmfmac4359-sdio.bin`（WiFi 固件本体）+ 通用 `BCM4359C0.hcd`（备用） |
| AP6398S 板级覆盖 | `khadas/fenix @ master`，路径 `archives/hwpacks/wlan-firmware/brcm/` | `brcmfmac4359-sdio_ap6398s.txt`（VIM3L NVRAM）+ `BCM4359C0_ap6398s.hcd`（AP6398S 模块板级 BT patchram） |

实板硬件：Khadas VIM3L（S905D3，4×Cortex-A55 @ 1.9GHz，2GB DDR4，16GB eMMC，板载 GbE，板载 AP6398S WLAN/BT M.2 模块，UART_AO @ 921600bps 调试串口）。

host 端依赖：

- `pyamlboot`（pip install pyamlboot 或 git clone https://github.com/superna9999/pyamlboot.git，MIT）—— 用于 MaskROM (1b8e:c003) 阶段把 u-boot 推到 SoC DDR。
- `android-tools-fastboot`（Ubuntu apt 包）—— u-boot 进 fastboot 模式后写各分区。

## Goals / Non-Goals

**Goals:**

- 新开 `amlogic` 平台，与 `rockchip` / `allwinnera733` 同形（两层 SoC 自动发现、FlashStrategy 接口实现）。
- s905d3 SoC 配置完整声明 mainline u-boot / mainline kernel / FIP blobs 来源，bootloader builder 走 mainline `u-boot.bin` → `aml_encrypt_sm1` → `u-boot.bin.sd.bin` 流程。
- VIM3L 第一版"串口 + SSH + Wi-Fi 关联 + BT scan"端到端验证：MaskROM (KEY1) → pyamlboot 推 u-boot → 自动进 fastboot → 写 boot0 + GPT 各分区 → 上电 → ttyAML0 banner → systemd → eth0 IP → ssh → `iw wlan0 scan` → `bluetoothctl scan`。
- 现有 Rockchip 与 Allwinner A733 不回归（无共享代码改动）。

**Non-Goals:**

- 不引入"SoC 家族"中间继承层；不动 `registry.py` / `merge.py` / `engine.py`。
- 不为 S905D3 启用 GPU (Mali-G31) / HDMI / VPU / NPU。
- 不做 SD 卡启动（首版仅 eMMC + USB Burning）。
- 不自编 TF-A（用 LibreELEC 预构建 `bl31.img`）。
- 本变更不回填整个 `amlogic-platform` capability 的全部历史行为；spec 范围只覆盖本次新增的契约。

## Decisions

### Decision 1: 平台命名 `amlogic`（vendor-wide），不用 family-narrow

**选择**：`builder/platforms/amlogic/` + `components/platform/amlogic/`，SoC 子目录用 `s905d3/`。

**理由**：

- Rockchip 模式（vendor-wide，多 SoC 共存）已在 RK3566/RK3568/RK3582/RK3588/RK3588S 验证可行；Amlogic 各 family（G12A / SM1 / SC2）的 FIP 流程顶层一致（都是 `aml_encrypt_<family>` + 一组 blob），靠 SoC config 注入 `fip_tool` / `fip_blobs_subdir` 两个字段即可切换 family。
- `allwinnera733` 之所以 family-narrow，是因为 A733 的 boot0/sun60 工具链跟 H 系/T 系 Allwinner 完全不同源；Amlogic 各 family 间反而高度相似。
- 后续若加 S905X4 (SC2) / A311D2 (T7)，只需加 SoC 子目录 + 注入对应 family 的 `fip_tool`，不需重开平台。

**备选**：

- *`amlogicsm1`*：family-narrow，与 a733 风格一致 — 但 SM1/SC2 之间的差异远小于 a733 vs H 系，过度切分。
- *按 SoC 单独立平台 `amlogics905d3`*：粒度过细，无收益。

### Decision 2: u-boot 走 mainline + 外挂 LibreELEC fip blobs（不用 Khadas 下游 u-boot）

**选择**：`bootloader.repo = "https://github.com/u-boot/u-boot.git"`，`branch = "v2024.10"`，`defconfig = "khadas-vim3l_defconfig"`。FIP blobs 与 `aml_encrypt_sm1` 工具走独立仓库声明（见 Decision 3）。

**理由**：

- mainline u-boot 自 v2019.10 起就支持 VIM3L，走标准 Generic Distro Boot（extlinux.conf）—— 与 flange 全平台 boot 入口约定完全对齐。RK3588 实测教训：Android-style 板级 defconfig 的固定 bootargs 会绕过 extlinux APPEND，引发 `root=PARTUUID` 截短 + `rootwait` 永久阻塞（add-rk3588-radxa-rock5b design Decision 3.5）。Khadas 下游 u-boot 历史含 multi-boot button + Android-style 启动逻辑，极可能复刻同类坑。
- 主线优势：跟随社区 release，无需维护 vendor patch；u-boot 升级与 kernel 升级解耦。
- "外挂 fip blobs"：mainline u-boot 不含任何 SoC 厂商私有 blob（Amlogic / Rockchip 都同样情况），blob 由 SoC config 的 `repos.amlogic-boot-fip` 字段独立声明仓库，bootloader builder 在 u-boot 编完后调用 `aml_encrypt_sm1` 把 blob 与 u-boot proper 拼装。

**备选**：

- *Khadas 下游 u-boot* (`khadas/u-boot`)：树内自带 `fip/vim3l/` blobs（无须外挂），但 Android-style multi-boot 风险已述。
- *LibreELEC 自维护 u-boot fork*：仅服务 LibreELEC，不主流。

### Decision 3: FIP blobs 与 `aml_encrypt_g12a` 工具来源 = `LibreELEC/amlogic-boot-fip`，**board 粒度**

**选择**：在 SoC config 的 `repos` 块声明 `amlogic-boot-fip = {repo: "https://github.com/LibreELEC/amlogic-boot-fip.git", branch: "master"}`。仓库内部按 **board** 而非 family 分目录（`khadas-vim3l/` / `aml-s905d3-cc/` / `khadas-vim3/` / ...），每个 board 目录含完整 blob 集 + `aml_encrypt_<family>` 工具 + `Makefile`（`include ../<family>.inc`）。

调用方式：`./build-fip.sh khadas-vim3l <path-to-u-boot.bin> <out-dir>` → 产出 `<out-dir>/u-boot.bin`（FIP 已封装但还不是 SD 可启动镜像）→ 再调一次 `aml_encrypt_g12a --bootsd --infile <out>/u-boot.bin --output <out>/u-boot.bin.sd.bin` 得 SD/eMMC 可启动镜像；`--bootusb` 得 `u-boot.bin.usb.bl2` / `u-boot.bin.usb.tpl`（pyamlboot USB 推送用）。

**字段分层**：

- **SoC 层**（`s905d3/config.py`）：声明 `bootloader.fip_family_inc = "g12a.inc"` + `bootloader.fip_tool = "aml_encrypt_g12a"`（SM1 family 工具链）。
- **board 层**（`khadas-vim3l/config.py`）：声明 `bootloader.fip_board_dir = "khadas-vim3l"`（仓库内 board 子目录名）。

board 粒度的字段位置反映了仓库本身的组织方式：每个 board 在 amlogic-boot-fip 内有独立目录、独立 blob 集合（`khadas-vim3l/` 与 `aml-s905d3-cc/` 都是 S905D3 但 blob 不完全相同 —— DDR 配置等板级差异）。

**理由**：

- LibreELEC/amlogic-boot-fip 是 OSS 圈的 canonical fip blobs 聚合，被 LibreELEC / CoreELEC / Armbian 多家发行版共用，质量稳定，长期维护。
- 仓库授权 MIT/GPL 兼容，可放进 Docker 镜像构建链。
- 复用其官方 `build-fip.sh` 脚本而不是自己组装 `aml_encrypt_*` 命令链：脚本封装了 BL2 SIG / BL30+BL301 拼接（`blx_fix.sh`）/ BL3X 加密 / FIP 封装 / DDR fw 嵌入等多步骤，自己重写易出错且违背"用主流工具"原则。
- 工具名修正：S905D3 是 SM1 family，但 LibreELEC 仓库统一用 `aml_encrypt_g12a`（G12A 工具兼容 SM1 — 同代加密协议 v3）。本 design 早期版本写 `aml_encrypt_sm1` 是误判，已修正。

**备选**：

- *`khadas/utils`*：Khadas 官方 fip 维护处，含 `vim3l/` 子目录 — 与 LibreELEC 同形但维护活跃度略低，且 LibreELEC 的 board 覆盖面更广（含非 Khadas 的 lepotato / odroid-c4 等）。
- *Khadas u-boot 树内 `fip/vim3l/`*：与 Decision 2 的"用 mainline u-boot"冲突（要么走 Khadas u-boot+Khadas fip，要么 mainline u-boot+独立 fip）。
- *从 Amlogic 官方 SDK 拷贝*：闭源、无版本管理、无法纳入 OSS 构建。

### Decision 4: eMMC 布局采用 boot0 hw 分区模式（不用 user-area 模式）

**选择**：u-boot.bin.sd.bin 写入 eMMC 硬件 boot0 分区（offset 0x200，eMMC partition 1）；user area 走 GPT，含 `env` / `boot` / `recovery` / `rootfs` 四个分区。

```
eMMC hw boot0 (4 MiB):
  ├ offset 0x000  bl2.bin.encrypted (Amlogic BootROM 直读)
  └ offset 0x200  fip + u-boot proper（u-boot.bin.sd.bin）

eMMC user area (GPT, sector size 512B)：
  ├ boot      offset 0x40,     size 0x20000   (64 MiB ext4，extlinux.conf + Image + meson-sm1-khadas-vim3l.dtb)
  ├ recovery  offset 0x20040,  size 0x100000  (512 MiB ext4)
  └ rootfs    offset 0x120040, size remaining (ext4, image_size 2G, grow_on_first_boot=True)
```

布局与 rk3566 一致（同样无 idbloader/uboot raw 分区，因 BootROM 走 hw boot0 而非 user area）。env 分区暂不在首版引入：mainline u-boot 默认走 mmc raw offset 存 env，无单独分区也能工作。

**理由**：

- pyamlboot + fastboot 的写入路径对 boot0 hw 分区是原生支持（Amlogic SDK 既定流程），与 USB Burning 心智完全对齐。
- u-boot proper 不占 user area 空间，便于 GPT 调整时不冲突。
- BootROM 实际只读 boot0 hw 分区，user-area 模式需要额外的 chain-loading 路径（不省事，徒增复杂度）。
- 与 Rockchip（idbloader 在 user area LBA 64）/ Allwinner A733（boot0 在 user area 16 KiB）形成对照：Amlogic 把 BootROM 入口完全放进 hw 分区，user area 仅承载内容分区。

**备选**：

- *user-area 模式*：u-boot.bin.sd.bin 写到 user area offset 0x200，GPT 在 1MiB 之后。优势：不依赖 hw boot0 分区切换，SD 与 eMMC 流程统一。劣势：与 fastboot `flash bootloader` 的默认目标不一致（fastboot 默认写 hw boot0），需要在 u-boot fastboot config 里改 `BOOTLOADER_PARTITION` 指向 mmc0:0:0x200，工程量与可见性不抵收益。
- *混合模式*：boot0 + user area 都写一份 u-boot — 浪费空间，无收益。

### Decision 5: flash 路径采用 pyamlboot → fastboot 两段式

**选择**：`AmlogicFlashStrategy` 实现：

```
pre_flash 阶段 (pyamlboot 推 u-boot 到 DDR):
  # 注：早期 brief 假设 `python3 -m pyamlboot.pyamlboot khadas-vim3l --img ...` —
  # 实际 pyamlboot 入口是 boot-g12.py（覆盖 G12A/G12B/SM1 含 S905D3），无 board
  # 参数（board 信息已隐含在 FIP 板级打包的 binary 里）。详见 tasks.md §7.2。
  sudo boot-g12.py target/bootloader/u-boot.bin.sd.bin
  → SoC 接收完整 u-boot 镜像，bl2 在 SRAM 解密执行 → BL31 → u-boot proper
  → u-boot 自动进入 fastboot 模式（u-boot 内置 USB gadget）

flash 阶段 (host fastboot 写各分区):
  fastboot flash bootloader   target/bootloader/u-boot.bin.sd.bin
  fastboot flash boot         target/boot.img
  fastboot flash recovery     target/recovery.img
  fastboot flash rootfs       target/rootfs.img
  fastboot reboot
```

**理由**：

- pyamlboot 是社区标准工具（superna9999 维护，被 LibreELEC / Armbian 等沿用），MIT 授权，纯 Python 跨平台。
- fastboot 是 Android 生态标准协议，u-boot 主线对其有完整支持（`CONFIG_USB_FUNCTION_FASTBOOT=y` + `CONFIG_FASTBOOT_FLASH=y`），主线 `khadas-vim3l_defconfig` 已默认开启。
- 两段式自然映射到 `FlashStrategy.pre_flash()` 与 `FlashStrategy` 主流程：pre_flash 把 u-boot 推进 DDR（u-boot 还没"在板上跑"），主流程通过 u-boot 提供的 fastboot 服务做实际写入。
- host 端工具链 = pyamlboot（pip）+ android-tools-fastboot（apt），均 mainline-friendly，无 vendor binary。

**备选**：

- *纯 pyamlboot*：pyamlboot 也实现了 update 协议（写各分区），但每个 SoC family 的 update 协议有差异，社区维护活跃度低于 fastboot。
- *uuu (mfgtools)*：i.MX 生态工具，对 Amlogic 支持非主流，不考虑。
- *先 SD 卡刷 u-boot 再 dd-to-eMMC*：流程拐弯，开发者体验差，背离"USB Burning"用户期望。

### Decision 6: Wi-Fi/BT 一并做掉（与首版 Goals 同步）

**选择**：

- WiFi/BT **通用固件**通过 Ubuntu apt 包 `firmware-brcm80211` 取得（来自 linux-firmware，含完整 brcm/* tree），加进 SoC/board 的 rootfs `+packages`。
- VIM3L **板级覆盖**两件套（NVRAM + BT patchram）通过 board config 的 `rootfs.+extra_firmware` 从 `khadas/fenix` 拉取并覆盖到 `/lib/firmware/brcm/`。
- systemd 单元 `bluetooth-vim3l.service` 在 bluetooth.target 之前 `btattach -B /dev/ttyAML6 -P bcm` 把 BT UART 注册为 HCI 设备。

| 文件 | 来源 | 落地路径 | 动作 |
|---|---|---|---|
| `brcmfmac4359-sdio.bin` | Ubuntu `firmware-brcm80211` 包 | `/lib/firmware/brcm/brcmfmac4359-sdio.bin` | apt 安装即在位 |
| `brcmfmac4359-sdio.txt`（NVRAM）| `khadas/fenix:archives/hwpacks/wlan-firmware/brcm/brcmfmac4359-sdio_ap6398s.txt` | `/lib/firmware/brcm/brcmfmac4359-sdio.txt` | rename 为通用名（mainline brcmfmac fallback 永远加载该名）|
| `BCM4359C0.hcd`（BT patchram）| `khadas/fenix:archives/hwpacks/wlan-firmware/brcm/BCM4359C0_ap6398s.hcd` | `/lib/firmware/brcm/BCM4359C0.hcd` | rename 覆盖 firmware-brcm80211 默认版（板级 patchram）|

**为何不用 LibreELEC/wlan-firmware**：早期 design 假设 LibreELEC/wlan-firmware 含 `.bin` / `.hcd` 固件本体，实测它仅含 NVRAM `.txt` 覆盖文件（11 个）。固件本体的 canonical 来源是 linux-firmware，Ubuntu 已封装为 `firmware-brcm80211` 包，直接 apt 安装最干净。

**为何 NVRAM/patchram 取 fenix `_ap6398s` 后缀版**：AP6398S 是 VIM3L 实际板上的 Broadcom WiFi/BT combo 模块，板级校准与 patchram 由 Khadas 维护。通用版（无 `_ap6398s` 后缀）可能首启可用但 RF 性能不达标。

驱动走 mainline in-tree（`brcmfmac` for SDIO WiFi，`hci_uart` + `btbcm` for BT over UART），不引入 OOT 模块。

**风险与 fallback**：

| 风险 | 触发概率 | 缓解 |
|---|---|---|
| WiFi NVRAM 文件名 compatible 字符串不匹配 → `brcmfmac` 拒载 | 中（mainline 6.12 的 `meson-sm1-khadas-vim3l.dts` chosen 节点内 `firmware-name` 与 NVRAM 命名约定可能漂移） | tasks 中实测前先 grep `meson-sm1-khadas-vim3l.dts` 与 dts 头注释确认期望文件名；不一致则 patch dts 或 rename NVRAM |
| BT UART flow control 时序问题 → `btattach` 报 `Failed to set raw mode` 或 HCI 启动失败 | 中（Amlogic mainline UART_AO 历史报过类似问题） | tasks 7 阶段验证；fallback：BT 移到 phase 2（独立后续变更），WiFi 仍在首版交付。design.md 内明确 fallback 不破坏首版验收 |
| BT firmware patch 流程在 mainline `hci_uart` 与 `btbcm` 上工作不稳 | 低 | mainline 6.12 已有完整 `btbcm_setup_patchram` 路径，`BCM4359C0.hcd` 是 patchram 标准格式 |

**fallback 矩阵**：

| 验证结果 | 处理 |
|---|---|
| WiFi 关联成功 + BT scan 成功 | 首版按计划交付 |
| WiFi 关联成功 + BT scan 失败 | board config 删除 BT firmware 与 service，BT 拆出后续变更，**首版仍合并**（验收条件降级为"WiFi 关联"） |
| WiFi 关联失败 | block 首版合并，调试 brcmfmac dts 与 NVRAM compatible，重新进入实测 |

### Decision 7: kernel 走 mainline 6.12 LTS（不用 Khadas 下游或社区 BSP）

**选择**：`kernel.repo = "https://github.com/torvalds/linux.git"`，`branch = "v6.12"`（mainline LTS），`dts_dir = "amlogic"`，`dts = "meson-sm1-khadas-vim3l"`。

**理由**：

- 6.12 是当前 mainline LTS，支持到 2030 年，与"工程板首版"心智契合。
- mainline VIM3L 支持完整：UART_AO / eMMC HS200 / GbE r8169 / SDIO 卡（接 AP6398S）/ I²C / SPI / USB host。GPU (Mali-G31) panfrost 主线支持，但首版不启用（Non-Goal）。
- 与 a733（用 `radxa-pkg/linux-a733` BSP，5.15 base）形成对照：Amlogic 这边 mainline 走得比 Allwinner 顺得多，无须依赖 vendor BSP。
- 与 rk3588（用 argon `linux-6.1-stan-rkr4.1-buildroot` BSP）也形成对照：rk3588 GPU/VPU/NPU 重依赖 BSP；S905D3 首版无这些诉求，mainline 充分。

**备选**：

- *Khadas linux fork* (`khadas/linux`)：5.x 系，含 vendor amvdec / amlhdmi 等私有 driver，但首版 Non-Goal 不需要。
- *6.6 LTS*：上一代 LTS，更稳但活跃度低于 6.12。

### Decision 8: SoC 目录命名 `s905d3`（与 rk3566/rk3588 风格一致）

**选择**：`components/platform/amlogic/s905d3/` 而非 `components/platform/amlogic/sm1/`。

**理由**：

- 与 Rockchip 的 `rk3566` / `rk3588` 命名风格一致（具体型号，非 family code）。
- SM1 family 还包括 S905X3 / S905Y3（同 die 不同 binning），后续若适配会作为 `s905x3/` / `s905y3/` 兄弟目录并列，避免 family code 与具体型号混淆。
- `meson-sm1-*.dts` 这类 family-coded 命名仅在 kernel DTS 命名空间内成立；flange 的 SoC 目录与 BootROM 视角对齐（aml_encrypt_<family> 工具的 family 参数是 `sm1`，但用 SoC 目录注入 `fip_tool="aml_encrypt_sm1"`、`fip_blobs_subdir="sm1"` 即可，不需要把目录名也用 family）。

**备选**：

- *`sm1/`（family code）*：与 a733 风格类似（family-named），但与 Rockchip 风格分裂；且 SM1 内多个具体 SoC 时无处放置差异。
- *`amlogic-s905d3/`（vendor + SoC）*：冗余（已经在 `components/platform/amlogic/` 子目录下）。

### Decision 9: spec 范围限定为本次新增契约

**选择**：新建 `amlogic-platform` 与 `amlogic-flash` capability 时，requirements 只覆盖本变更引入的契约（amlogic 平台模块、s905d3 SoC 配置、khadas-vim3l 板级链路、AmlogicFlashStrategy 两段式），不回填任何"已存在但未规范化"的历史行为（本变更无）。

**理由**：

- OpenSpec 鼓励变更最小化；amlogic 平台是首次引入，不存在"补全历史 spec"的负担，但仍需明确 spec 边界以防混入相邻 capability（如 platform-abstraction）的 requirements。
- Wi-Fi/BT 适配的 requirements 放进 `amlogic-platform`（板级 firmware）而非另开 capability，因这是 board-specific 配置而非平台级契约。

## Risks / Trade-offs

| 风险 | 缓解 |
|---|---|
| **mainline u-boot v2024.10 的 `khadas-vim3l_defconfig` fastboot 配置漂移** → u-boot 进入 fastboot 模式失败，pre_flash 后 host 端 fastboot 找不到设备 | tasks 中实测前先 grep `configs/khadas-vim3l_defconfig` 内 `CONFIG_USB_FUNCTION_FASTBOOT=y` 与 `CONFIG_FASTBOOT_FLASH=y`；缺失则在 SoC 层 patches 中补 fragment |
| **LibreELEC/amlogic-boot-fip 的 `aml_encrypt_sm1` 工具是 x86_64 二进制** → 在非 x86_64 host 或 ARM Docker 容器内不能跑 | flange 构建已要求 x86_64 host（参见 envsetup.sh），实测覆盖；ARM host 用户暂不支持，归为 Non-Goal |
| **GPT 偏移量 user-area 与 fastboot u-boot 内置分区表不一致** → fastboot flash 写错位置 | tasks 阶段在 u-boot 启动后用 `mmc list` 与 `part list mmc 1` 验证；u-boot 主线 `khadas-vim3l_defconfig` 默认从 `boot.scr` 或 `gpt` 读分区表，与 host 端 partition_table.json 必须一致 |
| **fastboot reboot 后 BootROM 再次进入 USB Burning 模式（板上 KEY1 仍按住）** → 反复进入 MaskROM | flange flash 文档明确"fastboot reboot 之前松开 KEY1"；CLI 提示语带此一行 |
| **Wi-Fi NVRAM compatible 字符串与 dts 不匹配** → brcmfmac 拒载 | 详见 Decision 6 风险表 |
| **BT btattach 卡死或 HCI 不上来** | 详见 Decision 6 fallback 矩阵 |
| **AP6398S 模块版本差异**（板上贴的可能是 AP6398SR1 等 revision） | tasks 实测时通过 `dmesg | grep brcmfmac` 确认实际加载的 firmware；若 SR1 需要 `BCM4359C0_003.001.012.0271.0349.hcd` 等更精细的 patchram，fallback 到对应文件 |
| **eMMC hw boot0 分区写入时序问题** → BootROM 重启后无法识别 u-boot | fastboot 主流程在写 bootloader 前必须 `fastboot oem switch_partition boot0` 或等价命令；u-boot 主线对 mmc dev 切 hw 分区的 fastboot extension 已有标准实现，tasks 阶段验证 |

## Migration Plan

本变更纯增量，无 breaking。落地顺序（与 tasks.md 对齐）：

1. **平台模块骨架**：`builder/platforms/amlogic/` 6 个 builder 文件 + `__init__.py`。先空实现 + 抛 NotImplementedError，仅打通 `engine.py` 的动态 import 路径。
2. **平台数据层**：`components/platform/amlogic/{config.py, s905d3/config.py}`。验证 `_load_platform_config("amlogic")` / `_load_soc_config("s905d3")` 返回完整字典。
3. **bootloader builder 实现**：mainline u-boot 编译 → `aml_encrypt_sm1` FIP 打包 → `u-boot.bin.sd.bin` 落地 target。
4. **kernel/boot/rootfs/recovery/image builder 实现**：与 Rockchip / Allwinner 同形，差异主要在 partitions 布局与 boot 分区结构。
5. **board 与 firmware**：`components/board/khadas-vim3l/` + Wi-Fi/BT firmware 三件套。
6. **flash 策略**：`builder/flash.py` 加 `AmlogicFlashStrategy`，注册到 `_FLASH_STRATEGIES`。
7. **实板验证**：USB Burning → 五分区刷写 → 串口 banner → SSH → Wi-Fi → BT。
8. **wiki 与 spec 归档**：`wiki/boards/khadas-vim3l.md` + `/opsx:archive`。

**回滚**：每步独立可回滚（git revert 单 commit）；最坏情况整 PR revert 不影响现有 Rockchip / Allwinner 板（无共享代码改动）。

## Open Questions

（组 1 pre-investigation 已关闭以下原 Open Questions，结论合并入对应 Decision）

- ~~mainline `khadas-vim3l_defconfig` 是否默认开 fastboot gadget？~~ → **不开**。defconfig 只有 `CONFIG_USB_GADGET_DOWNLOAD=y` + Amlogic ADNL VID/PID（0x1b8e:0xfada）+ `CONFIG_CMD_DFU=y`。Decision 5 / Decision 7 已更新：SoC 层挂 `flange-fastboot.config` fragment 启 fastboot（与 a733 平台 defconfig+`bsp_defconfig`+...config 合并机制同形）。
- ~~`aml_encrypt_sm1` 在 sm1/ 路径是否存在？~~ → **不存在**。仓库 board-organized，工具实际名 `aml_encrypt_g12a`（SM1 复用 G12A），位于 `khadas-vim3l/aml_encrypt_g12a`。Decision 3 已更新。
- ~~WiFi NVRAM 文件名约定？~~ → 取 `khadas/fenix:archives/hwpacks/wlan-firmware/brcm/brcmfmac4359-sdio_ap6398s.txt` rename 为 `brcmfmac4359-sdio.txt`（mainline brcmfmac fallback 名）。Decision 6 已更新。

剩余 Open Questions：

- **VIM3L 板 GbE PHY 复位时序**：mainline `meson-sm1-khadas-vim3l.dts` 已正确声明 `&ethmac` 与 `RTL8211F` PHY，但实测中曾报告"PHY 启动后链路不稳"（不影响板，但偶发）。Non-blocker，仅观察。
- **eMMC 启动 vs SD 卡启动跳线**：VIM3L 默认 boot from eMMC；若用户测试时把 SD 卡插上，BootROM 会优先尝试 SD（影响刷写后启动验证）。文档与 wiki 中明确"刷写后拔 SD"。
- **fastboot fragment 实际生效**：mainline u-boot v2024.10 是否完整支持 `CONFIG_FASTBOOT_FLASH_MMC_DEV=1` + GPT 分区表 partition-name 路由？需 tasks 4.x 实测验证 fragment 工作。
