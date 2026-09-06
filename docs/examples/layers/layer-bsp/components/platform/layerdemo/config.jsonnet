// 示例平台：仅用于用户态闭环验证，不声明可刷写的硬件。
{ platform: 'layerdemo', vendor: 'example', flash_tool: 'none',
  architecture: {userspace: 'aarch64', kernel: 'arm64', bootloader: 'arm64'} }
