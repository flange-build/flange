// Qualcomm QCS6490 平台层配置：声明共享架构、构建能力和变体策略。
// Qualcomm QCS6490 (qualcommqcs6490) 平台配置 -- platform overlay
//
// flange 首个 Qualcomm 平台。与 RK/AW/Amlogic（U-Boot 世界）根本不同：
// 启动链 PBL→XBL→EDK2 UEFI→GRUB→OS，刷写走 EDL 模式 + edl-ng，boot 固件是
// Radxa 预编签名 blob（flange 不编）。详见 design.md。
local variant = std.extVar('variant');

{
  platform: 'qualcommqcs6490',
  vendor: 'qualcommqcs6490',
  architecture+: {
    userspace: 'aarch64',
    kernel: 'arm64',
    bootloader: 'arm64',
  },
  products: ['default'],
  variants: ['debug', 'release'],
  // 刷写工具：Qualcomm EDL（edl-ng）。详见 QualcommFlashStrategy。
  flash_tool: 'edl-ng',
  rootfs+: {
    // adbd 便于 USB 调试；flange-rootfs-grow 首启扩容 rootfs。
    custom_packages: ['adbd', 'flange-rootfs-grow'],
    // Q6A 只支持 Ubuntu noble，与平台无关的 Ubuntu Base URL/SHA256 从 rootfs
    // 基线继承；这里追加 Mesa freedreno/turnip、Qualcomm 固件和无线用户态。
    packages: [
      // freedreno GL/GLES
      'libgl1-mesa-dri',
      'libegl-mesa0',
      'libgbm1',
      // turnip Vulkan
      'mesa-vulkan-drivers',
      // 含 qcom a660_zap/a660_sqe 等 GPU/DSP 固件
      'linux-firmware',
      // QCS6490 固件 updates/（ADSP/CDSP/GPU 更新）
      'linux-firmware-dragonwing',
      // 音频 UCM
      'alsa-ucm-conf',
      // cfg80211 regulatory.db 与 WiFi STA 工具
      'wireless-regdb',
      'iw',
      'wpasupplicant',
    ] + (if variant == 'debug' then [
      // eglinfo / glxinfo / es2_info
      'mesa-utils',
      // vulkaninfo
      'vulkan-tools',
    ] else []),
    // Qualcomm IoT PPA 提供 linux-firmware-dragonwing。固件落在
    // /lib/firmware/updates/qcom/qcs6490/，内核优先于 linux-firmware 加载；
    // signing key fingerprint: 33EF0ACBC6FE252590ABBAF21C70EB0C444248D7。
    extra_apt_sources: [{
      name: 'qcom-ppa',
      key: {
        url: 'https://keyserver.ubuntu.com/pks/lookup?op=get&search=0x33EF0ACBC6FE252590ABBAF21C70EB0C444248D7',
        sha256: 'd7ecf3de0b7c49fadcdbe9ad5aa6b870984b4ee933147c6ef936e97421e57a59',
        filename: 'qcom-ppa.asc',
      },
      source: 'deb [arch=arm64 signed-by=/etc/apt/keyrings/qcom-ppa.gpg] https://ppa.launchpadcontent.net/ubuntu-qcom-iot/qcom-ppa/ubuntu noble main',
    }],
  },
  // Recovery 子系统：v1 不启用（Qualcomm 走 EDL 紧急下载，而非 adb-recovery
  // 模型）。recovery.py 先 stub；后续如需再开。关闭则 partitions 无需 recovery 分区。
  recovery: { enabled: false },
}
