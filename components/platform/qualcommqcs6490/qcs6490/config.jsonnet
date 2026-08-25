// Qualcomm QCS6490 SoC 层配置：声明芯片级源码、Kconfig、设备树和固件能力。
//
// 启动模型（实证自 Radxa rsdk / Armbian / 本地 flat_build 固件包）：
//   SPI NOR: XBL → EDK2 UEFI(PILFv) + VarStore（Radxa 预编 blob，flange 不编）
//   系统盘 : GPT(4K) → ESP(FAT, GRUB EFI + kernel/dtb/initrd) → rootfs(ext4)
//            UEFI → GRUB(grub-with-dtb, acpi=off) → kernel(DeviceTree) → rootfs
//   内核   : radxa/kernel@linux-7.0.2（Radxa linux-qcom 官方包同款）
//            + arm64 通用 defconfig + qcom/radxa 配置片段
//            + kernel.config 中的 UFS/QMP-PHY/USB gadget builtin 与 drm/msm
//   GPU    : 开源 Mesa freedreno/turnip（Adreno 643/a6xx）+ a660_zap/a660_sqe 固件
//
// kernel 基线（migrate-qcs6490-kernel-702）：
//   从 mainline linux-6.18.2 升至 linux-7.0.2，与 Radxa linux-qcom 官方包对齐。
//   config 策略为 defconfig + qcom_module.config + radxa.config +
//   radxa_custom.config；后两者分别由 0004 / 0005 patch 注入内核树。
//   flange 特定 symbol 通过 kernel.config 在这些 fragment 后统一覆盖。
//
//   DTS 变化（6.18.2 → 7.0.2）：
//     #include "sc7280.dtsi" → #include "kodiak.dtsi"（功能等价）
//     video_mem 区域 5MB（venus vpu20_p1.mbn 约 2MB，远低于限制）
//     现有 0002/0003 DTS patch 在 7.0.2 上 dry-run 验证通过（offset +8/+1 行）
//     0001 DWC3 patch 针对 7.0.2 行号重写（逻辑不变）
{
  platform: 'qualcommqcs6490',
  soc: 'qcs6490',
  // 主线设备树路径为 arch/arm64/boot/dts/qcom/。
  vendor: 'qcom',
  sources+: {
    'linux-qcs6490': {
      url: 'https://github.com/radxa/kernel.git',
      // mainline 7.0.2，使用 Radxa linux-qcom 官方包同款分支。
      branch: 'linux-7.0.2',
      // 固定到生产在用的已验证 commit。分支 tip 6445af0c5 在本板 UFS probe
      // 早期触发 QHEE PSHOLD 整机复位；pin 可排除该回归。
      commit: '7473a9fca2b08623319e497f4f811746baddb7bc',
      recurse_submodules: false,
    },
  },
  kernel+: {
    // 内核源位于 source checkout 根目录，无 subpath。
    source: { name: 'linux-qcs6490' },
    // 对齐 radxa rsdk/linux-qcom 的 .github/local/Makefile.local：
    //   defconfig → qcom_module.config → radxa.config → radxa_custom.config
    // qcom_module.config 提供 UFS/PHY/SCSI_UFS_CRYPTO/QSEECOM/AOSS_QMP/LLCC/
    // ICC_BWMON/SMMU_V3/QCOM_IOMMU/PDC/MPM/RPMHPD 等 Qualcomm 平台驱动；
    // 遗漏它会让 UFS probe 早期撞 QHEE PSHOLD 整机复位。
    defconfig: [
      'defconfig', 'qcom_module.config', 'radxa.config',
      'radxa_custom.config',
    ],
    config: {
      // 无 initramfs 且 rootfs 位于 UFS，HCD/controller 与 QMP PHY 必须 builtin。
      CONFIG_SCSI_UFSHCD: 'y',
      CONFIG_SCSI_UFSHCD_PLATFORM: 'y',
      CONFIG_SCSI_UFS_QCOM: 'y',
      CONFIG_PHY_QCOM_QMP: 'y',
      CONFIG_PHY_QCOM_QMP_UFS: 'y',
      // 7.0.2 UFS DTS 新增 interconnects；若该驱动为 module，会形成
      // “加载 module 需要 rootfs、挂载 rootfs 又需要 UFS”的循环依赖。
      CONFIG_INTERCONNECT_QCOM_SC7280: 'y',
      // Qualcomm 固件普遍为 .zst，必须在加载 venus/GPU/QUP 固件前支持解压。
      CONFIG_FW_LOADER_COMPRESS: 'y',
      CONFIG_FW_LOADER_COMPRESS_ZSTD: 'y',
      // USB gadget 栈 builtin，配合 DWC3 DTS patch 消除 ADB 启动时的 modprobe 竞态。
      CONFIG_USB_LIBCOMPOSITE: 'y',
      CONFIG_USB_CONFIGFS: 'y',
      CONFIG_USB_F_FS: 'y',
      // GUD（Generic USB Display）host 侧 DRM 驱动，使 USB display 作为 DRM 设备。
      CONFIG_DRM_GUD: 'y',
      // OOT 模块由 flange 直接安装且不签名，SIG_FORCE 会导致 modprobe 拒绝加载。
      CONFIG_MODULE_SIG_FORCE: 'n',
      // 未覆盖 VIDEO_QCOM_VENUS：实板验证 iris 虽能绑定并解码，但硬件编码仍因
      // 固件/TZ-CP 契约触发整机复位，换驱动无解，因此保持 rsdk 的 venus 路线。
    },
    // SoC 只声明设备树目录，具体 Q6A 设备树名称由 board overlay 选择。
    device_tree+: { directory: 'qcom' },
  },
  boot+: {
    // GRUB(grub-with-dtb) 从 ESP 加载单 DTB；UEFI 同时提供 ACPI，必须 acpi=off
    // 强制 DeviceTree 路线。
    overlays: {
      intree: [],
      vendor: [],
      board: [],
      package: [],
      enabled: [],
    },
    // earlycon 在驱动加载前保留 panic；ttyMSM0 是 GENI UART0；panic=10 给串口
    // 留出刷日志时间。无 initramfs 时内核不能解析 filesystem LABEL，rootfs
    // 必须使用 PARTLABEL/PARTUUID/设备路径定位。
    kernel_args: 'earlycon console=ttyMSM0,115200 acpi=off panic=10 root=PARTLABEL=rootfs rootwait',
  },
  partitions: {
    format: 'gpt',
    // UFS 物理扇区为 4096；offset/size 仍统一按 512 字节扇区计，image builder
    // 会按实际介质 sector_size 折算，4K 介质上的偏移自动除以 8。
    sector_size: 4096,
    // GPT 只保留 ESP + rootfs：ESP 从 1 MiB 起、大小 256 MiB；rootfs 紧随其后，
    // 初始镜像 3G，并在首启扩展到 UFS 剩余空间。
    entries: [
      { name: 'esp', offset: '0x800', size: '0x80000', type: 'fat32', label: 'efi' },
      {
        name: 'rootfs',
        offset: '0x80800',
        size: 'remaining',
        type: 'ext4',
        label: 'rootfs',
        image_size: '3G',
        grow_on_first_boot: true,
      },
    ],
  },
}
