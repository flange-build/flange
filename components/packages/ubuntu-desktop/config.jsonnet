// Ubuntu Desktop 通用 package 配置：集中声明桌面软件、中文环境和镜像容量。
{
  rootfs+: {
    packages+: [
      // GNOME Core 直接提供 GDM、Shell、Settings、Nautilus 与标准应用，
      // 不引入 Ubuntu session、Yaru 和 Ubuntu Shell 扩展。
      'gnome-core',
      'glmark2-wayland',
      'language-pack-zh-hans',
      'language-pack-gnome-zh-hans',
      // 简体中文字体是 product 硬要求，不依赖元包 Recommends 漂移。
      'fonts-noto-cjk',
      'gnome-remote-desktop',
      'openssl',
      // Ubuntu 24.04 的 chromium-browser 是 Chromium Snap 的官方过渡包。
      'chromium-browser',
      'snapd',
    ],
    default_locale: {
      lang: 'zh_CN.UTF-8',
      language: 'zh_CN:zh',
    },
    // 桌面 product 安装 GNOME 元包维护的推荐集，获得完整桌面体验。
    install_recommends: true,
    default_session: 'gnome',
    gnome_remote_desktop_login: true,
  },
  // desktop 软件与 Chromium Snap 需要高于嵌入式默认值的初始空间；仅支持
  // 可扩容 ext4 rootfs 的板，固定 512 MiB SPI NAND 板不启用本 package。
  partitions+: {
    entries: [
      if entry.name == 'rootfs' then entry + { image_size: '8G' } else entry
      for entry in super.entries
    ],
  },
}
