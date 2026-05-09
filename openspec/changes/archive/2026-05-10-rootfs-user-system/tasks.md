## 1. 配置 schema 与校验

- [x] 1.1 在 `components/rootfs/config.py` 的 `ROOTFS["rootfs"]` 中新增 `disable_root_login: False`、`users: {}`、`default_user: None`、`groups: [...]` 字段；`groups` 默认值列入 `adm`、`dialout`、`cdrom`、`sudo`、`audio`、`video`、`plugdev`、`users`、`netdev`、`input`、`render`、`i2c`、`spi`、`gpio`
- [x] 1.2 在 `package_sets.base` 中新增 `bash-completion`
- [x] 1.3 实现配置校验函数（位置候选：`builder/rootfs.py` 内私有方法或独立 helper）：`default_user` 非 None 时必须存在于 `users` 键集；`disable_root_login=True` 且 `users` 为空时 raise `ValueError`，错误信息明确指出缺失项
- [x] 1.4 配置校验在 `_configure_users` 入口处调用一次，失败立即 raise（不继续构建）

## 2. RootfsBuilder 基类账号实现

- [x] 2.1 把 `_set_root_password` 与 `_verify_root_password` 从 `builder/platforms/rockchip/rootfs.py` 抬到 `builder/rootfs.py`（拷贝实现，注意 `ChrootContext` import）
- [x] 2.2 删除 `builder/platforms/allwinnera733/rootfs.py` 中的 `_set_root_password` / `_verify_root_password`
- [x] 2.3 删除 `builder/platforms/rockchip/rootfs.py` 中的 `_set_root_password` / `_verify_root_password`
- [x] 2.4 在 `builder/rootfs.py` 新增 `_configure_users(rootfs_dir, config)` 方法，编排顺序：调用配置校验 → `groupadd -f` 全部顶层 groups → 对每个 user 执行 `useradd -m -s <shell> -U <name>` → 计算合并 group 集（顶层 groups ∪ user.groups − (sudo if sudo=False)）→ `usermod -aG <merged>` → `chpasswd` 写密码 → 若 `sudo=={"nopasswd": True}` 写 `/etc/sudoers.d/90-<name>`（0440 root:root，单行 NOPASSWD ALL）→ 调用 `_set_root_password`（若声明 root_password）→ 若 `disable_root_login=True` 执行 `passwd -l root` 与写 `/etc/ssh/sshd_config.d/10-flange.conf`
- [x] 2.5 在 `_configure_users` 末尾增加硬校验：若 `disable_root_login=True` 检查 `/etc/shadow` root 行以 `!` 起首；检查 sshd drop-in 文件存在；写 sudoers.d 后用 `visudo -cf` 校验语法
- [x] 2.6 修改 `builder/platforms/rockchip/rootfs.py:_build_phase2`，把现有"读 root_password → 调 _set_root_password"段落整体替换为单行 `self._configure_users(rootfs_dir, config)`
- [x] 2.7 修改 `builder/platforms/allwinnera733/rootfs.py:_build_phase2` 做同样替换
- [x] 2.8 检视 `builder/recovery.py:217` 周边代码，确认 recovery 路径不调用 `_configure_users`，必要时在该函数注释明确"recovery 不走用户体系"

## 3. shell 体验 overlay

- [x] 3.1 创建 `components/rootfs/overlay/etc/skel/.bashrc`，内容基于 ubuntu-base 默认 skel 但取消 completion 块的注释（`# enable programmable completion` 段）；保留默认 alias、history 配置、prompt
- [x] 3.2 创建 `components/rootfs/overlay/root/.bashrc`，内容与 skel 同款 + root 专属 PS1（红色 `\h:\w\#` 风格）+ root 应有的 alias
- [x] 3.3 校验：构建一次镜像，挂载 rootfs ext4 后确认 `/etc/skel/.bashrc` 与 `/root/.bashrc` 落盘且内容符合预期；`bash-completion` 已安装（`dpkg -l bash-completion`）

## 4. cache hash 更新

- [x] 4.1 修改 `builder/cache.py:309` 周边逻辑：rootfs 阶段 hash 输入改为账号子树（`root_password` / `disable_root_login` / `users` / `default_user` / `groups`）的 `json.dumps(..., sort_keys=True)` 序列化
- [x] 4.2 更新 `builder/cache.py:68` 注释，反映新的 hash 输入范围
- [x] 4.3 局部测试：构造两份配置仅 `users.flange.password` 不同，确认 hash 输出不同；构造两份配置 dict key 排列不同但内容一致，确认 hash 输出相同

## 5. 端到端验证（通过实际构建）

- [x] 5.1 选 1 个 rockchip board 与 1 个 allwinner board，添加 `BOARD["rootfs"]["users"] = {"flange": {"password": "1234", "sudo": True}}` 与 `default_user = "flange"`，构建成功
- [x] 5.2 烧录上述镜像，串口或 ssh 登录 `flange` 用户成功，`sudo -s` 进入 root 成功，`sudo<TAB><TAB>` 触发 completion
- [x] 5.3 在某 board 上叠加 `disable_root_login: True`，构建烧录后验证：ssh root@设备 被拒绝（PermitRootLogin no），串口 root 登录失败，`adb shell` 仍正常进入 root bash
- [x] 5.4 在某 board 上叠加 `users.flange.sudo = {"nopasswd": True}`，验证 `/etc/sudoers.d/90-flange` 存在、内容正确、权限 0440
- [x] 5.5 不修改任何 board 配置，对一个未在 `BOARD["rootfs"]` 中覆盖账号字段的板构建：rootfs hash 改变（默认值切换 + cache 输入扩了，预期一次性），新行为生效 — `/etc/passwd` 含 `flange` 用户、`/etc/shadow` root 行以 `!` 起首、`/etc/ssh/sshd_config.d/10-flange.conf` 存在含 `PermitRootLogin no`、ssh root 被拒、ssh flange 后 `sudo -s` 进 root；adb shell 仍 root 可达
- [x] 5.6 构造非法配置（`disable_root_login=True` + `users={}`）确认构建立即 raise `ValueError`，错误信息可读

## 6. 文档与 wiki

- [x] 6.1 在 `wiki/` 适当位置（候选：rootfs 相关综述页）补一节 "用户与 sudo"，说明 schema、典型 board 配置示例、`disable_root_login` 与 adb 共存语义
- [x] 6.2 在 `components/rootfs/config.py` 顶部 docstring 中补字段速查（仿现有 `root_password` 段落风格）
