## MODIFIED Requirements

### Requirement: disable_root_login SHALL 同时锁 /etc/shadow 与 sshd

`disable_root_login: True` 时，框架 SHALL 在构建期：
1. 在 chroot 内执行 `passwd -l root`（使 `/etc/shadow` 中 root 字段以 `!` 起首）
2. 写入 `/etc/ssh/sshd_config.d/10-flange.conf`，内容包含 `PermitRootLogin no`
3. 确认 `PermitRootLogin no` 被 sshd 实际加载：`/etc/ssh/sshd_config` 已包含 `Include /etc/ssh/sshd_config.d/*.conf`
   时不修改主配置；未包含时（如 Ubuntu 18.04 的 OpenSSH 7.6，其 `sshd_config` 不支持 `Include`，写入会使 sshd
   拒绝启动），把 `PermitRootLogin no` 写在主配置首行，使其先于其他指令生效

`disable_root_login: True` 时，框架 SHALL 不影响 adb 调试通道 — adbd 由 systemd 以 root 启动，不走 PAM，`adb shell` 行为不变。

`disable_root_login: True` 时若 `users` 为空字典或缺省，框架 SHALL 在构建期 raise `ValueError`，避免镜像无任何普通用户可登录、串口 / SSH 全失联。

#### Scenario: 锁定后 /etc/shadow root 行带 ! 前缀
- **WHEN** 配置声明 `disable_root_login = True` 且 `users.flange = {password: "x"}`
- **THEN** 镜像 `/etc/shadow` root 行第二字段以 `!` 起首

#### Scenario: 锁定后 sshd drop-in 存在
- **WHEN** 配置声明 `disable_root_login = True` 且 `users.flange = {password: "x"}`
- **THEN** 镜像存在 `/etc/ssh/sshd_config.d/10-flange.conf`，至少包含一行 `PermitRootLogin no`

#### Scenario: 基线 sshd_config 未包含 drop-in 目录
- **WHEN** 基线 `/etc/ssh/sshd_config` 不含 `Include /etc/ssh/sshd_config.d/*.conf`，配置声明 `disable_root_login = True`
- **THEN** 镜像 `sshd_config` 第一条非注释指令为 `PermitRootLogin no`，不含 `Include`，sshd 可以启动且 `sshd -T` 输出 `permitrootlogin no`

#### Scenario: 基线已包含 drop-in 目录
- **WHEN** 基线 `sshd_config` 已包含该 `Include`（Ubuntu 24.04）
- **THEN** `sshd_config` 内容与基线逐字节一致

#### Scenario: 锁定后 adb shell 仍可达 root
- **WHEN** 配置声明 `disable_root_login = True`，烧录后 USB 连接设备
- **THEN** `adb shell` 直接进入 root bash，行为与未锁定时一致

#### Scenario: 锁定但未声明 users
- **WHEN** 配置声明 `disable_root_login = True` 但 `users` 字段缺省或为 `{}`
- **THEN** 构建在配置解析阶段 raise `ValueError`，错误信息提示需要至少声明一个 user

## ADDED Requirements

### Requirement: overlay 与内核模块 SHALL 以 root 属主写入 rootfs 且不改动已有目录

`RootfsBuilder` SHALL 以 `root:root` 属主写入合并进 rootfs 的新文件、目录与符号链接，并去掉组与其他用户的写权限
（仓库只记录 644 / 755），范围为 rootfs / platform / board overlay（及 recovery overlay）与 kernel 产物的 `lib/modules`；
rootfs 中已存在的目录 SHALL 保留原属主与权限，已存在的目录符号链接 SHALL 被跟随而不被替换成真实目录。
源目录的属主（仓库检出或宿主构建产物，通常为宿主 uid 1000，与镜像第一个普通用户同号）SHALL NOT 出现在镜像中。

#### Scenario: 系统目录属主不被 overlay 改写
- **WHEN** overlay 含 `etc/`、`usr/`、`var/` 下的文件，且仓库以 umask 002 检出
- **THEN** 镜像中 `/etc`、`/usr`、`/var` 保持 `root:root 755`，overlay 新增文件为 `root:root 644`（可执行为 755）

#### Scenario: 内核模块不归普通用户
- **WHEN** rootfs 安装 kernel 产物中的模块
- **THEN** `/lib/modules/<release>` 下全部文件属于 root，镜像中 `/home` 以外不存在属于 uid 1000 的文件

#### Scenario: merged-usr 目录符号链接
- **WHEN** rootfs 的 `/lib` 是指向 `usr/lib` 的符号链接，overlay 含 `lib/firmware/x`
- **THEN** 文件写入 `/usr/lib/firmware/x`，`/lib` 仍是符号链接
