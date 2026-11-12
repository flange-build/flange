// Luckfox Pico Pro / Max 板级配置：RV1106G2(128MB) / RV1106G3(256MB) 共用同一板型。
//
// 硬件事实来自 Luckfox 官方 SDK（BoardConfig-SPI_NAND-Buildroot-RV1106_Luckfox_
// Pico_Pro_Max-IPC.mk 与 rv1106g-luckfox-pico-pro-max.dts）。官方 SDK 的 oem /
// userdata 应用分区不保留，剩余空间整体作为 UBI rootfs。
//
// 默认 product 是最小 Ubuntu armhf，只用于在没有外部发行版层时独立验证 BSP；
// 资源受限的产品形态由 Alpine 等外部发行版层在本板上追加 product。
{
  board: 'luckfox-pico-pro-max',
  soc: 'rv1106',
  platform: 'rockchip',
  products: ['default'],
  variants: ['debug', 'release'],
  storage: { type: 'spinand', size: '256M' },
  flash_identity+: {
    storage_patterns: ['\\b(?:spi[ -]?nand|snand)\\b'],
    require_rid: false,
  },
  kernel+: {
    // 设备端编译内核模块需要整套 gcc 工具链，256MB NAND 放不下。
    headers_package: false,
    device_tree+: { name: 'rv1106g-luckfox-pico-pro-max' },
    config+: {
      // SPI NAND 的页就绪轮询需要微秒级休眠；HZ=100 下缺少高精度定时器
      // 会把每页等待放大到约 10ms，拖慢 UBI 扫描和全部冷读。
      CONFIG_HIGH_RES_TIMERS: 'y',
      // rv1106_defconfig 不含 LED 子系统；板载工作灯用 heartbeat 指示内核运行。
      CONFIG_NEW_LEDS: 'y',
      CONFIG_LEDS_CLASS: 'y',
      CONFIG_LEDS_GPIO: 'y',
      CONFIG_LEDS_TRIGGERS: 'y',
      CONFIG_LEDS_TRIGGER_HEARTBEAT: 'y',
    },
  },
  recovery+: { enabled: false },
  // GPT 偏移沿用 rk3506b 已实机验证的 SPI NAND 布局（单位 512B sector）；
  // rootfs 取到容量末端前 1 MiB（0x7F800），见 rockchip validate_storage。
  partitions: {
    format: 'gpt',
    sector_size: 512,
    entries: [
      { name: 'idbloader', offset: '0x40', size: '0x2000', type: 'raw' },
      { name: 'uboot', offset: '0x4000', size: '0x2000', type: 'raw' },
      { name: 'boot', offset: '0x8000', size: '0x8000', type: 'ext4' },
      { name: 'rootfs', offset: '0x10000', size: '223M', type: 'ext4' },
    ],
  },
  rootfs+: {
    image_format: 'ubi',
    // 2Gbit SPI NAND 典型几何：2 KiB page、128 KiB PEB、无 subpage。
    // TODO(实机)：以 U-Boot `mtd info` 或芯片丝印核实后去掉本注释。
    ubi: {
      min_io_size: 2048,
      peb_size: 131072,
      subpage_size: 2048,
      vid_hdr_offset: 2048,
      leb_size: 126976,
      // 整片 256MB / 128KiB。
      max_leb_count: 2048,
      // Rockchip 刷写器不跳过全 0xFF page，需 mkfs.ubifs -F。
      space_fixup: true,
      // rootfs 分区 223MiB = 1784 PEB；预留 40 PEB 坏块（MTD_UBI_BEB_LIMIT=20/1024），
      // 再扣 4 PEB UBI 内部卷，余 1740 LEB × 126976B。
      volume_size: '220938240B',
      reserved_pebs: 40,
      // GPT 顺序 idbloader/uboot/boot/rootfs → mtd3，须与 DTS ubi.mtd=3 一致。
      mtd_index: 3,
    },
  },
}
