---
title: thundercomm-rubikpi3
type: board
status: wip
sources:
  - components/board/thundercomm-rubikpi3/config.jsonnet
  - components/board/thundercomm-rubikpi3/patches/kernel/0001-dts-qcs6490-rubikpi3-lt9611-dsi-port-b.patch
  - components/board/thundercomm-rubikpi3/patches/kernel/0002-dts-qcs6490-rubikpi3-usb-qmp-phy-supplies.patch
  - components/board/thundercomm-rubikpi3/overlay/etc/systemd/system/rubikpi3-usb-firmware.service
  - components/board/thundercomm-rubikpi3/overlay/usr/lib/flange/rubikpi3-usb-firmware
  - components/platform/qualcommqcs6490/qcs6490/config.jsonnet
  - builder/flash/qualcomm_ufs.py
  - builder/platforms/qualcommqcs6490/boot.py
  - components/app/usbmoded/usbmoded/scene.py
  - openspec/changes/archive/2026-09-26-add-qcs6490-thundercomm-rubikpi3/
  - openspec/specs/qualcommqcs6490-thundercomm-rubikpi3/spec.md
related:
  - "[[qualcommqcs6490 平台]]"
  - "[[radxa-dragon-q6a]]"
  - "[[FlashStrategy 抽象]]"
updated: 2026-09-26
---

> 阅读前提：先完成[初学指南](../../docs/first-steps.md)的环境准备，运行
> `flange target list thundercomm-rubikpi3` 确认当前目标。
> 本页是配置摘要与硬件记录；2026-09-26 完成 Docker 构建并在实板上跑起 default 产物，
> 下文「实板观察」只记录已看到的现象，「待验收」项不代表已可用。
> [返回板卡索引](index.md) · [构建与刷写流程](../workflows/lunch-build-flash-流程.md)

## TL;DR

Thundercomm RUBIK Pi 3（Qualcomm QCS6490）是 [[qualcommqcs6490 平台]] 的第二块板，
复用 Q6A 的主线内核 `radxa/kernel@linux-7.0.2`、Mesa freedreno/turnip 与
UEFI → GRUB(grub-with-dtb) 启动链。与 Q6A 的根本差异是 **签名启动固件位于 UFS
boot LUN 1-5**（Q6A 在 SPI NOR），因此 `flange flash` 用一次 `edl-ng rawprogram`
会话同时写入固件、dtb 分区与 LUN0 系统盘。

| target | 用途 |
|---|---|
| `thundercomm-rubikpi3-default-{debug,release}` | 无桌面，串口 `ttyMSM0` / adb / SSH |
| `thundercomm-rubikpi3-desktop-{debug,release}` | `ubuntu-desktop` 包：GNOME，HDMI 经 LT9611 输出 |

## 板级契约

- **参考来源**：Thundercomm Yocto 工程（QLI 1.5，vendor 6.6.90 + KGSL/Adreno 私有栈 +
  bcmdhd）只作为硬件事实来源；flange 走主线内核 + 开源图形栈，不沿用其 BSP 内核。
- **kernel/DTB**：`qcs6490-thundercomm-rubikpi3.dtb`（7.0.2 已收录）。板级 backport 上游两处
  DTS 修复：LT9611 DSI 输入改到 Port B（上游 `ebcf2240a249`，否则 HDMI 无输出）、
  USB QMP PHY vdda-phy/vdda-pll 供电对调（上游 `83185fc5f51e`）。外设驱动均由 SoC 层
  defconfig 链启用，板级不加 `kernel.config`。
- **cmdline**：在 SoC 层基础上追加 `pcie_pme=nomsi deferred_probe_timeout=30`；后者避免
  msm-mdss 在 LT9611 探测前放弃，导致没有 `/dev/dri/card0`。
- **Wi-Fi/BT（AP6256）**：主线 brcmfmac + hci_uart bcm（DT serdev 自动 attach）。
  `brcmfmac43456-sdio.bin` 与 `.clm_blob` 取自 `radxa-pkg/radxa-firmware`（与
  orangepi-cm4 实证组合相同，二者须同版本）；板级 NVRAM
  `brcmfmac43456-sdio.thundercomm,rubikpi3.txt` 与 `BCM4345C5.hcd` 取自
  `rubikpi-ai/rubikpi3-firmware`，与参考工程 rootfs 逐字节一致。rootfs 显式加 `bluez`。
- **ADSP/CDSP/GPU 固件**：平台层 `linux-firmware` + `linux-firmware-dragonwing`
  已提供 DTS 引用的 `qcom/qcs6490/Thundercomm/RubikPi3/adsp.mbn` 与 `qcom/qcs6490/cdsp.mbn`。
- **Renesas USB3**：USB3 Type-A 口与板载以太网（USB CDC-NCM，`eth0`）挂在 PCIe Renesas
  uPD720201 后（实板 `lsusb -t` 确认），主控无外置 ROM，固件 `renesas_usb_fw.mem` 不可再分发、出厂存放在 LUN3 `usb_fw` 分区（ext4）。
  板级 overlay 的 `rubikpi3-usb-firmware.service` 在 sysinit 阶段只读挂载该分区到
  `/var/usbfw`，`/usr/lib/firmware/renesas_usb_fw.mem` 链接到挂载点，再重新探测因
  coldplug 时缺固件而未绑定的主控；分区或文件缺失时只记录并跳过。
- **分区**：沿用 SoC 层 LUN0 布局（ESP 256MiB + rootfs，4096 字节扇区，首启扩容）。

## 启动固件与刷写

`bootloader.edk2_firmware` 钉住 `rubikpi-ai/boot-assets` main@`10b8685` 的 GitHub 归档
（BOOT.MXF.1.0.c1-00430 / TZ.XF.5.29.1-00126.1，SHA256 校验），即
meta-qcom-3rdparty 主线集成所钉版本。未选用的两个版本：

| 版本 | 未选原因 |
|---|---|
| 参考工程 QLI 1.5（BOOT 00364） | Q6A 已实证该代固件与 7.0.2 kodiak DTB 不匹配（UFS probe 整机复位） |
| boot-assets `qli2.0`（BOOT 00508） | LUN3 删除 `usb_fw` 分区，出厂 Renesas 固件所在区域会被重划为 `ddr_a` |

`flange flash` 暂存并一次写入：

- LUN1-5：`bootloader.ufs_rawprogram` / `ufs_patch` 声明的官方 `rawprogram1-5.xml` 与 `patch1-5.xml`；
- LUN4 `dtb_a`：boot 组件生成的 `dtb.bin`（64MiB FAT16，内含当前内核 DTB `combined-dtb.dtb`）；
- LUN0：生成的 `rawprogram0.xml` 把 `image/raw.img` 写到扇区 0。

刷写前本地 preflight 校验：固件 XML 不得写或 patch LUN0；扇区大小与分区配置一致；
引用文件齐全且不是 Git LFS 指针；raw.img 为整扇区。LUN6（Thundercomm QLI 用户态配置，
ext 文件系统，UEFI 不读）不刷写——其 `devcfg_full.img` 在 GitHub 归档中只是 LFS 指针。
`--spi-firmware` 对本板直接拒绝；未声明 `ufs_provisions`，`--provision-ufs` 不可用
（出厂 UFS 已按官方 LUN0-6 布局初始化）。

## 实板观察（2026-09-26，default 产物）

- 00430 固件 + 7.0.2 DTB 启动到 rootfs，ADSP / CDSP remoteproc 均 up，无失败的 systemd 单元。
- `rubikpi3-usb-firmware.service` 将 `usb_fw`（`/dev/sdd3`）只读挂载到 `/var/usbfw`；
  `xhci-pci-renesas` 在约 9.7 秒绑定，USB3 总线上可见 CDC-NCM 以太网。PCI 枚举时 Renesas
  尚无固件，`quirk_usb_early_handoff` 等待约 6 秒（`xHCI HW not ready after 5 sec`）。
- `wlan0`（brcmfmac）与 `hci0` 已出现；尚未验证扫描与连接。
- Type-C 口 dwc3 依赖 pmic_glink 连接器，UDC `a600000.usb` 约 10 秒才注册，内核打印
  `dr_mode forced to gadget`，`/sys/class/usb_role` 为空（不支持 role 切换）。usbmoded 开机场景
  因等待 UDC 超时失败、需手动 `usb-mode set debug`；已修复为 UDC 注册后自动重试开机场景
  （见 [usbmoded README](../../components/app/usbmoded/README.md)）。重刷后复验：8.7 秒等待超时、
  10.5 秒 UDC 注册后重试、11.4 秒进入 `debug`，adb 无需人工干预即可连接。

## 待验收

- UFS 长时间稳定性与冷/热重启
- GRUB `devicetree` 与 UEFI dtb_a 两条 DTB 路径在本板 UEFI 上的实际行为
- HDMI（LT9611）、desktop GNOME、GPU freedreno
- AP6256 Wi-Fi 扫描/连接、蓝牙扫描；以太网链路；USB3 Type-A 外设；Type-C host 模式
- ADSP 音频、风扇温控
