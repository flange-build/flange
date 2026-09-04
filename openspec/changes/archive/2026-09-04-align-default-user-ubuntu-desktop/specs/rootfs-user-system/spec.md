## MODIFIED Requirements

### Requirement: rootfs 配置 SHALL 支持声明式用户体系

`components/rootfs/config.jsonnet` 的 `ROOTFS["rootfs"]` 字典 SHALL 接受以下账号相关字段。框架 base 层默认值采用 Ubuntu Desktop 账号模型——root 完全锁定 + 默认用户 `flange/flange`：所有未在板级显式覆盖账号字段的 board 都自动获得此行为。板级可通过 `BOARD["rootfs"]` 整段重写以替换或关闭默认用户体系。

字段：
- `root_password`（字符串 \| `None`，base 默认 `None`）：root 账号密码；`None` 时不调用 `chpasswd`，`/etc/shadow` root 字段保持 ubuntu-base tarball 出厂值（`*`）
- `disable_root_login`（布尔，base 默认 `True`）：是否禁止 root 通过串口 / SSH 登录
- `users`（dict，键为用户名，base 默认 `{"flange": {"password": "flange", "sudo": True}}`）：声明要创建的非 root 用户；每个 user value 接受子字段：
  - `password`（字符串，明文）：该用户密码
  - `groups`（字符串列表，默认 `[]`）：该用户额外加入的 group（追加在顶层 `groups` 之后）
  - `shell`（字符串，默认 `/bin/bash`）：登录 shell
  - `sudo`：三态 — `True`（默认入 sudo group）/ `False`（不入）/ `{"nopasswd": True}`（入 sudo group + 写 sudoers.d NOPASSWD）
- `default_user`（字符串 \| `None`，base 默认 `"flange"`）：标识默认桌面用户的语义指针，非 `None` 时 MUST 是 `users` 中存在的键；该用户 MUST 使用 UID 1000，并拥有同名、GID 1000 的 user private group（用户私有组）
- `groups`（字符串列表）：框架统一预创的 system group（系统组）集合，同时作为每个 user 默认加入的 group 集

除 `default_user` 外的用户 SHALL 由 Ubuntu `useradd` 从普通用户编号范围自动分配 UID 与同名用户私有组。若 UID 1000、GID 1000 或 `default_user` 的同名组已被其他身份占用，构建 MUST 失败，不得改用其他编号继续生成镜像。

#### Scenario: board 不覆盖账号字段 — 沿用 base 默认（root 锁定 + flange 用户）
- **WHEN** board 配置未在 `BOARD["rootfs"]` 中覆盖 `root_password` / `disable_root_login` / `users` / `default_user` 任一字段
- **THEN** 构建产物中：`/etc/passwd` 含 `flange` 用户（UID 1000、shell 为 `/bin/bash`、家目录 `/home/flange`），`/etc/group` 含同名 `flange` 用户私有组（GID 1000），且该组是 `flange` 的主组
- **AND** `/etc/shadow` flange 行带合法密码 hash、root 行字段以 `!` 起首（被 `passwd -l` 锁定，原始字段为 `*`），`/etc/group` 中 sudo 含 `flange`，`/etc/ssh/sshd_config.d/10-flange.conf` 存在并含 `PermitRootLogin no`

#### Scenario: default_user 不受 users 声明顺序影响
- **WHEN** `users` 中另一个普通用户排列在 `default_user` 之前
- **THEN** RootfsBuilder 仍先创建 `default_user`，并为其保留 UID 1000 与同名 GID 1000 用户私有组

#### Scenario: 默认用户编号被占用
- **WHEN** 基础镜像或前置安装包已将 UID 1000 或 GID 1000 分配给其他身份
- **THEN** rootfs 构建失败并保留 `groupadd` 或 `useradd` 的冲突诊断，不得为 `default_user` 自动选择其他编号

#### Scenario: board 显式关闭用户体系（回退到“仅 root 可登录”形态）
- **WHEN** board 在 `BOARD["rootfs"]` 中显式声明 `users={}` 且 `disable_root_login=False` 且 `root_password="1234"`
- **THEN** 构建产物中：无非系统普通用户、无 `/etc/sudoers.d/90-*` 增量文件、无 `/etc/ssh/sshd_config.d/10-flange.conf`、`/etc/shadow` root 行含 hash 可登录

#### Scenario: 声明 default_user 指向不存在的用户
- **WHEN** board 配置 `default_user = "alice"` 但 `users` 中无 `alice` 键
- **THEN** 构建在配置解析阶段 raise `ValueError`，错误信息包含 `default_user` 与 `users` 键集

### Requirement: 框架 SHALL 在创建用户前预创顶层 groups 中声明的所有 group

对 `rootfs.groups` 列出的每条 group 名，框架 SHALL 在 chroot 内执行 `groupadd -r -f <name>`，无论该 group 是否被任何 user 引用。新建 group MUST 从 Ubuntu system group（系统组）范围分配 GID，不得占用从 1000 开始的普通用户 GID 范围；已存在 group MUST 保持原 GID。

#### Scenario: 顶层 groups 包含 ubuntu-base 默认不存在的 group
- **WHEN** `rootfs.groups` 包含 `"i2c"`、`"spi"`、`"gpio"` 这类 ubuntu-base 默认未创建的 group
- **THEN** 构建后 `/etc/group` 中存在以上 group 行（即使没有任何 user 加入它们），且新分配的 GID 均小于 1000

#### Scenario: 顶层 groups 包含已存在的 group
- **WHEN** `rootfs.groups` 包含 `"sudo"` 这类 ubuntu-base 已创建的 group
- **THEN** 构建成功无报错（`groupadd -r -f` 幂等），`/etc/group` 中 sudo 行及其既有 GID 不被改写
