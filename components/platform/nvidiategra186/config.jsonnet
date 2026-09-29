// NVIDIA Tegra186 平台层配置：声明 L4T R32.7.6 的架构、tegraflash 刷写、Ubuntu 18.04 rootfs 与 L4T 用户态。
//
// 启动链全部是 NVIDIA 预编译件：MB1 → MB2 → cboot → U-Boot（kernel 分区）→
// APP 分区 /boot/extlinux → Linux；刷写只能在 USB Recovery（0955:7c18）下用
// BSP 自带的 tegraflash 完成。L4T R32 的 CUDA / 硬件编解码 / 摄像头只在 4.9 内核 +
// Ubuntu 18.04 用户态上完整可用，所以本平台把 rootfs 基线换成 18.04。
// 设计依据见 openspec/changes/add-tegra186-jetson-tx2/design.md。
local lib = import 'config/lib.libsonnet';

// L4T 用户态包版本必须与 BSP 启动链（R32.7.6）和内核一致。
local l4t = '32.7.6-20241104234601';
// NVIDIA Jetson OTA 仓库签名 key（jetson-ota-public.asc），两个源共用。
local nvidiaKey = {
  url: 'https://repo.download.nvidia.com/jetson/jetson-ota-public.asc',
  sha256: '576f852981855e5c6cfb9b625ffb51b984ca451f1181b2e70435b005034fad55',
  filename: 'jetson-ota-public.asc',
};

{
  platform: 'nvidiategra186',
  vendor: 'nvidia',
  architecture+: {
    userspace: 'aarch64',
    kernel: 'arm64',
    bootloader: 'arm64',
  },
  products: ['default'],
  variants: ['debug', 'release'],
  // 宿主刷写走 BSP 的 tegraflash.py（x86_64 宿主二进制），见 builder/flash/tegra.py。
  flash_tool: 'tegraflash',
  // L4T 自带的 recovery 内核属于 OTA 体系，flange ADB recovery 不适用于本平台。
  recovery: { enabled: false },
  rootfs+: {
    url: 'https://cdimage.ubuntu.com/ubuntu-base/releases/18.04/release/ubuntu-base-18.04.5-base-arm64.tar.gz',
    sha256: '9327cf905e818c38ba04605e40fbe11ac6548537786dc12936ca5819f8a563ad',
    package_sets+: {
      // btop 从 22.04 起才有；18.04 的 timesyncd 包含在 systemd 包里，没有独立包名。
      base: lib.without(super.base, ['btop', 'systemd-timesyncd']),
    },
    // USB gadget 与其他平台一样由 usbmoded 管理（默认 debug 场景 = adb），L4T 自带的
    // USB device mode（192.168.55.1）在 overlay 中 mask，两者会争用同一个 UDC。
    // usbmoded 用到 typing.Protocol（Python >= 3.8），18.04 默认 python3 是 3.6，
    // 因此装 universe 的 python3.8，overlay 中让 usbmoded 与 usb-mode 用它运行。
    // python3-yaml 是 usbmoded 的 deb 依赖（自有 deb 以 dpkg 安装，不会自动补依赖）。
    // flange 编译型 App 按容器内 glibc 2.39 编译，仍不能在 18.04 上运行；adbd 为静态链接。
    packages+: ['python3.8', 'python3-yaml'],
    // 与 stock L4T 相同的两个源保留在镜像中，设备上可直接 apt install nvidia-jetpack。
    // 不再安装 nvidia-l4t-apt-source，避免同一源被配置两次。
    extra_apt_sources: [
      {
        name: 'nvidia-jetson-common',
        key: nvidiaKey,
        source: 'deb [signed-by=/etc/apt/keyrings/nvidia-jetson-common.gpg] https://repo.download.nvidia.com/jetson/common r32.7 main',
      },
      {
        name: 'nvidia-jetson-t186',
        key: nvidiaKey,
        source: 'deb [signed-by=/etc/apt/keyrings/nvidia-jetson-t186.gpg] https://repo.download.nvidia.com/jetson/t186 r32.7 main',
      },
    ],
    // L4T 用户态包的 preinst 在 chroot 中读不到 /proc/device-tree，必须在 Phase 2
    // 由平台 rootfs 放置标记文件后安装，因此不能放进共享的 Phase 1 packages。
    // 不装：kernel / kernel-dtbs / kernel-headers（与自建内核冲突）、bootloader
    // （会尝试更新启动固件）、jetson-io（依赖 kernel 包）、oem-config（用户由 flange
    // 创建）、apt-source、weston、graphics-demos、gputools。
    // initrd 必须装：stock 内核 xhci 为 built-in，其固件由 /boot/initrd 提供。
    phase2_packages: [
      'nvidia-l4t-%s=%s' % [name, l4t]
      for name in [
        'core', 'init', 'firmware', 'tools', 'configs', 'xusb-firmware', 'initrd',
        'x11', 'wayland', 'libvulkan', '3d-core', 'cuda',
        'multimedia-utils', 'multimedia', 'camera', 'gstreamer',
      ]
    ],
  },
}
