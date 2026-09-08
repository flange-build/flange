// QRB2210 平台层配置：声明 ARM64 架构、QDL 刷写和可用变体。
{
  platform: 'qualcommqrb2210',
  vendor: 'qcom',
  architecture: { userspace: 'aarch64', kernel: 'arm64', bootloader: 'arm64' },
  products: ['default'],
  variants: ['debug', 'release'],
  flash_tool: 'qdl',
  // 官方 EDL 救援不等于 flange 独立 ADB recovery。
  recovery: { enabled: false },
}
