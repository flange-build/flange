// Qualcomm SC8280XP SoC 层配置：声明芯片级源码、Kconfig、设备树和固件能力。
// Qualcomm SC8280XP SoC 配置。
{
  platform: 'qualcommsc8280xp',
  soc: 'sc8280xp',
  vendor: 'qcom',
  sources+: {
    'linux-sc8280xp': {
      url: 'https://github.com/radxa/kernel.git',
      branch: 'linux-7.0.11',
      recurse_submodules: false,
    },
  },
  kernel+: {
    source: { name: 'linux-sc8280xp' },
    defconfig: ['radxa_qcom_7_0_defconfig'],
    // Q8B 只使用 Adreno/MSM 显示和 QPS615/TC956x 板载网卡。通过 flange
    // 额外 config 覆盖裁掉发行版 defconfig 中的离线调试信息、独显与
    // 无关 PCIe 网卡；USB 网卡和 M.2 E-Key Wi-Fi 驱动保持可用。
    config: {
      // flange 当前不生成 initramfs，让显示驱动在 rootfs 可用后加载固件。
      CONFIG_DRM_MSM: 'm',
      CONFIG_SCSI_UFSHCD: 'y',
      CONFIG_SCSI_UFSHCD_PLATFORM: 'y',
      CONFIG_SCSI_UFS_QCOM: 'y',
      CONFIG_PHY_QCOM_QMP: 'y',
      CONFIG_INTERCONNECT_QCOM_SC8280XP: 'y',
      CONFIG_FW_LOADER_COMPRESS: 'y',
      CONFIG_FW_LOADER_COMPRESS_ZSTD: 'y',
      CONFIG_DEBUG_INFO_NONE: 'y',
      CONFIG_ANDROID_BINDER_IPC: 'y',
      CONFIG_ANDROID_BINDERFS: 'y',
      CONFIG_DEBUG_INFO_DWARF5: 'n',
      CONFIG_DRM_AMDGPU: 'n',
      CONFIG_DRM_NOUVEAU: 'n',
      CONFIG_NET_VENDOR_CHELSIO: 'n',
      CONFIG_NET_VENDOR_I825XX: 'n',
      CONFIG_NET_VENDOR_INTEL: 'n',
      CONFIG_NET_VENDOR_MELLANOX: 'n',
      CONFIG_NET_VENDOR_MUCSE: 'n',
    },
    device_tree+: { directory: 'qcom' },
  },
  boot+: {
    overlays: {
      intree: [], vendor: [], board: [], package: [], enabled: [],
    },
    kernel_args: 'earlycon console=ttyMSM0,115200 acpi=off panic=10 root=PARTLABEL=rootfs rootwait',
  },
}
