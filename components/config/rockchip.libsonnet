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
  multimediaDebs: [
    {
      name: 'rockchip-mpp',
      url: 'https://github.com/CmST0us/rockchip-multimedia-ubuntu/releases/download/1.0.0/rockchip-mpp_1.3.9_arm64.deb',
      sha256: 'f1bc1826e054821bf268eb6fb31958695909f35807e25445dced1b6e4fc2a9e2',
    },
    {
      name: 'rockchip-mpp-dev',
      url: 'https://github.com/CmST0us/rockchip-multimedia-ubuntu/releases/download/1.0.0/rockchip-mpp-dev_1.3.9_arm64.deb',
      sha256: 'fcaa62bb7d35b028ea01b904e9c928c222d89bdf5b0eacc448e0d043215ec7fd',
    },
    {
      name: 'librga2',
      url: 'https://github.com/CmST0us/rockchip-multimedia-ubuntu/releases/download/1.0.0/librga2_2.1.0_arm64.deb',
      sha256: 'ec2343f42a323bf518c1bb4f36dbfd94349fad24a3e1a9c620e47aedd6ee2b54',
    },
    {
      name: 'librga-dev',
      url: 'https://github.com/CmST0us/rockchip-multimedia-ubuntu/releases/download/1.0.0/librga-dev_2.1.0_arm64.deb',
      sha256: 'ac6530b803e3606394006a93d60998846ca318c65df2ec57bd3b6e68ad2b73d4',
    },
    {
      name: 'libgstreamer1.0-0',
      url: 'https://github.com/CmST0us/rockchip-multimedia-ubuntu/releases/download/1.0.0/libgstreamer1.0-0_1.24.2_arm64.deb',
      sha256: '23cd246e5c5472936c596d314ca8e9e887cd323a586c22b90224467198262e69',
    },
    {
      name: 'gstreamer1.0-plugins-base',
      url: 'https://github.com/CmST0us/rockchip-multimedia-ubuntu/releases/download/1.0.0/gstreamer1.0-plugins-base_1.24.2_arm64.deb',
      sha256: 'c736643550e5b9922c5020281d96e39cfee82b42de996484f330e10c2e5fe409',
    },
    {
      name: 'gstreamer1.0-plugins-good',
      url: 'https://github.com/CmST0us/rockchip-multimedia-ubuntu/releases/download/1.0.0/gstreamer1.0-plugins-good_1.24.2_arm64.deb',
      sha256: '5324e07b23a90510024454b96eb98e6c64c76c85e54e15d6a2c9077c2239033b',
    },
    {
      name: 'gstreamer1.0-plugins-bad',
      url: 'https://github.com/CmST0us/rockchip-multimedia-ubuntu/releases/download/1.0.0/gstreamer1.0-plugins-bad_1.24.2_arm64.deb',
      sha256: '6854bb699b4bb7fcc4fe23e51306c6c57c2e69dea3aaa9776cba537f6d46c3c2',
    },
    {
      name: 'gstreamer1.0-rockchip',
      url: 'https://github.com/CmST0us/rockchip-multimedia-ubuntu/releases/download/1.0.0/gstreamer1.0-rockchip_1.0-1_arm64.deb',
      sha256: '4e8a6fdb195d3acd7b16c59c81b3b9a263d16324753fba4f700b2217d5139c32',
    },
  ],
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
