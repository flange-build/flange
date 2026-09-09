// UNO Q 功能包：Ubuntu 原生依赖及 Arduino 运行时策略，不引入 Debian 系统库。
{
  rootfs+: {
    package_sets+: {
      unoq: [
        'systemd', 'systemd-sysv', 'systemd-timesyncd', 'systemd-boot-efi', 'udev', 'initramfs-tools', 'kmod',
        'python3', 'binutils', 'gpiod', 'network-manager', 'wpasupplicant', 'wireless-regdb',
        'bluez', 'qrtr-tools', 'rmtfs', 'tqftpserv', 'iw', 'rfkill', 'alsa-ucm-conf', 'alsa-utils',
        'pipewire', 'pipewire-pulse', 'wireplumber', 'libspa-0.2-bluetooth',
        'docker.io', 'docker-compose-v2', 'avahi-daemon', 'libnss-mdns', 'openssh-server',
        'libwebkit2gtk-4.1-0', 'fonts-noto-color-emoji', 'inotify-tools', 'socat',
        'device-tree-compiler', 'ca-certificates', 'curl', 'git', 'sudo', 'zram-tools',
        'xfce4', 'lightdm', 'lightdm-gtk-greeter', 'xserver-xorg', 'xserver-xorg-video-fbdev',
        'mesa-utils', 'mesa-vulkan-drivers', 'libgl1-mesa-dri', 'v4l-utils',
        'gstreamer1.0-libcamera', 'libcamera-tools', 'libusb-1.0-0', 'libgpiod2t64',
        'android-libbase', 'android-libboringssl', 'android-libcutils', 'android-liblog',
        'libprotobuf32t64',
        'e2fsprogs', 'dosfstools', 'locales', 'needrestart', 'dbus-user-session',
      ],
    },
    package_set: ['unoq'],
    default_session: 'xfce',
    // App CLI 与 MCU 上传服务沿用上游固定用户身份。
    groups+: ['adm', 'video', 'docker', 'netdev', 'dialout', 'audio', 'render',
              'bluetooth', 'input', 'gpiod'],
  },
}
