"""平台无关的 rootfs 基线配置。

ROOTFS["rootfs"] 字段速查（按主题分组）：

— root 账号 —
  root_password (str)
      明文 root 密码。不设此字段时 ubuntu-base tarball 默认 /etc/shadow 中
      root 字段为 "*"（锁定态），串口与 SSH 都无法登录；adb 不走 PAM 登录
      所以 adbd 仍能 root shell，掩盖问题直到第一次真正去串口登录才暴露
      （如 ROCK 5B 首版适配踩过这个坑）。
      板级 BOARD["rootfs"]["root_password"] 可覆盖；生产镜像应改为强随机
      密码或迁 SSH key 体系。
  disable_root_login (bool, 默认 False)
      true 时框架在构建期对 root 做两件事：
        1) chroot 内 ``passwd -l root`` → /etc/shadow root 字段加 ! 前缀
        2) 写 /etc/ssh/sshd_config.d/10-flange.conf 内容 PermitRootLogin no
      adb 调试通道**不受影响**（adbd 不走 PAM，systemd 直接 root 拉起）。
      此字段为 true 但 users 为空时，框架在构建期 raise ValueError —
      避免镜像无任何普通用户可登录、串口/SSH 全失联。

— 普通用户 —
  users (dict, 键=用户名)
      声明要创建的非 root 用户。每个 value 接受：
        password (str): 明文密码
        groups (list[str], 默认 []): 用户额外加入的 group（追加在顶层
            ``groups`` 之后）
        shell (str, 默认 "/bin/bash"): 登录 shell
        sudo: 三态控制 sudo 行为
            True (默认)         — 入 sudo group，靠 /etc/sudoers 中
                                  ``%sudo ALL=(ALL:ALL) ALL`` 提权
            False               — 不入 sudo group（从顶层 groups 中显式扣
                                  除 "sudo"）
            {"nopasswd": True}  — 入 sudo group **且** 写入
                                  /etc/sudoers.d/90-<name>，0440 root:root，
                                  单行 ``<name> ALL=(ALL:ALL) NOPASSWD:ALL``
  default_user (str | None)
      标识"那个"默认用户的语义指针，必须是 users 中存在的键。当前仅作元
      数据；不联动 autologin / getty 等。

— Group 集合 —
  groups (list[str])
      框架统一预创的 group 集合。两职：
        1) 构建时对每条 group 调用 ``groupadd -f``（幂等创建），解决
           i2c/spi/gpio 等 ubuntu-base 中默认不存在的 group
        2) 作为每个 user 的默认入组集合（user.sudo=False 时框架从该集合
           中显式扣除 "sudo" 后再合并 user 自己的 groups）

— 包集合（与账号无关，沿用旧字段）—
  package_sets / package_set / +package_set:<variant>
"""

ROOTFS = {
    "rootfs": {
        # — root 账号 —
        # 框架默认完全锁定 root：不设密码 (/etc/shadow root 字段为 *) 且
        # 通过 disable_root_login=True 让 chroot 内 passwd -l 锁为 !* +
        # 写 sshd PermitRootLogin no。ssh / 串口 root 登录均被拒；adb
        # 调试通道仍可达 root（adbd 不走 PAM，开发期保留）。
        # 板级若需开放 root，板级 BOARD["rootfs"] 中显式覆盖：
        #   "root_password": "1234", "disable_root_login": False
        "root_password": None,
        "disable_root_login": True,

        # — 普通用户 —
        # 默认建一个 flange 用户（与 ubuntu 桌面装机第一用户心智一致）：
        # 入 sudo group，密码同名；ssh / 串口登录后用 ``sudo -s`` 切 root。
        # 板级可整段重写 users / default_user 以替换默认用户；不希望任何
        # 用户的板级须显式 ``"users": {}`` 并同时把 disable_root_login
        # 设为 False（否则框架在校验阶段拒绝构建）。
        "users": {
            "flange": {
                "password": "flange",
                "sudo": True,
            },
        },
        "default_user": "flange",

        # — Group 集合（嵌入式开发板向）—
        # 框架预创 + 默认入组；新增/修改请同步 wiki/components/rootfs-构建器.md
        "groups": [
            "adm", "dialout", "cdrom", "sudo", "audio", "video",
            "plugdev", "users", "netdev", "input", "render",
            "i2c", "spi", "gpio",
        ],

        # — 包集合 —
        "package_sets": {
            "base": [
                "systemd", "systemd-sysv", "dbus", "network-manager",
                "iputils-ping", "iproute2", "openssh-server", "sudo",
                "bash", "bash-completion", "ca-certificates", "locales",
                "cloud-guest-utils", "gdisk", "e2fsprogs", "util-linux",
                "python3", "kmod", "wpasupplicant", "usbutils",
                "net-tools", "systemd-timesyncd", "btop",
            ],
            "debug": ["gdb", "strace", "tcpdump", "valgrind"],
            "release": [],
        },
        "package_set": ["base"],
        "+package_set:debug": ["debug"],
        "+package_set:release": ["release"],
    },
}
