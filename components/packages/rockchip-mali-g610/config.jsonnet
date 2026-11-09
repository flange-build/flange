// Mali-G610 厂商 package 配置：在 rootfs 基础阶段预装本地 DEB 的系统运行依赖。
// rootfs 定制阶段使用 dpkg 安装自有包，不会自动从 APT 补齐 Depends。
{
  rootfs+: {
    packages+: [
      'libc6', 'libdrm2', 'libgcc-s1', 'libstdc++6',
      'libwayland-client0', 'libwayland-server0',
      'libx11-6', 'libx11-xcb1', 'libxcb-dri2-0', 'libxcb1',
      'ocl-icd-libopencl1', 'libvulkan1', 'udev',
    ],
  },
}
