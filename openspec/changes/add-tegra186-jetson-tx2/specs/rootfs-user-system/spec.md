## MODIFIED Requirements

### Requirement: disable_root_login SHALL 同时锁 /etc/shadow 与 sshd

`disable_root_login: True` 时，框架 SHALL 在构建期：
1. 在 chroot 内执行 `passwd -l root`（使 `/etc/shadow` 中 root 字段以 `!` 起首）
2. 写入 `/etc/ssh/sshd_config.d/10-flange.conf`，内容包含 `PermitRootLogin no`
3. 确认 `/etc/ssh/sshd_config` 加载 `/etc/ssh/sshd_config.d/*.conf`；基线配置未包含该目录时（如 Ubuntu 18.04 的 OpenSSH 7.6），
   在文件首行插入 `Include /etc/ssh/sshd_config.d/*.conf`，使 drop-in 先于其他指令生效；已包含时不修改文件

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
- **THEN** 镜像 `sshd_config` 第一条非注释指令为该 `Include`，`sshd -T` 输出 `permitrootlogin no`

#### Scenario: 基线已包含 drop-in 目录
- **WHEN** 基线 `sshd_config` 已包含该 `Include`（Ubuntu 24.04）
- **THEN** `sshd_config` 内容与基线逐字节一致

#### Scenario: 锁定后 adb shell 仍可达 root
- **WHEN** 配置声明 `disable_root_login = True`，烧录后 USB 连接设备
- **THEN** `adb shell` 直接进入 root bash，行为与未锁定时一致

#### Scenario: 锁定但未声明 users
- **WHEN** 配置声明 `disable_root_login = True` 但 `users` 字段缺省或为 `{}`
- **THEN** 构建在配置解析阶段 raise `ValueError`，错误信息提示需要至少声明一个 user
