// Rockchip 多媒体 package 配置：为本地重打 runtime 预装 Noble 依赖与同名升级基线。
{
  rootfs+: {
    packages+: [
      'libgstreamer1.0-0',
      'gstreamer1.0-tools',
      'gstreamer1.0-plugins-base-apps',
      'libgstreamer-plugins-base1.0-0',
      'libgstreamer-gl1.0-0',
      'gstreamer1.0-alsa',
      'gstreamer1.0-plugins-base',
      'gstreamer1.0-x',
      'gstreamer1.0-gl',
      'gstreamer1.0-plugins-good',
      'libgstreamer-plugins-good1.0-0',
      'gstreamer1.0-plugins-bad-apps',
      'gstreamer1.0-plugins-bad',
      'libgstreamer-plugins-bad1.0-0',
    ],
  },
}
