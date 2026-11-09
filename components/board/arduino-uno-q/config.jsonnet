// Arduino UNO Q 板级配置：两种内存容量共用板支持，完整运行时由功能包提供。
//
// waveshare-display-10.1a：UNO Q 插在 Waveshare UNO-Q-DSI-TOUCH-10.1A（Arduino
// media carrier 兼容载板，经 JMEDIA/JMISC 板对板连接）上，800×1280 DSI 屏 +
// Goodix 触摸 + 4 组 RGB LED。对应官方
// `arduino-linux-config carrier enable media-carrier display=10-dsi-touch-a`，
// 这里改为构建期合并内核自带 overlay。DSI0 只能接一路：默认 DTB 已把 DSI0 接到
// USB-C 的 anx7625，与屏冲突，因此本 product 以 base DTB 为底，不含 USB-C 视频输出。
// 摄像头接口未启用（官方 camera0/1=none）。显示默认顺时针旋转 90°（横屏 1280×800）：
// 板私有 dtso 修正 Goodix 坐标范围并在内核旋转触摸，overlay/ 下的 LightDM
// display-setup 脚本检测到该面板时用 xrandr 旋转 DSI-1，两者须同向修改。
local variant = std.extVar('variant');
local product = std.extVar('product');
local ws101a = product == 'waveshare-display-10.1a';
// 顺序不可对调：两个 overlay 都 include carrier-media-common.dtsi，各带一份
// pca9555 节点，后合并者的 phandle 覆盖前者。carrier-media 必须最后合并，让 LED 与
// 摄像头供电对 pca9555 的引用随其一并重写；反之 LED 引用悬空，leds-gpio 整组
// （含 UNO Q 板载 LED）probe 失败。
local ws101aOverlays = [
  'qrb2210-arduino-imola-carrier-media-panel-10in_touch_a-dsi.dtbo',
  'qrb2210-arduino-imola-carrier-media.dtbo',
];
local ws101aTouchOverlay = 'qrb2210-arduino-uno-q-waveshare-10.1a-touch.dtbo';
{
  board: 'arduino-uno-q',
  platform: 'qualcommqrb2210',
  soc: 'qrb2210',
  products: ['default', 'waveshare-display-10.1a'],
  variants: ['debug', 'release'],
  packages: ['arduino-unoq-runtime'],
  storage: { type: 'emmc' },
  kernel+: {
    // 默认 DTB 由官方内核合并 base 与 USB-C 音视频 overlay，不能仅使用 base；
    // 接屏 product 以 base 为底，构建期合并 media carrier 与面板 overlay。
    device_tree+: if ws101a then {
      name: 'qrb2210-arduino-imola-base',
      // 触摸修正以路径定位 panel overlay 新增的 goodix 节点，必须最后合并。
      build_overlays: ws101aOverlays + [ws101aTouchOverlay],
    } else { name: 'qrb2210-arduino-imola' },
    defconfig: ['defconfig', 'arduino.config', 'docker.config', 'panel.config',
                'systemd-boot.config', 'usb-can.config'],
    config+: {
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
    overlays: { intree: if ws101a then ws101aOverlays else [],
                vendor: [], board: if ws101a then [ws101aTouchOverlay] else [],
                package: [], enabled: [] },
  },
  rootfs+: {
    default_user: 'arduino',
    // release 与官方镜像一致：不预设口令，构建期置为空口令且立即过期，由 App Lab 首次连接时
    // 引导设置（见 qualcommqrb2210 rootfs 的 _post_customize）。debug 保留研发用默认口令。
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
