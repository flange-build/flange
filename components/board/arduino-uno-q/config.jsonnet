// Arduino UNO Q 板级配置：两种内存容量共用板支持，完整运行时由功能包提供。
local variant = std.extVar('variant');
{
  board: 'arduino-uno-q',
  platform: 'qualcommqrb2210',
  soc: 'qrb2210',
  products: ['default'],
  variants: ['debug', 'release'],
  packages: ['arduino-unoq-runtime'],
  storage: { type: 'emmc' },
  kernel+: {
    // 最终 DTB 由官方内核合并 base 与 USB-C 音视频 overlay，不能仅使用 base。
    device_tree+: { name: 'qrb2210-arduino-imola' },
    defconfig: ['defconfig', 'arduino.config', 'docker.config', 'panel.config',
                'systemd-boot.config', 'usb-can.config'],
    config: {
      CONFIG_EFI: 'y',
      CONFIG_EFI_STUB: 'y',
      CONFIG_BLK_DEV_INITRD: 'y',
      CONFIG_RD_GZIP: 'y',
      CONFIG_RD_ZSTD: 'y',
      CONFIG_EXT4_FS: 'y',
      CONFIG_MMC_SDHCI_MSM: 'y',
      CONFIG_FW_LOADER_COMPRESS: 'y',
      CONFIG_FW_LOADER_COMPRESS_ZSTD: 'y',
      CONFIG_GPIO_CDEV: 'y',
      CONFIG_USB_CONFIGFS: 'y',
      CONFIG_USB_CONFIGFS_F_FS: 'y',
      CONFIG_USB_F_FS: 'y',
      // 自有内核与模块统一构建，不强制未配置的模块签名密钥。
      CONFIG_MODULE_SIG_FORCE: 'n',
      CONFIG_LOCALVERSION: '"-flange-unoq"',
      CONFIG_LOCALVERSION_AUTO: 'n',
      // debug 保留 DWARF（调试信息）；release 不携带内核调试符号，驱动集合相同。
      CONFIG_DEBUG_INFO_NONE: if variant == 'release' then 'y' else 'n',
      CONFIG_DEBUG_INFO_DWARF_TOOLCHAIN_DEFAULT: if variant == 'debug' then 'y' else 'n',
    },
  },
  bootloader+: {
    device_tree: 'qcom/qrb2210-arduino-imola',
    recovery_firmware: {
      url: 'https://downloads.arduino.cc/debian-im/unoq-bootloader-emmc-linux-251020.zip',
      sha256: 'c606e95d0107f8c58d0dd9494e00624d1db7c4361cca20513bc78ef02ca28dd1',
      filename: 'unoq-bootloader-emmc-linux-251020.zip',
    },
    firehose_loader: 'prog_firehose_ddr.elf',
  },
  boot: {
    kernel_args: 'earlycon console=ttyMSM0,115200n8 root=PARTLABEL=rootfs rootwait rw',
    overlays: { intree: [], vendor: [], board: [], package: [], enabled: [] },
  },
  rootfs+: {
    default_user: 'arduino',
    // release 不传 password，让 useradd 保持账户口令锁定；空字符串会被 chpasswd 拒绝。
    users: { arduino: { shell: '/bin/bash', sudo: true }
             + (if variant == 'debug' then { password: 'arduino' } else {}) },
    image_format: 'ext4',
  },
  // 仅描述系统组件尺寸；完整高通 GPT/XML 由官方救援包保留并由 QDL 策略校验。
  // 512 字节扇区；这里只保留救援包的构建模板基线。
  // 32 GB 官方布局的 rootfs 可能更大，宿主必须按实板 GPT 定位，不移动已有 userdata。
  partitions: {
    format: 'gpt', sector_size: 512,
    entries: [
      { name: 'efi', offset: '985408', size: '512M', type: 'fat32', label: 'efi' },
      { name: 'rootfs', offset: '2033984', size: '20920568', type: 'ext4',
        label: 'rootfs', image_size: '9G' },
      { name: 'userdata', offset: '22954552', size: 'remaining', type: 'ext4',
        // 3 GiB 初始镜像兼容约 3.6 GiB 用户分区；刷前仍按实际 GPT 严格核验。
        label: 'userdata', image_size: '3G' },
    ],
  },
}
