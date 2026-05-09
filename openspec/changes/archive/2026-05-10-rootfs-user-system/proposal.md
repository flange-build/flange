## Why

当前 rootfs 配置只有一个 `root_password` 字段，没有"普通用户"概念，整套体验跟 ubuntu 桌面差距很大：sudo 不可用（需要先建用户进 sudo group）、无法关闭 root 直接登录、bash 体验空白（无 PS1、无 alias、无 sudo<TAB> completion），开发者上手即觉粗糙。同时两套平台（rockchip、allwinnera733）各自实现了几乎相同的 `_set_root_password`，新加用户体系若不抬到基类会进一步重复。

## What Changes

- `components/rootfs/config.py` 新增 `users` / `default_user` / `disable_root_login` / 顶层 `groups` 字段，沿用 dict 浅合并语义供 board 覆盖
- 把 `_set_root_password` / `_verify_root_password` 从 `builder/platforms/{rockchip,allwinnera733}/rootfs.py` 抬到 `builder/rootfs.py` 基类，并新增 `_configure_users`：创建 group、创建用户、设密码、入 sudo group、可选写 `/etc/sudoers.d/90-<name>` NOPASSWD、可选锁 root 并写 `/etc/ssh/sshd_config.d/10-flange.conf`
- `package_sets.base` 加入 `bash-completion`
- `components/rootfs/overlay/` 新增 `etc/skel/.bashrc` 与 `root/.bashrc`，让新建用户与 root 都拥有 PS1、alias、bash-completion（含 sudo<TAB>）— 使 ssh 登录与 adb shell 体验对齐 ubuntu 桌面
- `builder/cache.py` rootfs hash 输入从 `root_password` 扩到整个 `users` / `default_user` / `disable_root_login` / `groups` / `root_password` 子树，避免改账号配置不触发重建
- **BREAKING**：framework base 默认值切换到"ubuntu 桌面心智模型" — `root_password=None` + `disable_root_login=True` + `users={"flange": {"password": "flange", "sudo": True}}` + `default_user="flange"`。所有未在板级 `BOARD["rootfs"]` 显式覆盖账号字段的 board，下次构建后自动获得：root 锁定（ssh + 串口被拒）、新增 `flange` 用户（密码 flange，可 `sudo -s`）、adb shell root 通道保留。板级可整段重写 `users` / 把 `disable_root_login` 设回 `False` 来回退到旧形态

## Capabilities

### New Capabilities
- `rootfs-user-system`: rootfs 中用户、密码、group、sudo、root 登录策略与 shell 体验的统一声明式配置体系

### Modified Capabilities
（无 — 现有 specs 中无涉及 rootfs 用户/密码的能力，`rootfs-auto-grow` 关注分区扩容、`platform-abstraction` 关注组件分层，均不重叠）

## Impact

- **代码**：
  - `components/rootfs/config.py`（schema 扩展）
  - `components/rootfs/overlay/{etc/skel/.bashrc,root/.bashrc}`（新增 overlay）
  - `builder/rootfs.py`（基类新增 `_configure_users` / `_set_root_password` / `_verify_root_password`）
  - `builder/platforms/rockchip/rootfs.py`、`builder/platforms/allwinnera733/rootfs.py`（删除重复实现，改调基类）
  - `builder/cache.py`（hash 输入扩展）
  - `builder/recovery.py`（确认 recovery 路径不调用 `_configure_users`，保持现有"不装 root_password"行为）
- **配置**：所有 board 的 `BOARD["rootfs"]` 兼容不变；启用新功能需显式声明 `users` / `default_user`
- **行为**：启用 `disable_root_login: true` 后，串口 / SSH 不再允许 root 直接登录；adb 调试通道**不受影响**（adbd 不走 PAM）— 这是显式 feature
- **依赖**：rootfs base 包多一个 `bash-completion`，镜像增量约 1MB

## 非目标

- **SSH key 注入**（`authorized_keys`）：本期不做，留给后续 change
- **password_hash 字段**：仅支持明文 `password`，与当前 `root_password` 一致；生产强密码管理由后续 change 处理
- **autologin / getty 自动登录**：`default_user` 仅作语义指针，不联动 getty 自动登录
- **adb shell 切换到 default_user**：明确保持 root，仅通过 overlay 让 root shell 体验追上 ssh + sudo -s
- **改写 adbd 二进制**：完全不动 adbd，仅靠 `/root/.bashrc` 对齐体验
