// Radxa Cubie A7Z 板级配置：声明固件、设备树和板载硬件策略。
// Radxa Cubie A7Z (Allwinner A733) 板级配置
local firmwareFiles = [
  'fw_patch_8800d80_u02_ext0.bin', 'fw_adid_8800d80_u02.bin',
  'fw_patch_table_8800d80_u04.bin', 'fw_patch_8800d80_u04.bin',
  'aic_userconfig_8800d80.txt', 'fw_patch_table_8800d80_u02.bin',
  'fw_patch_8800d80_u02.bin', 'fmacfw_8800d80_h_u02_ipc.bin',
  'fw_ble_scan_ad_filter.bin', 'aic_powerlimit_8800d80.txt',
  'fmacfw_8800d80_u02.bin', 'calibmode_8800d80.bin',
  'fmacfw_8800d80_u02_ipc.bin', 'fmacfw_8800d80_h_u02.bin',
  'lmacfw_rf_8800d80_u02.bin',
];
local product = std.extVar('product');

{
  board: 'radxa-cubie-a7z',
  soc: 'a733',
  platform: 'allwinnera733',
  products: ['default', 'desktop'],
  variants: ['debug', 'release'],
  packages: if product == 'desktop' then ['ubuntu-desktop'] else [],
  sources+: {
    aic8800: {
      // cubie-a7z 板级独有
      url: 'https://github.com/radxa-pkg/aic8800.git',
      commit: '7f42b22913b462ab6c658dfc075bae1dbfe9a71a',
    },
  },
  kernel+: {
    device_tree+: { name: 'sun60i-a733-cubie-a7z' },
  },
  kernel_device+: {
    board_dts_path: 'configs/cubie_a7z/linux-5.15/board.dts',
  },
  bootloader+: { target: 'radxa-cubie-a7z' },
  boot+: {
    overlays+: {
      vendor: [
        // radxa-overlays 仓库内与 A733 (sun60iw2p1) 兼容的 vendor overlay 全集。
        // 仓库 arch/arm64/boot/dts/allwinner/overlays/Makefile 用
        // CONFIG_ARCH_SUN60IW2 圈选这一组；A523 / A527 / A537 (sun55iw3p1) 那一组
        // 与本板 SoC 不兼容，故不打包。
        // SoC 级（sun60iw2p1）— 通用外设 muxing
        'sun60iw2p1-i2s0-2ch.dtbo', 'sun60iw2p1-i2s4-2ch.dtbo',
        'sun60iw2p1-pwm1-1.dtbo', 'sun60iw2p1-pwm1-2.dtbo',
        'sun60iw2p1-pwm1-3.dtbo', 'sun60iw2p1-pwm1-6.dtbo',
        'sun60iw2p1-pwm1-7.dtbo', 'sun60iw2p1-spi1-spidev.dtbo',
        'sun60iw2p1-spi3-spidev.dtbo', 'sun60iw2p1-twi2.dtbo',
        'sun60iw2p1-twi7.dtbo', 'sun60iw2p1-uart2.dtbo',
        'sun60iw2p1-uart3.dtbo', 'sun60iw2p1-uart4.dtbo',
        // 板级（cubie-a7a 命名，但同基线 SoC，依 Makefile 归到 sun60iw2p1）
        'cubie-a7a-enable-sunxi-ac101-sound-card.dtbo',
        'cubie-a7a-radxa-25w-poe.dtbo',
        'cubie-a7a-radxa-camera-8m-219.dtbo',
        'cubie-a7a-radxa-camera-13m-214.dtbo',
        'cubie-a7a-radxa-camera-4k-415.dtbo',
        'cubie-a7a-radxa-display-8hd.dtbo',
        'cubie-a7a-radxa-display-10fhd.dtbo',
        'cubie-a7z-reroute-audio-from-hdmi-to-typec-dp.dtbo',
      ],
      // 把 radxa-overlays 中与 A733 兼容的全部 overlay 打入 boot.img。
      // 板私有 overlay，源文件位于 components/board/radxa-cubie-a7z/dtso/，
      // 由 device-tree-overlay 组件复用同一 cpp+dtc 流水线编译。
      // 开机默认应用的 overlay（按声明顺序写入 extlinux fdtoverlays）；
      // 未列入此处的 overlay 仍可通过运行时编辑 /boot/extlinux/extlinux.conf
      // 启用。
      //
      // SPI1 当前绑定 ST7789V2 SPI LCD（drm/tiny `panel-mipi-dbi-spi`
      // backport，暴露 /dev/dri/card*）；如需改回 spidev1.0 用户态访问，
      // 把下面这行换成 "sun60iw2p1-spi1-spidev.dtbo"（已在 overlays.vendor
      // 中）。
      board: ['sun60iw2p1-spi1-st7789v-display.dtbo'],
      enabled: [
        'sun60iw2p1-spi1-st7789v-display.dtbo',
        'cubie-a7a-radxa-camera-13m-214.dtbo',
      ],
    },
  },
  rootfs+: {
    panel_firmware: [{
      // 账号体系沿用 components/rootfs/config.jsonnet base 层默认：root 完全
      // 锁定 + 默认用户 flange/flange。如需开放 root 在此处覆盖。
      // ST7789V2 panel-mipi-dbi-spi 的 init 序列：构建期由
      // builder.firmware_panel 把文本源编译为 mainline 兼容的 panel.bin，
      // 落 rootfs /lib/firmware/panel-mipi-dbi-spi.bin。dest 与 DTS overlay
      // 的 compatible[0] 派生的 firmware 名一致（driver 不读 firmware-name
      // DT 属性，而是用 ``<compatible[0]>.bin`` 在 /lib/firmware/ 下查找）。
      src: 'firmware/panel/st7789v2-240x280.txt',
      dest: 'panel-mipi-dbi-spi.bin',
    }],
    // AIC8800 旧 BSP firmware helper 从 aic_fw_path 直接读取扁平文件；
    // Wi-Fi fdrv 又会在同一路径下拼接 aic8800D80/ 读取用户配置。
    // 因此同一批 Radxa D80 USB 固件同时安装为扁平目录和芯片子目录。
    extra_firmware+: [
      {
        name: 'radxa-aic8800',
        source: { name: 'aic8800', subpath: 'src/USB/driver_fw/fw/aic8800D80' },
        files: firmwareFiles,
        dest: 'lib/firmware/aic8800_fw/USB',
      },
      {
        name: 'radxa-aic8800',
        source: { name: 'aic8800', subpath: 'src/USB/driver_fw/fw' },
        files: ['aic8800D80/' + path for path in firmwareFiles],
        dest: 'lib/firmware/aic8800_fw/USB',
      },
    ],
  },
}
