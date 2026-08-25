// Amlogic 平台层配置：声明共享架构、构建能力和公共源码。
// Amlogic 平台配置 -- platform overlay
{
  platform: 'amlogic',
  vendor: 'amlogic',
  architecture+: {
    userspace: 'aarch64',
    kernel: 'arm64',
    bootloader: 'arm',
  },
  products: ['default'],
  variants: ['debug', 'release'],
  // host 端 flash 主流程通过 fastboot；pre_flash 阶段调 pyamlboot 把 u-boot
  // 推到 SoC DDR（详见 builder/flash.py:AmlogicFlashStrategy）。
  flash_tool: 'fastboot',
  rootfs+: {
    // 与 Rockchip / Allwinner 同样：normal 系统也安装 recoveryctl，便于
    // ADB 触发模式切换；flange-rootfs-grow 处理 rootfs 首启自扩展。
    custom_packages: ['adbd', 'recoveryctl', 'flange-rootfs-grow'],
  },
  recovery: {
    enabled: true,
    packages: [
      // 不在平台层挂 WiFi/BT 通用固件包 —— 不同 amlogic 板的 WiFi/BT
      // combo 各异（VIM3L 板载 AP6398S，其他 amlogic 板可能 RTL/realtek
      // 等），无法在平台层共享。各 board 在 extra_firmware 中按需声明
      // 自己的固件来源（VIM3L 走 khadas/fenix 板级 AP6398S 三件套）。
      // 注：Ubuntu 24.04 也没有 Debian 风格的 firmware-brcm80211 切片包
      // （Ubuntu 把 brcm firmware 打在 monolithic linux-firmware 里，
      // 整包 ~500MB），不适合 embedded 默认拉。
      // Recovery 子系统：默认开启，与 Rockchip / Allwinner 平台等价。
      // boards 可通过 enabled: false 关闭。
      'systemd', 'systemd-sysv', 'udev', 'dbus', 'python3', 'util-linux',
      'e2fsprogs', 'dosfstools', 'parted', 'gdisk', 'zstd', 'coreutils',
      'ca-certificates',
    ],
    custom_packages: ['adbd', 'recoveryctl'],
    transport: 'adb',
    protected_partitions: ['recovery'],
  },
}
