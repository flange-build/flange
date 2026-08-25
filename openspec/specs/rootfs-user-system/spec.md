# rootfs-user-system Specification

## Purpose

定义 flange 镜像中 root 账号、普通用户、密码、group、sudo 策略、root 登录通道与 shell 体验的统一声明式配置体系。框架在 `RootfsBuilder` 基类中收敛实现，跨平台共享，配置入口集中在 `components/rootfs/config.jsonnet` 的 `ROOTFS["rootfs"]` 子树，板级可通过 `BOARD["rootfs"]` 整段重写覆盖默认。base 默认对齐 ubuntu 桌面心智模型 — root 完全锁定，默认用户 `flange/flange` 入 sudo group。

## Requirements

### Requirement: rootfs 配置 SHALL 支持声明式用户体系

`components/rootfs/config.jsonnet` 的 `ROOTFS["rootfs"]` 字典 SHALL 接受以下账号相关字段。框架 base 层默认值已切换到"ubuntu 桌面心智模型"——root 完全锁定 + 默认用户 `flange/flange`：所有未在板级显式覆盖账号字段的 board 都自动获得此行为。板级可通过 `BOARD["rootfs"]` 整段重写以替换或关闭默认用户体系。

字段：
- `root_password`（字符串 \| `None`，base 默认 `None`）：root 账号密码；`None` 时不调用 `chpasswd`，`/etc/shadow` root 字段保持 ubuntu-base tarball 出厂值（`*`）
- `disable_root_login`（布尔，base 默认 `True`）：是否禁止 root 通过串口 / SSH 登录
- `users`（dict，键为用户名，base 默认 `{"flange": {"password": "flange", "sudo": True}}`）：声明要创建的非 root 用户；每个 user value 接受子字段：
  - `password`（字符串，明文）：该用户密码
  - `groups`（字符串列表，默认 `[]`）：该用户额外加入的 group（追加在顶层 `groups` 之后）
  - `shell`（字符串，默认 `/bin/bash`）：登录 shell
  - `sudo`：三态 — `True`（默认入 sudo group）/ `False`（不入）/ `{"nopasswd": True}`（入 sudo group + 写 sudoers.d NOPASSWD）
- `default_user`（字符串 \| `None`，base 默认 `"flange"`）：标识"那个"默认用户的语义指针，非 `None` 时必须是 `users` 中存在的键
- `groups`（字符串列表）：框架统一预创的 group 集合，同时作为每个 user 默认加入的 group 集

#### Scenario: board 不覆盖账号字段 — 沿用 base 默认（root 锁定 + flange 用户）
- **WHEN** board 配置未在 `BOARD["rootfs"]` 中覆盖 `root_password` / `disable_root_login` / `users` / `default_user` 任一字段
- **THEN** 构建产物中：`/etc/passwd` 含 `flange` 用户（uid≥1000，shell 为 `/bin/bash`，家目录 `/home/flange`），`/etc/shadow` flange 行带合法密码 hash、root 行字段以 `!` 起首（被 `passwd -l` 锁定，原始字段为 `*`），`/etc/group` 中 sudo 含 `flange`，`/etc/ssh/sshd_config.d/10-flange.conf` 存在并含 `PermitRootLogin no`

#### Scenario: board 显式关闭用户体系（回退到"仅 root 可登录"形态）
- **WHEN** board 在 `BOARD["rootfs"]` 中显式声明 `users={}` 且 `disable_root_login=False` 且 `root_password="1234"`
- **THEN** 构建产物中：无非系统普通用户、无 `/etc/sudoers.d/90-*` 增量文件、无 `/etc/ssh/sshd_config.d/10-flange.conf`、`/etc/shadow` root 行含 hash 可登录

#### Scenario: 声明 default_user 指向不存在的用户
- **WHEN** board 配置 `default_user = "alice"` 但 `users` 中无 `alice` 键
- **THEN** 构建在配置解析阶段 raise `ValueError`，错误信息包含 `default_user` 与 `users` 键集

### Requirement: 框架 SHALL 在创建用户前预创顶层 groups 中声明的所有 group

对 `rootfs.groups` 列出的每条 group 名，框架 SHALL 在 chroot 内执行 `groupadd -f <name>`，无论该 group 是否被任何 user 引用，无论 ubuntu-base 中是否已存在该 group。

#### Scenario: 顶层 groups 包含 ubuntu-base 默认不存在的 group
- **WHEN** `rootfs.groups` 包含 `"i2c"`、`"spi"`、`"gpio"` 这类 ubuntu-base 默认未创建的 group
- **THEN** 构建后 `/etc/group` 中存在以上 group 行（即使没有任何 user 加入它们）

#### Scenario: 顶层 groups 包含已存在的 group
- **WHEN** `rootfs.groups` 包含 `"sudo"` 这类 ubuntu-base 已创建的 group
- **THEN** 构建成功无报错（`groupadd -f` 幂等），`/etc/group` 中 sudo 行不被破坏

### Requirement: 用户的实际入组集合 SHALL 由顶层 groups 与 user 自身 groups 合并构成

每个 `users.<name>` 在创建后，框架 SHALL 调用 `usermod -aG <merged> <name>`，其中 `<merged>` 为：
- `rootfs.groups` 全部条目
- ∪ `users.<name>.groups` 全部条目
- 若 `users.<name>.sudo == False`，则从合并集中移除 `"sudo"`

#### Scenario: 默认 user 自动入顶层 groups
- **WHEN** `rootfs.groups = ["sudo", "video", "dialout", "i2c"]` 且 `users.flange = {sudo: True}`
- **THEN** `flange` 用户最终所属 group 包含 `sudo`、`video`、`dialout`、`i2c`

#### Scenario: user.sudo=False 时显式扣除 sudo group
- **WHEN** `rootfs.groups = ["sudo", "video"]` 且 `users.guest = {sudo: False}`
- **THEN** `guest` 用户所属 group 包含 `video` 但**不**包含 `sudo`

#### Scenario: user.groups 追加额外 group
- **WHEN** `rootfs.groups = ["sudo"]` 且 `users.dev = {groups: ["docker"]}`
- **THEN** `dev` 用户所属 group 包含 `sudo` 与 `docker`

### Requirement: sudo 三态 SHALL 控制 sudoers.d 文件写入

框架 SHALL 按 `users.<name>.sudo` 的三态值控制 sudo group 与
`/etc/sudoers.d/` 文件写入：

- `sudo: True` 或省略 → 仅入 sudo group，**不**写 `/etc/sudoers.d/` 文件
- `sudo: False` → 不入 sudo group，**不**写 `/etc/sudoers.d/` 文件
- `sudo: {"nopasswd": True}` → 入 sudo group **且** 写入 `/etc/sudoers.d/90-<name>`，文件内容为单行 `<name> ALL=(ALL:ALL) NOPASSWD:ALL`，文件权限为 `0440`，所有者 `root:root`

#### Scenario: sudo NOPASSWD 写出 drop-in 文件
- **WHEN** `users.flange = {sudo: {"nopasswd": True}}`
- **THEN** 镜像中存在 `/etc/sudoers.d/90-flange`，内容为 `flange ALL=(ALL:ALL) NOPASSWD:ALL\n`，权限 `0440`

#### Scenario: 默认 sudo: True 不产生 drop-in 文件
- **WHEN** `users.flange = {sudo: True}`
- **THEN** `/etc/sudoers.d/` 中不存在 `90-flange`；该用户依赖 `/etc/sudoers` 的 `%sudo ALL=(ALL:ALL) ALL` 行获得 sudo 权限

### Requirement: disable_root_login SHALL 同时锁 /etc/shadow 与 sshd

`disable_root_login: True` 时，框架 SHALL 在构建期：
1. 在 chroot 内执行 `passwd -l root`（使 `/etc/shadow` 中 root 字段以 `!` 起首）
2. 写入 `/etc/ssh/sshd_config.d/10-flange.conf`，内容包含 `PermitRootLogin no`

`disable_root_login: True` 时，框架 SHALL 不影响 adb 调试通道 — adbd 由 systemd 以 root 启动，不走 PAM，`adb shell` 行为不变。

`disable_root_login: True` 时若 `users` 为空字典或缺省，框架 SHALL 在构建期 raise `ValueError`，避免镜像无任何普通用户可登录、串口 / SSH 全失联。

#### Scenario: 锁定后 /etc/shadow root 行带 ! 前缀
- **WHEN** 配置声明 `disable_root_login = True` 且 `users.flange = {password: "x"}`
- **THEN** 镜像 `/etc/shadow` root 行第二字段以 `!` 起首

#### Scenario: 锁定后 sshd drop-in 存在
- **WHEN** 配置声明 `disable_root_login = True` 且 `users.flange = {password: "x"}`
- **THEN** 镜像存在 `/etc/ssh/sshd_config.d/10-flange.conf`，至少包含一行 `PermitRootLogin no`

#### Scenario: 锁定后 adb shell 仍可达 root
- **WHEN** 配置声明 `disable_root_login = True`，烧录后 USB 连接设备
- **THEN** `adb shell` 直接进入 root bash，行为与未锁定时一致

#### Scenario: 锁定但未声明 users
- **WHEN** 配置声明 `disable_root_login = True` 但 `users` 字段缺省或为 `{}`
- **THEN** 构建在配置解析阶段 raise `ValueError`，错误信息提示需要至少声明一个 user

### Requirement: rootfs 构建 SHALL 安装 bash-completion 并提供对齐 ubuntu 的 shell 体验

`package_sets.base` SHALL 包含 `bash-completion`。
`components/rootfs/overlay/` SHALL 提供以下三个文件，使新建用户与 root 拥有 PS1、常用 alias、bash-completion（含 `sudo<TAB>` 补全）：
- `etc/bash.bashrc` — 系统级 bashrc（覆盖 ubuntu-base 默认），始终补齐 `HOME` / `USER` / `LOGNAME`（即便非交互），交互态设彩色 PS1（root 红色 / 普通用户绿色）；adb shell 走 POSIX-bash 不读 `~/.bashrc`，体验靠本文件承担
- `etc/skel/.bashrc` — 由 `useradd -m` 拷入新建用户家目录
- `root/.bashrc` — root 的同款体验，PS1 区分（红色 `#` 提示符）；ssh + `sudo -s` 路径生效

由此，ssh 登录 default_user 后执行 `sudo -s` 进入 root，与 `adb shell` 直接进入 root 的 bash 体验等价（同样 PS1 风格、同样 alias、同样 completion 行为）。

#### Scenario: 新建用户家目录拥有可用的 bash 配置
- **WHEN** 配置 `users.flange = {password: "x"}`，构建并烧录后 ssh 登录 flange
- **THEN** 该用户拥有 `~/.bashrc`，shell prompt 非默认 `\s-\v\$`，输入 `sudo<TAB><TAB>` 触发 completion

#### Scenario: root shell 体验与新用户对齐
- **WHEN** ssh 登录 default_user 后执行 `sudo -s`，或 `adb shell` 直接进入 root
- **THEN** 两路获得的 root bash 拥有一致的 PS1 风格（root 用 `#`）、一致的 alias（如 `ll` / `la`）、一致的 completion 行为

#### Scenario: adb shell 环境变量补齐
- **WHEN** 通过 `adb shell` 进入设备 root bash
- **THEN** `$HOME` 等于 `/root`、`$USER` 等于 `root`，btop / less 等读 `$HOME` 的程序不再因变量未设而失败

### Requirement: 账号配置 SHALL 全量纳入 rootfs cache hash

`builder/cache.py` 的 rootfs 阶段 hash 输入 SHALL 覆盖以下字段的稳定序列化结果：
- `root_password`
- `disable_root_login`
- `users`（含全部嵌套字段）
- `default_user`
- `groups`

序列化方式 SHALL 与 dict 键顺序无关（推荐 `json.dumps(..., sort_keys=True)`）。

#### Scenario: 修改某 user 的密码触发 rootfs 重建
- **WHEN** 仅将 `users.flange.password` 由 `"1234"` 改为 `"5678"`
- **THEN** 后续构建中 rootfs 缓存命中失败，触发完整 rootfs 重建

#### Scenario: 修改 dict key 排列顺序不触发重建
- **WHEN** `users` 字典内键的源代码字面量顺序发生变化但内容一致
- **THEN** rootfs cache hash 不变，缓存命中

### Requirement: rootfs 通用账号实现 SHALL 收敛在 RootfsBuilder 基类

`builder/rootfs.py` 的 `RootfsBuilder` 基类 SHALL 提供：
- `_set_root_password(rootfs_dir, password)`
- `_verify_root_password(rootfs_dir)`
- `_configure_users(rootfs_dir, config)` — 内部封装 group 预创、useradd、chpasswd、sudoers.d 写入、root 密码设置、`disable_root_login` 处理
- `_real_users(rootfs_cfg)` — 直接返回 canonical `rootfs.users`；Jsonnet 求值后不得存在嵌套 product/variant 伪 key

平台子类（`builder/platforms/rockchip/rootfs.py`、`builder/platforms/allwinnera733/rootfs.py`） SHALL 不再各自实现 `_set_root_password` / `_verify_root_password`，且不再直接读取 `rootfs.root_password`。子类 `_build_phase2` 中对账号配置的处理 SHALL 收敛为对 `self._configure_users(rootfs_dir, config)` 的单次调用。

`builder/recovery.py` 的 recovery rootfs 路径 SHALL 不调用 `_configure_users`，维持现有"recovery 不安装 root_password"的行为。

#### Scenario: 平台子类不再包含密码相关代码
- **WHEN** 检视 `builder/platforms/rockchip/rootfs.py` 与 `builder/platforms/allwinnera733/rootfs.py`
- **THEN** 两文件中不存在 `chpasswd` / `_set_root_password` / `root_password` 字面量

#### Scenario: 两平台账号行为一致
- **WHEN** 同一份 `rootfs` 配置（含 `users` / `disable_root_login`）被 rockchip 与 allwinnera733 平台分别构建
- **THEN** 两镜像 `/etc/passwd` 中 user 集合、`/etc/shadow` 中各 user 密码字段格式、`/etc/sudoers.d/` 内容、sshd drop-in 文件内容字节级一致
