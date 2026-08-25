// Allwinner A733 平台层配置：声明共享架构、构建能力和公共源码。
// Allwinner A733 (allwinnera733) 平台配置 -- platform overlay
{
  platform: 'allwinnera733',
  vendor: 'allwinnera733',
  architecture+: {
    userspace: 'aarch64',
    kernel: 'arm64',
    bootloader: 'arm',
  },
  products: ['default'],
  variants: ['debug', 'release'],
  flash_tool: 'dd',
  rootfs+: {
    // 同 Rockchip：normal 系统也安装 recoveryctl，便于 ADB 触发模式切换。
    custom_packages: ['adbd', 'recoveryctl', 'flange-rootfs-grow'],
    // PowerVR DDK（下方 xserver-xorg-img-bxm）的 control 没有 Depends，且
    // dpkg -i 不解析依赖；显式安装 libdrm/xcb/x11-xcb/xshmfence/wayland 等
    // 低层运行库，避免 libEGL.so.1 无法 dlopen。这些库不是 GL 实现，不与 PVR 冲突。
    packages: [
      'libdrm2', 'libxcb1', 'libxcb-dri2-0', 'libxcb-dri3-0',
      'libxcb-randr0', 'libxcb-xfixes0', 'libxcb-present0',
      'libxcb-sync1', 'libx11-xcb1', 'libxshmfence1',
      'libwayland-server0', 'libwayland-client0',
    ],
    extra_debs: [
      {
        name: 'xserver-xorg-img-bxm',
        url: 'https://github.com/radxa-pkg/allwinner-prebuilt-extra/releases/download/0.1.10/xserver-xorg-img-bxm_1.21.1-2_arm64.deb',
        sha256: 'c8e606db1abdea40a5b97f7905ea86901b50c5fe1b76a55356ab70dde3304c3a',
      },
      {
        name: 'libcedarc-dev',
        url: 'https://github.com/radxa-pkg/allwinner-prebuilt-extra/releases/download/0.1.10/libcedarc-dev_2.0.0_arm64_new-f7cf8b546b8a5337c1ea19451972b3f1.deb',
        sha256: '24a5d7669cc382f79ec51ba6139be0ef3a54fc54d8843dbe150a4426d3dc6a99',
      },
    ],
  },
  recovery: {
    enabled: true,
    packages: [
      // Recovery 子系统：与 Rockchip 平台等价的默认值。首版主要在 RK3566 上
      // 落地，A733 的 image 端集成（image dd / flash-config）按"静态预留"
      // 处理（详见 §5.2 / §5.4）。boards 可通过 enabled: false 关闭。
      'systemd', 'systemd-sysv', 'udev', 'dbus', 'python3', 'util-linux',
      'e2fsprogs', 'dosfstools', 'parted', 'gdisk', 'zstd', 'coreutils',
      'ca-certificates',
    ],
    custom_packages: ['adbd', 'recoveryctl'],
    transport: 'adb',
    protected_partitions: ['recovery'],
  },
}
