// QRB2210 平台层配置：声明 ARM64 架构、QDL 刷写和可用变体。
local lib = import 'config/lib.libsonnet';

{
  platform: 'qualcommqrb2210',
  vendor: 'qcom',
  architecture: { userspace: 'aarch64', kernel: 'arm64', bootloader: 'arm64' },
  products: ['default'],
  variants: ['debug', 'release'],
  flash_tool: 'qdl',
  // 官方 EDL 救援不等于 flange 独立 ADB recovery。
  recovery: { enabled: false },
  rootfs+: {
    // Arduino UNO Q 自带整套 USB gadget 方案（adbd.service +
    // adbd-usb-gadget 脚本 + Android SDK 的 adbd），与 usbmoded 会抢同一个
    // configfs gadget。从基线中扣除 adbd，避免两套并存互相破坏。
    custom_packages: lib.without(super.custom_packages, ['adbd']),
  },

}
