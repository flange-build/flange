// Ubuntu Desktop 通用 package 配置：集中声明桌面软件、中文环境和镜像容量。
{
  rootfs+: {
    packages+: [
      'ubuntu-desktop',
      'glmark2-wayland',
      'language-pack-zh-hans',
      'language-pack-gnome-zh-hans',
      // rootfs 安装包统一使用 --no-install-recommends，显式保留中文字体。
      'fonts-noto-cjk',
      'gnome-remote-desktop',
      // Ubuntu 24.04 的 chromium-browser 是 Chromium Snap 的官方过渡包。
      'chromium-browser',
      'snapd',
    ],
    gnome_remote_desktop_login: true,
  },
  // desktop 软件与 Chromium Snap 需要高于嵌入式默认值的初始空间；仅支持
  // 可扩容 ext4 rootfs 的板，固定 512 MiB SPI NAND 板不启用本 package。
  partitions+: {
    entries: [
      if entry.name == 'rootfs' then entry + { image_size: '6G' } else entry
      for entry in super.entries
    ],
  },
}
