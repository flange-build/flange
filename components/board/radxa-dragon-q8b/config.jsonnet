// Radxa Dragon Q8B 板级配置：声明设备树、产品变体和板载硬件策略。
// Radxa Dragon Q8B（Qualcomm SC8280XP）板级配置。
local product = std.extVar('product');

{
  board: 'radxa-dragon-q8b',
  soc: 'sc8280xp',
  platform: 'qualcommsc8280xp',
  products: ['default', 'desktop'],
  variants: ['debug', 'release'],
  packages: (if product == 'desktop' then ['ubuntu-desktop'] else []) + [
    'firmware-qcom-audioreach',
    'radxa-firmware-sc8280xp',
    'radxa-q8b-fastrpc',
  ],
  sources+: {
    'radxa-firmware-sc8280xp': {
      url: 'https://github.com/radxa-pkg/radxa-firmware.git',
      commit: 'e1761009df008adfd62c77f2c5584e3067449013',
    },
  },
  kernel+: {
    device_tree+: { name: 'sc8280xp-radxa-dragon-q8b' },
  },
  rootfs+: {
    groups+: ['fastrpc'],
    packages+: ['acl', 'libbsd0', 'libyaml-0-2', 'udev'] + [
      // Iris 硬件编解码验证工具：gst-launch-1.0、h264parse/h265parse、v4l2-ctl
      'gstreamer1.0-tools', 'gstreamer1.0-plugins-bad', 'v4l-utils',
    ],
    extra_firmware+: [{
      name: 'radxa-firmware-sc8280xp',
      source: {
        name: 'radxa-firmware-sc8280xp',
        subpath: 'radxa-firmware-sc8280xp/lib/firmware',
      },
      files: [
        'qcom/sc8280xp/qccdsp8280.mbn',
        'qcom/sc8280xp/qcslpi8280.mbn',
        'qcom/sc8280xp/qcvss8280.mbn',
        'qcom/sc8280xp/qupv3fw.elf',
        'qcom/sc8280xp/radxa/dragon-q8b/qcadsp8280.mbn',
        'qcom/vpu/vpu20_p4_gen2_s6.mbn',
        {
          src: 'qcom/sc8280xp/qcdxkmsuc8280.mbn',
          dest: 'qcom/sc8280xp/LENOVO/21BX/qcdxkmsuc8280.mbn',
        },
      ],
      dest: 'lib/firmware',
    }],
    extra_debs+: [{
      name: 'alsa-ucm-conf-radxa-q8b',
      url: 'https://github.com/radxa-pkg/alsa-ucm-conf/releases/download/1.2.16.1-radxa-1/alsa-ucm-conf_1.2.16.1-radxa-1_all.deb',
      sha256: 'e98278426a43fac2b99f72d299032c2904b62886c3a6fb1f745f5ad0c3bc62e8',
      filename: 'alsa-ucm-conf_1.2.16.1-radxa-1_all.deb',
    }],
  },
  bootloader: {
    edk2_firmware: {
      url: 'https://dl.radxa.com/dragon/q8b/images/dragon-q8b_flat_build_wp_260731.zip',
      sha256: 'f9bd55ac342bad53f056f620bdbf6e090ab1ef80c99cbf90ed685a64d7980fb8',
    },
    firehose_loader: 'prog_firehose_ddr.elf',
    spi_rawprogram: 'rawprogram0.xml',
    spi_patch: 'patch0.xml',
    ufs_firehose: {
      url: 'https://raw.githubusercontent.com/armbian/qcombin/f2d55c46dcbe2af57dc400658cd14e70cd8baa79/Makena/prog_firehose_ddr.elf',
      sha256: '2922271fb6d0792d737fb757e7783513b2e7ca54eacb219e80e58ba233dcbaf2',
      filename: 'prog_firehose_ufs.elf',
    },
    ufs_provisions: {
      'lun0-only': {
        url: 'https://raw.githubusercontent.com/armbian/qcombin/f2d55c46dcbe2af57dc400658cd14e70cd8baa79/Makena/radxa-dragon-q8b/provision_ufs31_lun0_only.xml',
        sha256: '54709fd22904972066ab3bbae58e65da9cda404fdfdacac2cae83feca98ac5c8',
        filename: 'provision_ufs31_lun0_only.xml',
      },
      qcom: {
        url: 'https://dl.radxa.com/q6a/images/android/provision_ufs31.xml',
        sha256: '2eca74731049bfb399ec88bdbb830b5163910c471902d15dc3bfa6e9c1889c3e',
        filename: 'provision_ufs31.xml',
      },
    },
  },
  partitions: {
    format: 'gpt',
    sector_size: 4096,
    entries: [
      { name: 'esp', offset: '0x800', size: '0x80000', type: 'fat32', label: 'efi' },
      {
        name: 'rootfs', offset: '0x80800', size: 'remaining', type: 'ext4',
        label: 'rootfs', image_size: '3G', grow_on_first_boot: true,
      },
    ],
  },
}
