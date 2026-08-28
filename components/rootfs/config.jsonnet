// 平台无关 rootfs 基线配置：声明 Ubuntu Base、包集合和默认系统策略。
// 平台无关的 rootfs 基线配置。
//
// rootfs canonical 字段速查（按主题分组）：
//
// — root 账号 —
//   root_password (string)
//       明文 root 密码。不设此字段时 ubuntu-base tarball 默认 /etc/shadow 中
//       root 字段为 "*"（锁定态），串口与 SSH 都无法登录；adb 不走 PAM 登录
//       所以 adbd 仍能 root shell，掩盖问题直到第一次真正去串口登录才暴露
//       （如 ROCK 5B 首版适配踩过这个坑）。
//       板级 overlay 可覆盖 rootfs.root_password；生产镜像应改为强随机
//       密码或迁 SSH key 体系。
//   disable_root_login (boolean, 默认 false)
//       true 时框架在构建期对 root 做两件事：
//         1) chroot 内 ``passwd -l root`` → /etc/shadow root 字段加 ! 前缀
//         2) 写 /etc/ssh/sshd_config.d/10-flange.conf 内容 PermitRootLogin no
//       adb 调试通道**不受影响**（adbd 不走 PAM，systemd 直接 root 拉起）。
//       此字段为 true 但 users 为空时，框架在构建期 raise ValueError —
//       避免镜像无任何普通用户可登录、串口/SSH 全失联。
//
// — 普通用户 —
//   users (object, 键=用户名)
//       声明要创建的非 root 用户。每个 value 接受：
//         password (string): 明文密码
//         groups (array[string], 默认 []): 用户额外加入的 group（追加在顶层
//             ``groups`` 之后）
//         shell (string, 默认 "/bin/bash"): 登录 shell
//         sudo: 三态控制 sudo 行为
//             true (默认)         — 入 sudo group，靠 /etc/sudoers 中
//                                   ``%sudo ALL=(ALL:ALL) ALL`` 提权
//             false               — 不入 sudo group（从顶层 groups 中显式扣
//                                   除 "sudo"）
//             {"nopasswd": true}  — 入 sudo group **且** 写入
//                                   /etc/sudoers.d/90-<name>，0440 root:root，
//                                   单行 ``<name> ALL=(ALL:ALL) NOPASSWD:ALL``
//   default_user (string | null)
//       标识"那个"默认用户的语义指针，必须是 users 中存在的键。desktop
//       package 可用它复用账号配置启用 GNOME Remote Login。
//   gnome_remote_desktop_login (boolean, 默认 false)
//       true 时将 default_user 及其 password 交给 desktop App，在首次启动
//       配置 GNOME Remote Desktop 系统级 RDP；成功后删除暂存明文凭据。
//
// — Group 集合 —
//   groups (array[string])
//       框架统一预创的 group 集合。两职：
//         1) 构建时对每条 group 调用 ``groupadd -f``（幂等创建），解决
//            i2c/spi/gpio 等 ubuntu-base 中默认不存在的 group
//         2) 作为每个 user 的默认入组集合（user.sudo=false 时框架从该集合
//            中显式扣除 "sudo" 后再合并 user 自己的 groups）
//
// — 包集合（与账号无关）—
//   package_sets 定义集合；package_set 使用 Jsonnet variant 条件选择集合。
local variant = std.extVar('variant');

{
  rootfs: {
    url: 'https://cdimage.ubuntu.com/ubuntu-base/releases/24.04/release/ubuntu-base-24.04.4-base-arm64.tar.gz',
    sha256: '04207713ece899c3740823d33690441ad3a7f0ded1101aca744e2b0f37ac7ff2',
    emulator: 'qemu-aarch64-static',
    // — root 账号 —
    // 框架默认完全锁定 root：不设密码 (/etc/shadow root 字段为 *) 且
    // 通过 disable_root_login=true 让 chroot 内 passwd -l 锁为 !* +
    // 写 sshd PermitRootLogin no。ssh / 串口 root 登录均被拒；adb
    // 调试通道仍可达 root（adbd 不走 PAM，开发期保留）。
    // 板级若需开放 root，在 board overlay 的 rootfs 中显式覆盖：
    // root_password: '1234', disable_root_login: false
    root_password: null,
    disable_root_login: true,
    users: {
      flange: {
        // — 普通用户 —
        // 默认建一个 flange 用户（与 ubuntu 桌面装机第一用户心智一致）：
        // 入 sudo group，密码同名；ssh / 串口登录后用 ``sudo -s`` 切 root。
        // 板级可整段重写 users / default_user 以替换默认用户；不希望任何
        // 用户的板级须显式 ``"users": {}`` 并同时把 disable_root_login
        // 设为 false（否则框架在校验阶段拒绝构建）。
        password: 'flange',
        sudo: true,
      },
    },
    default_user: 'flange',
    gnome_remote_desktop_login: false,
    groups: [
      // — Group 集合（嵌入式开发板向）—
      // 框架预创 + 默认入组；新增/修改请同步 wiki/components/rootfs-构建器.md
      'adm', 'dialout', 'cdrom', 'sudo', 'audio', 'video',
      'plugdev', 'users', 'netdev', 'input', 'render',
      'i2c', 'spi', 'gpio',
    ],
    package_sets: {
      base: [
        // — 包集合 —
        'systemd', 'systemd-sysv', 'dbus', 'network-manager',
        'iputils-ping', 'iproute2', 'openssh-server', 'sudo',
        'bash', 'bash-completion', 'ca-certificates', 'locales',
        'cloud-guest-utils', 'gdisk', 'e2fsprogs', 'util-linux',
        'python3', 'kmod', 'wpasupplicant', 'usbutils',
        'net-tools', 'systemd-timesyncd', 'btop',
      ],
      debug: ['gdb', 'strace', 'tcpdump', 'valgrind'],
      release: [],
    },
    package_set: ['base'] + (if variant == 'debug' then ['debug'] else ['release']),
  },
}
