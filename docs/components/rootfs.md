# rootfs 构建器

## 概述

内置 Ubuntu 路径以 ubuntu-base + APT + overlay + DEB 组成两阶段 rootfs；外部发行版层可替换基础与安装后端，见[多层工作区](../layers.md)。
按 `architecture.userspace` 选择 QEMU，按 `rootfs.image_format` 输出 ext4 或 UBI。[ATK-RK3506B](../boards/atk-rk3506b.md) 与 [Luckfox](../boards/luckfox-pico-pro-max.md) 使用 ARM32 / SPI NAND / UBIFS；块设备目标通常使用 ext4。

## 关键设计要点

- **package_sets 基线**：`components/rootfs/config.jsonnet` 定义 `rootfs.package_sets`，platform/board 通过 `rootfs.package_set` 选择，product/variant 条件使用 Jsonnet 表达；求值边界展开为 `rootfs.packages` 扁平列表
- **Phase 1 — base**：解压 ubuntu-base，chroot 内 `apt-get install` `rootfs.packages`；tar 存 base cache，下次跳过
- **活树与产物分离**：解包、快照恢复、APT、定制和成像读取同一容器原生 `/var/tmp` 活树，不跟随 TMPDIR；最终镜像、清单与平台辅助文件仍写组件持久化工作目录。该边界同时适用于 recovery，避免宿主共享存储的权限/UID 语义影响目标系统
- **Phase 2 顺序**（`_build_phase2`）：报告选定的 runtime 软件包（同时核对发行版/ABI） → 额外 deb → Phase 2 软件包 → kernel modules → linux-headers deb（`kernel.headers_package` 开启时，见 [kernel 构建器](kernel.md)）→ 固件/面板文件 → overlay → locale → 账户 → hostname → 包清单
- **App 报告**：engine 在 rootfs 前构建 App 闭包并传入 AppBuildReport；`rootfs.custom_packages` 选择需要安装的运行依赖集合，拒绝缺失或损坏报告
- **`extra_debs`**（基类 `_install_extra_debs`）：声明式下载并安装第三方 deb（不在 Ubuntu 官方源、又不便发布到 app 体系的预编译包）；通过 [源码管理 SourceManager](../build-system-design.md) sha256 校验，批量 `dpkg -i` 后 `ldconfig`
- **`extra_firmware`**（基类 `_install_extra_firmware`）：通过 `source: {name, subpath}` 引用顶层 `sources`，或使用带 SHA256 的下载描述符；同一来源经 SourceManager 复用，`files` 元素支持 `str` 或 `{src, dest}` dict 形态做重命名（如给无后缀 vendor 固件统一补 `.bin`）
- **继承**：`RockchipRootfsBuilder` / `AllwinnerA733RootfsBuilder` → `RootfsBuilder` → `ComponentBuilder`；`apply_overlays` / `_install_extra_debs` / `_install_extra_firmware` 复用基类
- **chroot**：`ChrootContext` 挂载 proc/sys 并绑定 dev/pts，初始化失败回滚，退出恢复原有临时配置并逆序卸载；主异常不被清理错误替换。活树删除前还会检查剩余挂载
- **ARM32**：SoC 配置选择 Ubuntu Base armhf 与 `qemu-arm-static`；Docker 同时提供 armhf 运行库和 gcc-10 hard-float 工具链，宿主机无需 ARM32 环境
- **UBI**：`rootfs.image_format=ubi` 时先以 `mkfs.ubifs` 按 min-I/O/LEB/max-LEB 生成 volume，再用 `ubinize` 按 PEB/subpage/VID offset 封装 `rootfs.ubi`；`space_fixup=true` 对应 `mkfs.ubifs -F`，首次挂载可修复 NAND 空闲页
- **API 文件系统**：rootfs 固化 `/proc`、`/sys`、`/dev`、`/dev/pts`、`/run`、`/sys/kernel/config` 等挂载点，保证 systemd 与模块化 USB gadget 冷启动可用
- **用户与 sudo 体系**（基类 `_configure_users`，跨平台共享）：声明式配置 `rootfs.{users, default_user, disable_root_login, root_password, groups}`；`default_user` 非空时优先创建为 UID 1000，并使用同名、GID 1000 的 user private group（用户私有组），编号冲突直接构建失败。`groups` 顶层声明同时承担“幂等 `groupadd -r -f` 预创 system group（系统组）”与“每个 user 默认入组集”双职，缺失组不占普通用户 GID 范围。每 user 的 `sudo` 三态：`True`（默认入 sudo group）/ `False`（从入组集中扣除 `sudo`）/ `{"nopasswd": True}`（额外写 `/etc/sudoers.d/90-<name>` 0440 NOPASSWD ALL，构建期 `visudo -cf` 校验）。`disable_root_login: true` 同时锁 `/etc/shadow`（`passwd -l root`）与写 `/etc/ssh/sshd_config.d/10-flange.conf` 的 `PermitRootLogin no`，但 **adb 调试通道不受影响**（adbd 不走 PAM）；该开关启用但 `users` 空时框架在构建期 `raise ValueError`。`bash-completion` 进 base 包；overlay `etc/skel/.bashrc` 与 `root/.bashrc` 同款配置（PS1、ls/grep 彩色、`ll/la/l` alias、`sudo<TAB>` completion），让 ssh 登录与 `adb shell` 拿到的 root bash 体验对齐 Ubuntu Desktop

## 关键代码位置

- [`builder/rootfs_base.py`](../../builder/rootfs_base.py) — Phase 1 的统一计划与执行
- [`builder/rootfs_storage.py`](../../builder/rootfs_storage.py) — 原生工作树作用域与清理门禁
- [`builder/rootfs.py:RootfsBuilder._build_phase2`](../../builder/rootfs.py) — Phase 2 个性化
- [`builder/rootfs.py:RootfsBuilder.apply_overlays`](../../builder/rootfs.py) — overlay
- [`builder/rootfs.py:RootfsBuilder._install_extra_debs`](../../builder/rootfs.py) — 第三方 deb
- [`builder/rootfs.py:RootfsBuilder._configure_users`](../../builder/rootfs.py) — 账号一体化
- [`builder/chroot.py:ChrootContext`](../../builder/chroot.py) — chroot

## 易踩坑

- base cache 同时依赖 ubuntu-base 摘要、APT 输入、推荐包策略、架构、模拟器、环境和配方；详见[rootfs 两阶段缓存](../build-system-design.md)
- 大小写敏感卷不等于 Linux 原生权限语义；rootfs 活树自动使用容器原生存储。需要同时检查 Docker 磁盘与宿主产物卷空间，见[开发指南](../development-guide.md#构建存储与磁盘空间)
- _modules_staging 的 source/build symlink 须由内核构建器预先删除，详见 [kernel 构建器](kernel.md)
- `disable_root_login: true` 锁定常规账户登录，不能关闭不经 PAM 的 ADB root 通道；发布配置需另行决定是否启用 ADB
- 当前 standalone adbd 配合 `ADBD_SHELL=/bin/bash` 启动 login bash，经 `/root/.profile` 读取 `.bashrc`；公共环境仍由 `/etc/bash.bashrc` 补齐。旧版 vendor adbd 的 `argv[0]="sh"` / POSIX 行为不代表当前入口，详见 [adbd](../../components/app/adbd/README.md)
- 账号子树（`users` / `default_user` / `disable_root_login` / `groups` / `root_password`）整体进 rootfs cache hash；改任一字段触发完整 rootfs 重建
- UBI 几何必须来自目标 NAND：`leb_size = peb_size - data_offset`，volume/预留 PEB 与分区容量均在构建期校验；不要从其他 SPI NAND 型号复制参数

## 挂载表与文件元数据

Phase 2 前统一移除基础归档自带的 fstab，新建与快照恢复路径一致。
App、overlay 或定制钩子提供的 `/etc/fstab` 原样保留，空文件也有明确意义；仅在文件不存在时生成板级默认项。
基础快照保留 UID/GID、权限、符号链接、xattrs/capabilities 与 ACL，损坏快照不能命中缓存。

overlay 与模块合入不能把宿主 UID 1000 带成设备系统目录属主。TX2 实板在修复后检查了
`/etc`、`/usr` 等属主为 root、`/root` 为 0700、无失败服务；这不替代其他文件系统的独立验证。
老版 Ubuntu 的 SSH 主配置不读取 drop-in 时，需要平台兼容处理，见 [TX2](../platforms/nvidiategra186.md)。
