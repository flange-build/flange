## Context

参考工程 `thundercomm-qcom-linux` 为 Yocto QLI 1.5：UEFI → systemd-boot → UKI + OSTree，
DTB 由 UEFI 从 LUN4 `dtb_a`（FAT，`combined-dtb.dtb`）提供，rootfs 为 LUN0 `system` 分区，
刷写用 QDL 执行 `rawprogram0-6.xml` + `patch0-6.xml`。flange 的 QCS6490 平台已完成主线化
（`radxa/kernel@linux-7.0.2`、freedreno、GRUB grub-with-dtb、LUN0 整盘 raw.img）。

## Goals / Non-Goals

**Goals:**
- `thundercomm-rubikpi3-{default,desktop}-{debug,release}` 可规划、可在 Docker 内构建全部组件。
- 从出厂 QLI / Ubuntu 状态出发，`flange flash` 一条命令写入配套启动固件与系统盘。
- 任何写入前拒绝会破坏 LUN0、引用 LFS 指针或产物缺失的刷写包。

**Non-Goals:**
- 不改变 Q6A/Q8B 的构建产物与刷写行为；不实现 UFS provisioning、LUN6 刷写与 A/B 槽切换。

## Decisions

### 复用 qualcommqcs6490 平台，板级只声明差异

内核、图形、GRUB、分区几何全部继承 SoC 层；板级只声明 DTB 名、两条 DTS backport、cmdline 追加、
无线固件、UFS 固件清单。替代方案是沿用参考工程 vendor 6.6.90 内核：需要 KGSL + Adreno 私有
用户态（Ubuntu 无对应包）且与平台已完成的主线化方向相反，故不采用。

### 启动固件版本：boot-assets main@10b8685（BOOT 00430）

参考工程的 00364 与 Q6A 上已证实与 7.0.2 kodiak DTB 不匹配的固件同代；`qli2.0`（00508）
LUN3 删除 `usb_fw`，会把出厂 Renesas 固件所在区域重划为 `ddr_a`。main@10b8685 被
meta-qcom-3rdparty 用于主线集成，LUN3 布局与出厂一致。通过 GitHub 归档 zip + SHA256 固定，
复用既有 `edk2_firmware` 下载/解压路径。

### 一次 edl-ng rawprogram 会话写入全部 LUN

LUN0 继续使用 flange 的整盘 raw.img（ESP + rootfs），由生成的 `rawprogram0.xml` 写到扇区 0；
LUN1-5 使用官方 XML。分两次调用 edl-ng 会重复 Sahara 握手，因此合并为单会话，与官方 flat
build 的 QDL 流程一致。LUN0 只允许 flange 系统盘：固件 XML 写或 patch LUN0 一律拒绝。
每次全量刷写都会重写启动固件，换取从任意出厂状态一步到位；这与 Q6A 的 SPI 单刷不同，
RUBIK Pi 3 上 `--spi-firmware` 直接拒绝。

### 新增配置字段

| 字段 | 类型 / 默认 | 层 | 约束与消费 | 缓存影响 |
|---|---|---|---|---|
| `bootloader.ufs_rawprogram` | 字符串数组 / 未声明 | board | 与 `ufs_patch` 成对非空、需 `edk2_firmware`、仅固件包根目录 `.xml`；bootloader 构建期校验、boot 产出 dtb.bin、flash-config `ufs_firmware` | bootloader、boot、image 的 config 输入 |
| `bootloader.ufs_patch` | 字符串数组 / 未声明 | board | 同上；patch 不得指向 LUN0 | 同上 |

### DTB 双路径

GRUB 仍以 `devicetree` 加载 rootfs `/boot/<dtb>.dtb`，内核更新不依赖重写 dtb 分区；全量刷写
同时把同一 DTB 写入 `dtb_a`（64MiB FAT16，布局对齐参考工程 dtb.bin），避免 UEFI 读到旧系统或
空分区中的 DTB。有构建期 overlay 时 dtb.bin 与 rootfs 使用同样的 fdtoverlay 合并结果。

### 板载固件

- AP6256：brcmfmac 的 bin 与 clm_blob 必须同版本，采用 orangepi-cm4 已实证的 radxa-firmware
  组合；板级 NVRAM 用 Thundercomm V1.4（与参考工程 rootfs 一致），以
  `brcmfmac43456-sdio.thundercomm,rubikpi3.txt` 命名由 brcmfmac 按 DT compatible 优先加载。
- Renesas uPD720201：固件不可再分发、出厂在 `usb_fw`（ext4）。沿用参考工程的挂载 + 符号链接
  方式；因 coldplug 时可能尚未挂载导致探测失败，sysinit 阶段服务挂载后对未绑定主控执行
  `drivers_probe`，分区/文件缺失时只记录不失败。

## Risks / Trade-offs

- 00430 固件与 7.0.2 DTB 的兼容性未经实板验证 → 列为首个验收项；失败时可评估 `qli2.0`
  固件并另行处理 `usb_fw` 迁移。
- 每次全量刷写重写 XBL 等固件 → 中断时经 EDL 按键重刷即可恢复（PBL 在 ROM）。
- Renesas 与 USB 网卡拓扑来自推断 → 实板以 `lsusb -t` 确认。
- GitHub 归档 zip 摘要可能变化 → SHA256 失配时构建失败而非静默使用新内容。

## Migration Plan

新增板卡，无迁移。回退即删除板级目录；新增字段未被其他板声明。
