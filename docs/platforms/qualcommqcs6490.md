# Qualcomm QCS6490 平台

QCS6490（SC7280-class）包含 Cortex-A78/A55、Adreno 643 与 Hexagon ADSP/CDSP。
启动使用签名 XBL/EDK2 → GRUB → Linux，刷写使用 EDL（紧急下载模式）与 edl-ng。
板卡页给出实际配件、固件和验收边界：[Dragon Q6A](../boards/radxa-dragon-q6a.md)、
[RUBIK Pi 3](../boards/thundercomm-rubikpi3.md)。

## 内核与执行级别

| 目标 | 内核与配置 | 执行级别 / DSP |
| --- | --- | --- |
| Q6A | radxa/kernel 7.0.2 固定 7473a9f，四段 defconfig，KVM 组合 DTB | UEFI Auto/Enabled 进入 EL2；固件预加载 DSP，内核 attach |
| RUBIK Pi 3 default / desktop / default_ax210 | rubikpi-ai/linux 6.6.90，qcom_defconfig 与下游视频驱动 | EL1；DSP 与编码可同时使用 |
| RUBIK Pi 3 mainline | SoC 层 7.0.2 与平台补丁，KVM xbl_config | EL2；本板 TZ 缺 PAS_GET_RSCTABLE，DSP 离线 |

SoC 默认源固定 `7473a9fca2b08623319e497f4f811746baddb7bc`。
配置顺序为 `defconfig → qcom_module.config → radxa.config → radxa_custom.config`，再应用 kernel.config。
UFS/SCSI/QMP PHY 和 interconnect 必须 built-in：该启动路径没有 initramfs，
否则形成“挂载 rootfs 需要模块、加载模块需要 rootfs”的循环依赖。

## 启动与分区

- boot 组件用 `grub-mkimage -O arm64-efi` 生成独立 BOOTAA64.EFI、grub.cfg 和 FAT ESP。
- ESP 只保存 GRUB 与菜单；内核/DTB 在 rootfs `/boot`，GRUB 用 ext2 模块读取。
- 通过 `acpi=off` 选择 Device Tree，root 参数使用 PARTLABEL 等内核可直接解析的标识。
- 物理扇区为 4096 B，配置 offset/size 仍按 512 B 单位输入，由分区模型折算。
- 当前不在 fstab 挂 ESP，避免 4K UFS 与 512-sector FAT 的挂载不匹配。
- DT overlay 在构建期合并，详见[设备树覆盖](../hardware/device-tree-overlays.md)。

## 两种刷写布局

**Q6A：SPI 固件 + UFS 系统。** 普通 `flange flash` 只写 UFS raw.img，
`--spi-firmware` 单独更新 SPI NOR 的 EDK2/XBL。7.0.2 必须与板卡页的 SPI 固件配套。
全新 UFS 的 `--provision-ufs` 会重建逻辑单元并清除数据，不是每次更新的步骤。

**RUBIK Pi 3：启动固件也在 UFS。** 板级声明 `bootloader.ufs_rawprogram` / `ufs_patch`；
boot 另生成 UEFI 使用的 dtb.bin，宿主暂存官方 XML、签名固件与生成的 LUN0 系统 XML，
在一次 edl-ng rawprogram 会话中写入。固件 XML 若越界写/patch LUN0，或输入仍为 Git LFS 指针，
会在等待设备前拒绝。不能套用 Q6A 的 SPI 操作。

## 平台维护

平台策略位于 `builder/platforms/qualcommqcs6490/`，数据和补丁在 `components/platform/qualcommqcs6490/`。
Q6A 与 RUBIK 的启动固件、EL、DSP 接管方式和驱动不同，不能仅因 SoC 相同互换 DTB/固件。
内核补丁包含 DWC3 clear-stall、I2C FIFO 与 DP 中断处理；适用产品以配置中的补丁选择为准。
GPU/固件、无线、音频拓扑和实际验证结果集中在板卡页。
