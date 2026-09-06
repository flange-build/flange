// Khadas VIM3 系列共享配置：集中定义两板相同的 AP6398S、内核与 eMMC 策略。
{
  products: ['default', 'desktop'],
  variants: ['debug', 'release'],

  sources: {
    'khadas-fenix-ap6398s': {
      // VIM3/VIM3L 均使用 AP6398S（BCM4359）；Khadas fenix 提供板级
      // RF 调校后的 Wi-Fi firmware、NVRAM 与 BT patchram。
      url: 'https://github.com/khadas/fenix.git',
      branch: 'master',
    },
  },

  kernelConfig: {
    // TUN 供 VPN 等用户态程序创建 /dev/net/tun；Binder 供 Android
    // 兼容负载使用。公共 renderer 会把这些值写入最终 override fragment。
    CONFIG_NET: 'y',
    CONFIG_TUN: 'y',
    CONFIG_ANDROID_BINDER_IPC: 'y',
    CONFIG_ANDROID_BINDERFS: 'y',
  },

  recovery: { enabled: false },

  // 两板共用 sd_emmc_c=eMMC 拓扑。bootloader raw entry 只进入
  // flash-config，不写入 user-area GPT；fastboot 将它路由到 mmc2 boot0。
  partitions: {
    format: 'gpt',
    sector_size: 512,
    entries: [
      { name: 'bootloader', offset: '0', size: '0x1000', type: 'raw' },
      { name: 'boot', offset: '0x40', size: '0x20000', type: 'ext4' },
      {
        name: 'rootfs', offset: '0x20040', size: 'remaining', type: 'ext4',
        image_size: '2G', grow_on_first_boot: true,
      },
    ],
  },

  rootfsPackages: ['bluez'],
  extraFirmware: [{
    name: 'khadas-fenix-ap6398s',
    source: {
      name: 'khadas-fenix-ap6398s',
      subpath: 'archives/hwpacks/wlan-firmware/brcm',
    },
    files: [
      {
        src: 'brcmfmac4359-sdio_ap6398s.bin',
        dest: 'brcmfmac4359-sdio.bin',
      },
      {
        src: 'brcmfmac4359-sdio_ap6398s.txt',
        dest: 'brcmfmac4359-sdio.txt',
      },
      { src: 'BCM4359C0_ap6398s.hcd', dest: 'BCM4359C0.hcd' },
    ],
    dest: 'lib/firmware/brcm',
  }],
}
