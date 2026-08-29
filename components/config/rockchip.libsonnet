// Rockchip 共享配置数据：集中定义通用分区、下载项和外设描述。
{
  partitions: {
    format: 'gpt',
    sector_size: 512,
    entries: [
      { name: 'idbloader', offset: '0x40', size: '0x2000', type: 'raw' },
      { name: 'uboot', offset: '0x4000', size: '0x2000', type: 'raw' },
      { name: 'boot', offset: '0x8000', size: '0x20000', type: 'ext4' },
      { name: 'recovery', offset: '0x28000', size: '0x100000', type: 'ext4' },
      {
        name: 'rootfs', offset: '0x128000', size: 'remaining', type: 'ext4',
        image_size: '2G', grow_on_first_boot: true,
      },
    ],
  },
  ampPartitions: {
    format: 'gpt',
    sector_size: 512,
    entries: [
      { name: 'idbloader', offset: '0x40', size: '0x2000', type: 'raw' },
      { name: 'uboot', offset: '0x4000', size: '0x2000', type: 'raw' },
      { name: 'boot', offset: '0x8000', size: '0x20000', type: 'ext4' },
      { name: 'recovery', offset: '0x28000', size: '0x100000', type: 'ext4' },
      { name: 'amp', offset: '0x128000', size: '0x8000', type: 'ext4' },
      {
        name: 'rootfs', offset: '0x130000', size: 'remaining', type: 'ext4',
        image_size: '2G', grow_on_first_boot: true,
      },
    ],
  },
  // RTL8852BE 使用 rkwifibt vendor OOT 驱动：M 指向实际模块目录，Makefile 的
  // CONFIG_RTL8852B=y + CONFIG_PCI_HCI=y 生成 8852be.ko。显式关闭
  // CONFIG_RTW_DEBUG，避免 PHL/RTW 的扫描与连接 INFO 日志持续淹没串口；
  // 命令行赋值优先于 Makefile 内默认值，关闭后相关日志宏在编译期退化为 no-op。
  rtl8852beModule: {
    dir: '{rkwifibt_src}/drivers/rtl8852be',
    label: 'rtl8852be (rkwifibt vendor driver)',
    make_args: [
      'ARCH=arm64', 'CROSS_COMPILE=aarch64-linux-gnu-',
      'KSRC={kernel_src}', 'M={rkwifibt_src}/drivers/rtl8852be',
      'CONFIG_RTW_DEBUG=n',
    ],
    ko_pattern: ['{rkwifibt_src}/drivers/rtl8852be/8852be.ko'],
  },
  // BT blob 沿用 rtl8852bu 历史文件名，但内容供 PCIe RTL8852BE 共用；安装时
  // 补 .bin 后缀以匹配 in-tree btusb-rtl 的固件加载路径。
  rtl8852beFirmware: {
    name: 'rkwifibt-rtl8852be',
    source: { name: 'rkwifibt', subpath: 'firmware/realtek/RTL8852BE' },
    files: [
      { src: 'rtl8852bu_fw', dest: 'rtl8852bu_fw.bin' },
      { src: 'rtl8852bu_config', dest: 'rtl8852bu_config.bin' },
    ],
    dest: 'lib/firmware/rtl_bt',
  },
}
