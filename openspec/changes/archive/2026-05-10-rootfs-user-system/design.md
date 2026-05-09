## Context

flange 现有 rootfs 配置仅有一个 `root_password` 字段；两套平台（rockchip、allwinnera733）各自实现了几乎相同的 `_set_root_password` / `_verify_root_password`，并在 `_build_phase2` 末尾调用。`builder/cache.py:309` 仅把 `root_password` 纳入 hash。adb 调试通道由 `components/app/adbd/` 提供（systemd 拉起静态 `adbd-arm64`，二进制 hardcoded `/bin/bash`）；ssh 由 `package_sets.base` 中的 `openssh-server` 提供。`components/rootfs/overlay/` 已有一份 `etc/`，由 `RootfsBuilder.apply_overlays` 在 phase2 中按 rootfs → platform → board 顺序拷入 — 后者覆盖前者。

ubuntu 桌面安装时的事实标准心智模型：
- 装机阶段创建一个普通用户，加入 `sudo`、`adm`、`dialout`、`plugdev`、`netdev` 等一组 group
- root 账号默认锁定（`/etc/shadow` root 字段为 `!`），不允许密码登录
- `/etc/sudoers` 中 `%sudo ALL=(ALL:ALL) ALL` 一行让 sudo group 成员可提权
- bash 体验依赖 `bash-completion` 包 + `/etc/skel/.bashrc` 模板（其中 completion source 块默认是注释的）

本 change 把这套心智模型平移到 flange，同时保持空配置时跟今天行为完全一致，避免破已有 board。

## Goals / Non-Goals

**Goals:**
- 在 `components/rootfs/config.py` 的声明式配置中支持用户、密码、group、sudo 策略、root 锁定策略
- 让 `_set_root_password` 与新增的 `_configure_users` 都在 `RootfsBuilder` 基类中实现，平台子类只调用、不重写
- ssh 登录与 adb shell 拿到的 bash 体验对齐 ubuntu 桌面（PS1、alias、bash-completion 含 sudo<TAB>）
- `disable_root_login: true` 同时锁 `/etc/shadow` 的 root 与禁 sshd `PermitRootLogin`，但保持 adb 调试通道可达
- cache hash 覆盖整个账号子树，改密码 / 改 sudo 配置 / 加用户都触发 rootfs 重建
- framework base 默认值切换到"ubuntu 桌面心智模型"（root 完全锁定 + 默认用户 `flange/flange`），让所有未做账号覆盖的 board 即时获得现代默认；板级可整段重写 `users` / 关掉 `disable_root_login` 回退到旧形态

**Non-Goals:**
- SSH 公钥注入（`authorized_keys`） — 留给后续 change
- 密码哈希字段（`password_hash`） — 仅支持明文，与现有 `root_password` 一致
- Autologin / getty 自动登录 — `default_user` 仅作语义指针
- adb shell 切换到 default_user 或重新编译 adbd — 完全不动 adbd 二进制
- recovery rootfs 的用户体系 — recovery 维持现有"不装 root_password"行为，不调用 `_configure_users`

## Decisions

### Decision 1: schema 形态 — dict-by-name + 顶层 default_user 指针

**选**：

```python
ROOTFS["rootfs"] = {
    "root_password": "1234",
    "disable_root_login": False,
    "users": {
        "<name>": {
            "password": "<plaintext>",
            "groups": [],                 # 用户额外追加的 group
            "shell": "/bin/bash",
            "sudo": True,                 # True / False / {"nopasswd": True}
        },
    },
    "default_user": "<name>",             # 仅元数据指针
    "groups": [...],                      # 框架预创 group + default 用户加入集
}
```

**为什么不选数组**：board 层用 dict 浅合并覆盖单个 user 的子字段（如只改 `sudo`）零样板。数组形态需要按 name 匹配再 patch，跟现有 board override 风格不一致。

**为什么 `default_user` 是顶层指针不是 user 内的 `default: true`**：避免列表中多个 user 都标 `default: true` 的歧义；指针写错（指向不存在的 user）也容易在框架层早 fail。

### Decision 2: 顶层 `groups` 同时承担"预创"与"默认入组"两职

`rootfs.groups` 列出的每条 group：
1. 在创建用户前先 `groupadd -f <g>`（幂等）— 解决 `i2c/spi/gpio` 等 ubuntu-base 中默认不存在的 group
2. 自动作为每个 user 的 `usermod -aG` 列表（除非 user 显式 `sudo: False` 时框架会从加入集中扣掉 `sudo`）
3. user 自己 `groups: [...]` 中列的项追加到 (1) 之后

**为什么"预创"路径选 (a) 而不是 (b)**：(b)"只对已存在的 group 加入"会让镜像行为依赖 deb 安装顺序（某 deb 创建了 video group 才能加入），不可预测。(a) 让 group 集合在框架层显式声明，行为可预测，代价仅是若干空 group。

**为什么不另起一个 `default_groups` 字段**：与 user 内 `groups` 同名仅在嵌套层不同，语义清晰（顶层 = 全局集合 + 默认入组；user 内 = 该 user 额外追加），命名一致性优于结构歧义。

### Decision 3: `users.<name>.sudo` 三态

| 值 | 行为 |
|----|------|
| `True`（默认） | 入 `sudo` group，沿用 `/etc/sudoers` 中 `%sudo ALL=(ALL:ALL) ALL` |
| `False` | 不入 sudo group，从顶层 `groups` 加入集中显式扣掉 `sudo` |
| `{"nopasswd": True}` | 入 sudo group + 写 `/etc/sudoers.d/90-<name>` 一行 `<name> ALL=(ALL:ALL) NOPASSWD:ALL`，0440 权限 |

砍掉 `{"nopasswd": False}`：与 `True` 等价，无信息量。

### Decision 4: `disable_root_login` 命名与联动

字段名 **`disable_root_login`**（不用 `lock_root` / `root.locked`）— 命名直白表达"禁登录"意图，避免读者疑惑"锁了之后 sudo 还能用吗"。

`disable_root_login: true` 时框架做两件事：
1. chroot 内 `passwd -l root` → `/etc/shadow` root 字段加 `!` 前缀
2. 写 `/etc/ssh/sshd_config.d/10-flange.conf` 内容 `PermitRootLogin no`

**adb 调试通道不受影响**：adbd 不走 PAM，systemd 直接以 root 拉起；这是显式 feature，spec 中明确声明。

### Decision 5: shell 体验通过 overlay 实现，不在 `_configure_users` 内动态生成

新增两个 overlay 文件：
- `components/rootfs/overlay/etc/skel/.bashrc` — ubuntu 默认 skel 但 completion 块取消注释；新建用户 `useradd -m` 时自动从 skel 拷到家目录
- `components/rootfs/overlay/root/.bashrc` — 跟 skel 同款 + root 红色 PS1

**为什么不动态生成**：overlay 路径是声明式的、可 diff、可 review；动态写文件需要在 chroot 内 sed，调试更难。代价仅是若新增 user 体验需要改文件而非改代码。

`/etc/bash.bashrc` 已由 ubuntu-base 提供，且包含 completion 启用片段，无需覆盖。

### Decision 6: 抬到基类的范围

抬到 `builder/rootfs.py`（`RootfsBuilder`）：
- `_set_root_password(rootfs_dir, password)`
- `_verify_root_password(rootfs_dir)`
- `_configure_users(rootfs_dir, config)` — 新

`_build_phase2` 留在平台子类，但内部对账号配置的调用收敛为：

```python
self._configure_users(rootfs_dir, config)
# _configure_users 内部已包含：groupadd → useradd → chpasswd → sudoers.d
#                              → root_password → disable_root_login
```

平台子类不再直接调 `_set_root_password` / 不再 `chpasswd` / 不再读 `root_password`。

`builder/recovery.py` 维持现有行为 — recovery 路径不走 `_configure_users`，仅做最小 rootfs 准备。

### Decision 7: cache hash 输入

`builder/cache.py` rootfs 阶段 hash 改为：

```python
account_subtree = {
    "root_password":      rootfs_cfg.get("root_password", ""),
    "disable_root_login": rootfs_cfg.get("disable_root_login", False),
    "users":              rootfs_cfg.get("users", {}),
    "default_user":       rootfs_cfg.get("default_user"),
    "groups":             rootfs_cfg.get("groups", []),
}
h.update(json.dumps(account_subtree, sort_keys=True).encode())
```

**为什么用 `json.dumps(sort_keys=True)`**：dict 顺序无关、嵌套结构稳定序列化、跨 Python 版本一致。

### Decision 8: bash-completion 加入 base 包集

`bash-completion` 加到 `package_sets.base`，约 1MB 增量。**为什么进 base 而非 debug**：completion 是日常交互体验的一部分，不属于调试工具；若进 debug 则 release 镜像上 sudo<TAB> 不可用，跟 ubuntu 桌面体验不一致。

## Risks / Trade-offs

- **Risk**：用户启用 `disable_root_login` 但同时没声明 `users` / `default_user` → 镜像 root 锁了又没普通用户可登录，仅 adb 可达，串口 / SSH 全失联
  → **Mitigation**：`_configure_users` 在 `disable_root_login=true` 时若 `users` 为空，**直接 raise `ValueError`** — 拒绝构建，把错暴露在编译期而非烧录后

- **Risk**：板级 board 在 `BOARD["rootfs"]["users"]` 中覆盖单个 user 字段时，dict 浅合并把 `users` 整体替换 → 框架默认 user 丢失
  → **Mitigation**：参考现有 `package_set` 的 `+package_set:debug` 增量语法（见 `components/rootfs/config.py`），spec 中明确 `users` 字段在 board 层应**整段重写**而非 patch；想做"只覆盖默认 user 的 sudo"则需写完整的 `users: {flange: {..., sudo: ...}}`。这是与现有 schema 风格一致的取舍 — 不引入新增量语法

- **Risk**：cache hash 输入新增字段 → 一次性触发所有现有 board 的 rootfs 全量重建
  → **Mitigation**：可接受 — 一次重建后即稳定；hash 覆盖账号子树是正确性必需，不应回避

- **Trade-off**：`groups` 顶层预创会在所有 board 上产生若干"空 group"（如 `i2c` 在没有 i2c-tools 的板上） → 体积影响可忽略（/etc/group 多几行），换来可预测行为

- **Trade-off**：选 overlay 而非动态生成 `.bashrc` → 改 shell 体验需要改文件（review 友好）但不能按 user 个性化；本期不需要个性化能力，未来若需要再演进

## Migration Plan

1. 实施顺序：基类改造 → 配置 schema 扩展 → overlay 文件 → cache hash → 平台子类清理 → 默认值切换 → 测试
2. 切换路径：现有 board 不需改 config 即获得新默认 — root 完全锁定 + 默认用户 `flange/flange`。需要旧形态（root 可登录、无普通用户）的板，板级显式声明 `"root_password": "<pw>", "disable_root_login": False, "users": {}` 整段覆盖
3. 回滚：板级回退到旧形态见上；框架层回滚把 base config 中的默认值改回 `root_password="1234"` / `disable_root_login=False` / `users={}` / `default_user=None` 即可，逻辑代码与 overlay 保留
4. 验证矩阵：
   - 旧 board 不动配置 → 镜像 hash 改变（cache 输入扩了），新行为：root 锁定 + flange/flange 用户 + 两个 .bashrc + `bash-completion` 包
   - 板级显式 `users={}` + `disable_root_login=False` + `root_password="1234"` → 退回到旧 root-only 形态
   - 新 board 声明自定义 `users` + `default_user` → ssh 该用户成功、`sudo -s` 进 root 成功
   - 新 board 声明 `disable_root_login: true` → ssh root 被 sshd 拒绝、串口 root 登录失败、adb shell 仍正常
   - 新 board 声明 `users.<name>.sudo: {nopasswd: true}` → `/etc/sudoers.d/90-<name>` 存在且 0440
   - `disable_root_login: true` 但 `users` 为空（板级误覆盖） → 构建期 `ValueError`

## Open Questions

无。所有设计点已与用户在 explore 阶段达成一致。
