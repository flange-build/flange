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
  //
  // image_size 只是**构建期容器尺寸**，不是设备上的最终容量：rootfs 声明了
  // grow_on_first_boot，首启会 growpart 撑满整盘。实测 ext4 内容 2.70 GiB，
  // 按 _ensure_rootfs_fits_image 的 max(20%, 128MiB) 保留规则需要 3.24 GiB，
  // 4 GiB 仍有 25% 余量。声明成 8G 只会让每个 target 在构建卷上多占 4 GiB
  // 并让 image 阶段多 dd 一倍数据，对设备零收益。
  partitions+: {
    entries: [
      if entry.name == 'rootfs' then entry + { image_size: '4G' } else entry
      for entry in super.entries
    ],
  },
}
