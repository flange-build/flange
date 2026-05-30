## Context

现有 Amlogic 支持由 `add-amlogic-khadas-vim3l` 引入，已经具备 vendor-wide
`amlogic` 平台策略、LibreELEC `amlogic-boot-fip` FIP 打包、mainline U-Boot
+ Linux 6.12、以及 `pyamlboot` → fastboot 的两段式刷写路径。Radxa Zero
1.5 与 VIM3L 同属 Amlogic Meson 系，但 SoC family、U-Boot defconfig、FIP
board 目录、DTS 与无线模组都不同：

| 项目 | Khadas VIM3L | Radxa Zero 1.5 |
|---|---|---|
| SoC | S905D3 / SM1 | S905Y2 / G12A |
| U-Boot defconfig | `khadas-vim3l_defconfig` | `radxa-zero_defconfig` |
| kernel DTS | `meson-sm1-khadas-vim3l` | `meson-g12a-radxa-zero` |
| FIP board 目录 | `khadas-vim3l/` | `radxa-zero/` |
| 存储 | eMMC | 用户确认 8GB eMMC |
| Wi-Fi/BT | AP6398S / BCM4359 | AW-CM256SM / CYW43455 系列 |
| host | Linux/macOS 均可 | 用户确认 macOS |

本变更处于 explore → propose 阶段，仅创建 OpenSpec 方案，不实现代码。

## Goals / Non-Goals

**Goals:**

- 支持 Radxa Zero 1.5、8GB eMMC、AW-CM256SM Wi-Fi/BT 的默认
  `radxa-zero-default-debug` / `radxa-zero-default-release` lunch target。
- 复用现有 `amlogic` 平台策略，新增 `s905y2` SoC 层与 `radxa-zero` board 层。
- 通过 macOS host 完成 MaskROM → `boot-g12.py` → fastboot → eMMC 刷写。
- 首版关闭 recovery，只刷写 `bootloader`、`boot`、`rootfs`。
- 实板验收包括 TTL 串口启动日志、系统登录、Wi-Fi scan、Bluetooth scan。

**Non-Goals:**

- 不支持无 eMMC 的 Radxa Zero SKU。
- 不支持 SD 卡启动。
- 不启用 recovery。
- 不把 HDMI、GPU、VPU、音频、GPIO header overlay、SPI/I2C 外设扩展纳入首版。
- 不重构 `builder/engine.py`、`builder/config/*` 或 FlashStrategy 框架。

## Decisions

### Decision 1: 新增 `s905y2` SoC，而不是复用 `s905d3`

**选择**：创建 `components/platform/amlogic/s905y2/config.py`。该层声明 S905Y2/G12A
共同信息：mainline U-Boot、mainline Linux、`amlogic-boot-fip`、G12A FIP 工具、
`ttyAML0` console 与基础分区策略。

**理由**：

- ProjectSpec 要求 platform → SoC → board 三层继承；S905Y2 与 S905D3 的
  family code、DTS、U-Boot defconfig 都不同，不应塞进 board 层绕过 SoC 层。
- LibreELEC FIP 仓库按 board 组织，但加密工具与 family include 仍是 SoC/family
  级概念：Radxa Zero 走 G12A，工具名仍为 `aml_encrypt_g12a`。
- 后续如果支持 S905Y3 / S905X2，可复用相同模式。

**备选**：

- 仅新增 board、复用 `s905d3`：会把 `khadas-vim3l_defconfig`、SM1 注释与
  S905D3 假设泄漏到 Radxa Zero，不可维护。
- 新开 `amlogicg12a` 平台：切得太细，违背现有 vendor-wide Amlogic 设计。

### Decision 2: Radxa Zero board 层只声明板级差异

**选择**：`components/board/radxa-zero/config.py` 声明：

- `board = "radxa-zero"`
- `soc = "s905y2"`
- `platform = "amlogic"`
- `kernel.dts = "meson-g12a-radxa-zero"`
- `bootloader.fip_board_dir = "radxa-zero"`
- `recovery.enabled = False`
- rootfs 的 AW-CM256SM 固件与必要包

**理由**：

- 与 `khadas-vim3l` 已有约定一致：repos、arch、fip_tool、kernel_args、dts_dir
  留在 platform/SoC 层，board 层不重复。
- Radxa Zero 1.5 的 eMMC 容量是用户确认的 8GB；rootfs 分区仍用
  `grow_on_first_boot`，不在配置里写死 8GB 容量。

### Decision 3: 首版关闭 recovery

**选择**：Radxa Zero 首版只保留 bootloader / boot / rootfs。board 层覆盖
`recovery.enabled = False`，分区表移除 recovery entry。

**理由**：

- 用户明确不启动 recovery。
- 当前 Amlogic fastboot fragment 需要在 U-Boot `partitions` env 中声明 GPT；
  去掉 recovery 可避免首版同时修改/验证 recovery boot path。
- 8GB eMMC 空间较小，省掉 512MB recovery 分区更符合小板默认系统。

**备选**：

- 保留 recovery 分区但不启动：浪费空间，且 fastboot GPT 字符串仍需覆盖。
- 做可选 variant：对首版目标过宽，后续可单独起 `radxa-zero-recovery` 变更。

### Decision 4: macOS host 刷写作为首版验收

**选择**：实板验收在 macOS 上执行，依赖：

- `fastboot`（Android platform tools）
- `boot-g12.py`（pyamlboot）
- Python `pyusb`
- Homebrew `libusb`

**理由**：

- 用户当前 host 是 macOS，且工具已基本装好。
- 现有 `AmlogicFlashStrategy` 已包含 macOS `ioreg` 探测与 libusb dyld fallback
  方向；Radxa Zero 应覆盖这条路径，避免只在 Linux 上“纸面支持”。

**风险**：macOS 下 `sudo` 与 SIP/DYLD 行为容易导致 pyusb 找不到 libusb。
实施时应把 host 预检命令写进 tasks 与文档。

### Decision 5: AW-CM256SM 固件先调查、再固定声明

**选择**：Wi-Fi/BT 是首版验收项，但实施第一阶段必须先确认 AW-CM256SM 的
实际固件文件名与来源，再写入 `rootfs.+extra_firmware`。初始预期为
CYW43455/BCM43455 系列：

| 用途 | 初始预期文件名 |
|---|---|
| Wi-Fi firmware | `brcm/brcmfmac43455-sdio.bin` |
| Wi-Fi NVRAM | `brcm/brcmfmac43455-sdio.txt` 或 board-specific `.txt` |
| BT patchram | `brcm/BCM4345C0.hcd` |
| CLM blob（如驱动请求） | `brcm/brcmfmac43455-sdio.clm_blob` |

**理由**：

- Radxa Zero 的 AW-CM256SM 模组与 VIM3L 的 AP6398S 不同，不能照搬
  `brcmfmac4359-*`。
- brcmfmac 的实际请求路径会受 SDIO ID、DTS compatible、board name 影响；
  以 dmesg 实测为准比凭文件名猜测更稳。
- Ubuntu `linux-firmware` 包体积较大，不应无脑纳入默认 embedded rootfs；
  优先使用 `radxa-pkg/radxa-firmware` 或精准 git source。

**验收标准**：不只是文件存在，还必须 `iw wlan0 scan` 与 `bluetoothctl scan on`
通过，并且 `dmesg` 无 brcmfmac/btbcm 固件缺失错误。

### Decision 6: 先沿用 mainline 6.12 LTS

**选择**：`s905y2` 默认使用 `torvalds/linux @ v6.12` 或后续 6.12.y，DTS 为
`arch/arm64/boot/dts/amlogic/meson-g12a-radxa-zero.dts`。

**理由**：

- 本地缓存已显示现有 Linux 源包含 `meson-g12a-radxa-zero.dts`。
- 首版不做 HDMI/GPU/VPU，mainline 对串口、eMMC、SDIO Wi-Fi、USB 与基本
  rootfs 启动更可预测。

### Decision 7: bootloader 使用 mainline `radxa-zero_defconfig` + fastboot fragment

**选择**：`bootloader.defconfig` 为 list，先应用 `radxa-zero_defconfig`，再应用
Radxa Zero/S905Y2 fastboot fragment。

**理由**：

- mainline `radxa-zero_defconfig` 已存在，但和 VIM3L defconfig 一样默认偏向
  DFU/USB download，不保证开启 flange 需要的 fastboot flash。
- fastboot fragment 中的 `CONFIG_FASTBOOT_FLASH_MMC_DEV`、`CONFIG_PREBOOT`
  与 GPT `partitions` 字符串可能与 VIM3L 相同，也可能需要按实板 `mmc list`
  调整；把 fragment 放在 `s905y2` 层或 board 层便于独立验证。

## Risks / Trade-offs

| 风险 | 缓解 |
|---|---|
| AW-CM256SM 固件文件名猜错，Wi-Fi/BT 驱动加载失败 | 实施第 1 阶段先从 Radxa 官方镜像、`radxa-firmware`、`linux-firmware` 与 dmesg 请求路径确认文件名 |
| Radxa Zero U-Boot 中 eMMC 不是 `mmc2` | 串口进入 U-Boot 后执行 `mmc list` / `mmc dev` 验证，再固定 fastboot fragment |
| `boot-g12.py` 对 Radxa Zero 需要裸 FIP 而非 SD image | 以当前 `AmlogicFlashStrategy.generate_pre_flash_config()` 与实测为准；任务中安排校准 spec/code 文案 |
| macOS pyusb 找不到 libusb | 预检 `python3 -c "import usb"` 与 `brew --prefix libusb`；必要时沿用 dyld fallback |
| 8GB eMMC rootfs 初始镜像过大 | 保持 rootfs `image_size=2G` + 首启 grow，避免默认装 `linux-firmware` 整包 |
| 无线验收扩大首版耗时 | 用户明确要求 Wi-Fi/BT，保留为必须验收，但把固件调查拆成前置任务 |

## Migration Plan

1. 前置调查：确认 U-Boot defconfig、FIP 目录、kernel DTS、AW-CM256SM 固件来源、
   macOS host 工具、U-Boot mmc 拓扑。
2. 新增 `s905y2` SoC 配置与 fastboot fragment。
3. 新增 `radxa-zero` board 配置、overlay、Wi-Fi/BT 固件声明。
4. 补配置与 flash 单元测试，验证 `resolve_config()`、lunch target、flash-config。
5. 容器内构建 bootloader/kernel/boot/rootfs/image。
6. macOS host 实板刷写与 TTL 串口验证。
7. Wi-Fi/BT 实测，按 dmesg 修正固件文件名。
8. 补 wiki 与排障文档。

回滚方式：本变更应保持纯增量；删除 `s905y2` 与 `radxa-zero` 配置目录即可移除
新板支持，不影响既有 `khadas-vim3l`。

## Open Questions

- AW-CM256SM 的最终 Wi-Fi NVRAM 与 BT patchram 文件名、来源仓库和版本 pin。
- Radxa Zero 上 U-Boot fastboot 应使用的 eMMC mmc dev 编号。
- `radxa-zero_defconfig` 是否已完整支持 extlinux/bootstd；若不支持，需要 fragment
  补齐。
- Radxa Zero 1.5 的蓝牙 UART 是否会被 mainline DTS 自动绑定，还是需要 board
  私有 systemd `btattach` 单元。
