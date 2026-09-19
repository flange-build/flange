// Qualcomm SC8280XP 平台层配置：声明共享架构、构建能力和变体策略。
// Qualcomm SC8280XP 平台配置。
local variant = std.extVar('variant');

{
  platform: 'qualcommsc8280xp',
  vendor: 'qualcommsc8280xp',
  architecture+: {
    userspace: 'aarch64',
    kernel: 'arm64',
    bootloader: 'arm64',
  },
  products: ['default'],
  variants: ['debug', 'release'],
  flash_tool: 'edl-ng',
  rootfs+: {
    // adbd 已在 rootfs 基线层默认启用，这里只追加本层特有的包。
    custom_packages+: ['flange-rootfs-grow'],
    packages: [
      'bluez', 'bluetooth', 'protection-domain-mapper', 'qrtr-tools',
      'alsa-ucm-conf', 'acpi', 'zstd', 'libgl1-mesa-dri', 'libegl-mesa0',
      'libgbm1', 'mesa-vulkan-drivers', 'linux-firmware',
    ] + (if variant == 'debug' then ['mesa-utils', 'vulkan-tools'] else []),
  },
  recovery: { enabled: false },
}
