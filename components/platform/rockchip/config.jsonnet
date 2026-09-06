// Rockchip 平台层配置：声明共享架构、构建能力和公共源码。
// Rockchip 平台配置 -- platform overlay
{
  platform: 'rockchip',
  vendor: 'rockchip',
  architecture+: {
    userspace: 'aarch64',
    kernel: 'arm64',
    bootloader: 'arm',
  },
  products: ['default'],
  variants: ['debug', 'release'],
  flash_tool: 'upgrade_tool',
  sources+: {
    rkbin: {
      url: 'https://github.com/radxa/rkbin',
      // rkbin 与 u-boot 版本对应：bootloader 切到 next-dev-v2026.01 后，
      // rkbin 同步切到 develop-v2026.01（含配套 DDR firmware / BL31 /
      // OPTEE blob）。详见 rk3566/config.jsonnet 的 bootloader.branch 注释。
      branch: 'develop-v2026.01',
    },
    'rockchip-u-boot': {
      url: 'https://github.com/radxa/u-boot',
      branch: 'next-dev-v2026.01',
    },
    'rockchip-kernel': {
      url: 'ssh://git@github.com/flange-build/kernel.git',
      branch: 'linux-6.1-stan-rkr5.1',
    },
  },
  rkbin: { source: { name: 'rkbin' } },
  rootfs+: {
    // recoveryctl 需要在 normal 系统中也能调用（`recoveryctl recovery`
    // 通过 reboot reason 从 normal 进入 recovery，由 `flange recovery enter`
    // 通过 ADB 触发）；flash/backup 子命令会在 normal 模式下硬性拒绝，安全。
    custom_packages: ['adbd', 'recoveryctl', 'flange-rootfs-grow'],
    // libdrm 用户态库 —— Mali GPU（panthor / mali_kbase）+ Rockchip VPU
    // （mpp）+ RGA 都通过 DRM render node / 私有 ioctl 与内核交互，需要
    // libdrm2 暴露的 ABI（drmGetDevice2 / drmIoctl 等）；libdrm-common
    // 是 libdrm2 的 dpkg 强依赖（提供 /usr/share/libdrm/）。ubuntu-base
    // tarball 不带，必须显式追加进 packages 基线。
    packages: ['libdrm2', 'libdrm-common'],
  },
  recovery: {
    enabled: true,
    packages: [
      // Recovery 维护系统（独立 rootfs，独立分区）默认开启；
      // 如某个板子存储紧张可在 board 配置覆盖 enabled: false。
      // SoC/board 层需在 partitions.entries 中提供 recovery 分区，
      // 否则 validate_config 会拒绝配置。
      'systemd', 'systemd-sysv', 'udev', 'dbus', 'python3', 'util-linux',
      'e2fsprogs', 'dosfstools', 'parted', 'gdisk', 'zstd', 'coreutils',
      'ca-certificates',
    ],
    custom_packages: ['adbd', 'recoveryctl'],
    transport: 'adb',
    // raw 类型分区由设备端按 type 自动保护，这里补充 recovery 自身。
    protected_partitions: ['recovery'],
  },
  // AMP 协处理器固件（裸机 HAL / RT-Thread）默认全平台关闭；需要的板在 board
  // 配置 opt-in（如 tspi-rk3566 的 amp product）。启用时 SoC/board 须提供
  // amp.mode、amp.soc_project、amp.memory，并在 partitions.entries 提供非 raw
  // 的 amp 分区，否则 validate_amp 拒绝配置。
  amp: { enabled: false },
}
