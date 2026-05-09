"""RootfsBuilder — 各平台 rootfs 构建器的公共基类。

通用能力（与平台无关）：
  - apply_overlays：platform overlay → board overlay 两层覆盖
  - extra_debs：下载第三方 deb 并安装
  - extra_firmware：从外部仓库拉取固件文件并写入 rootfs
  - panel_firmware：把板级 panel init 文本源编译为 panel.bin 写入 rootfs
  - configure_users：创建 group / 普通用户 / sudo 配置 / root 密码 /
                     disable_root_login（含 chroot 内 chpasswd / passwd -l /
                     /etc/sudoers.d 写入 / sshd_config drop-in 写入）
"""

import math
import shutil
from pathlib import Path
from builder.base import ComponentBuilder
from builder.chroot import ChrootContext
from builder.docker import BuildError
from builder.firmware_panel import encode_file as _encode_panel_file
from builder.partition.size import resolve_image_size


# 写入 /etc/sudoers.d/ 时统一使用 0440，与 visudo 默认权限和 sudo 自身的
# 严格性检查一致；权限错则 sudo 直接拒绝读该文件，提权静默失败。
_SUDOERS_D_MODE = 0o440


class RootfsBuilder(ComponentBuilder):
    """rootfs 构建器基类。

    各平台子类继承此类，获得通用 rootfs 能力，再叠加平台特定逻辑。
    """

    def apply_overlays(self, rootfs_dir: Path, config: dict):
        """按优先级顺序应用 overlay 文件：rootfs → platform → board。

        优先级从低到高，后应用的同名文件覆盖先应用的：
          components/rootfs/overlay/          与 OS/发行版绑定，所有平台共用
          components/platform/<p>/overlay/    与芯片平台绑定
          components/board/<b>/overlay/       与具体板子绑定
        """
        for overlay_dir, label in [
            (Path("components/rootfs/overlay"),                          "rootfs"),
            (Path(f"components/platform/{config['platform']}/overlay"),  "platform"),
            (Path(f"components/board/{config['board']}/overlay"),        "board"),
        ]:
            if overlay_dir.exists() and any(overlay_dir.iterdir()):
                self._status(f"复制 {label} overlay 文件...")
                self.docker.run_privileged(
                    ["cp", "-a", f"{overlay_dir}/.", str(rootfs_dir)])

    def _partition_size_mb(self, config: dict, name: str) -> int:
        """从 config 中读取指定分区的初始镜像大小（MiB）。"""
        for entry in config.get("partitions", {}).get("entries", []):
            if entry["name"] == name:
                return resolve_image_size(entry).mb
        raise KeyError(f"partitions.entries 中未定义分区: {name}")

    def _ensure_rootfs_fits_image(self, rootfs_dir: Path, image_size_mb: int):
        """构建 ext4 前检查 rootfs 内容是否能放入初始镜像。

        使用 du 统计目录占用，并额外保留 20% 或至少 128MiB 空间，避免
        mke2fs 在最后阶段才因空间不足失败。
        """
        result = self.docker.run(
            ["du", "-sm", str(rootfs_dir)],
            capture=True,
        )
        used_mb = int(result.stdout.split()[0])
        reserve_mb = max(math.ceil(used_mb * 0.2), 128)
        required_mb = used_mb + reserve_mb
        if required_mb > image_size_mb:
            raise BuildError(
                f"rootfs 内容约 {used_mb}MB，按保留空间需要至少 "
                f"{required_mb}MB；当前 image_size 仅 {image_size_mb}MB，"
                f"请增大 rootfs 分区 image_size。"
            )

    def _install_extra_debs(self, rootfs_dir: Path, config: dict):
        """下载并安装第三方 deb 包到 rootfs。

        config["rootfs"]["extra_debs"] 格式：
          [
            {
              "name": "xserver-xorg-img-bxm",
              "url": "https://github.com/.../xserver-xorg-img-bxm_1.21.1-2_arm64.deb",
              "sha256": "<hex>",
              "filename": "xserver-xorg-img-bxm_1.21.1-2_arm64.deb",  # 可选
            },
          ]

        name 用于缓存目录隔离，必须全局唯一。deb 在 app deb 之后、
        kernel modules 之前安装，与 Phase 2 其他 deb 共享 dpkg -i 流程。
        """
        extra_debs = config.get("rootfs", {}).get("extra_debs", [])
        if not extra_debs:
            return
        deb_files = []
        for deb_cfg in extra_debs:
            name = deb_cfg["name"]
            self._status(f"下载外部 deb: {name}")
            deb_path = self.source.ensure_extra_deb(name, deb_cfg)
            deb_files.append(deb_path)
        deb_names = [d.name for d in deb_files]
        self._status(f"安装 {len(deb_files)} 个外部 deb: {', '.join(deb_names)}")
        deb_tmp = rootfs_dir / "tmp" / "flange-extra-debs"
        deb_tmp.mkdir(parents=True, exist_ok=True)
        for deb in deb_files:
            shutil.copy2(deb, deb_tmp)
        with ChrootContext(rootfs_dir, self.docker) as chroot:
            deb_list = [f"/tmp/flange-extra-debs/{d.name}" for d in deb_files]
            chroot.run(["dpkg", "-i", "--force-confnew"] + deb_list,
                       label=f"dpkg -i ({len(deb_files)} 个外部包)...")
            chroot.run(["ldconfig"], label="ldconfig...")
        shutil.rmtree(deb_tmp)

    def _install_extra_firmware(self, rootfs_dir: Path, config: dict):
        """安装额外固件文件到 rootfs。

        config["rootfs"]["extra_firmware"] 是声明 list，每条 entry：

          - 必填：``name`` / ``files`` / ``dest``
          - 可选：``source``（来源类型，默认 ``"repo"``）；其余字段按 source
            类型语义化，详见 ``SourceManager.ensure_extra_firmware`` 的注释。

        典型形态：

          [
            # source="repo"（默认） — 从外部 git 仓库取
            {
              "name": "radxa",
              "repo": "https://github.com/radxa-pkg/radxa-firmware",
              "branch": "main",
              "repo_subdir": "radxa-firmware/lib/firmware",  # 仓库内子目录作为 files 的根
              "files": ["brcm/brcmfmac43430-sdio.txt", ...],
              "dest": "lib/firmware",   # 相对 rootfs 根目录，默认 lib/firmware
            },
            # source="kernel" — 从 BSP 内核源码内已 vendor 的 blob 取
            {
              "name": "mali-csf",
              "source": "kernel",
              "repo_subdir": "drivers/gpu/arm/bifrost",
              "files": ["mali_csffw.bin"],
              "dest": "lib/firmware/arm/mali/arch10.8",
            },
            # source="oot:<name>" — 从同 build 已 ensure 的 OOT 模块源取，
            # 适用于 vendor WiFi/BT 包同时携带固件 blob 的场景（如 rkwifibt）
            {
              "name": "rkwifibt-rtl8852be",
              "source": "oot:rkwifibt",
              "repo_subdir": "firmware/realtek/RTL8852BE",
              # files 元素支持 dict 形态做重命名（例如补 .bin 后缀）
              "files": [
                {"src": "rtl8852bu_fw",     "dest": "rtl8852bu_fw.bin"},
                {"src": "rtl8852bu_config", "dest": "rtl8852bu_config.bin"},
              ],
              "dest": "lib/firmware/rtl_bt",
            },
          ]

        files 元素两种形态：
          - str：路径同时作 src 和 dest 相对路径，原名拷贝（保留目录结构）
          - dict {src, dest}：src 是相对 repo_subdir 的源路径，dest 是相对
            ``dest`` 字段的目标路径（用于重命名或扁平化）

        例：repo_subdir="radxa-firmware/lib/firmware", files=["brcm/foo.txt"],
            dest="lib/firmware" → rootfs/lib/firmware/brcm/foo.txt
        """
        extra_firmware = config.get("rootfs", {}).get("extra_firmware", [])
        if not extra_firmware:
            return
        # 收集所有 entry 用到的 component source 类型，按需 ensure 对应组件
        # 源码树。已被 cache 依赖图保证 kernel/bootloader 先于 rootfs build，
        # 此处只是拿 path，幂等。
        needed_sources = {fw.get("source", "repo") for fw in extra_firmware}
        component_sources: dict[str, Path] = {}
        for st in needed_sources & {"kernel", "bootloader"}:
            component_sources[st] = self.source.ensure(st, config)
        # OOT 源：source="oot:<name>" 引用 kernel.oot_sources 中已声明的源。
        # 过滤 resolve_conditions 递归注入的 product/variant 伪 key（详见
        # KernelBuilder._oot_sources_config 注释）。
        raw_oot = config.get("kernel", {}).get("oot_sources", {}) or {}
        oot_sources = {k: v for k, v in raw_oot.items()
                       if k not in ("product", "variant")
                       and isinstance(v, dict)}
        for st in needed_sources:
            if not st.startswith("oot:"):
                continue
            oot_name = st.split(":", 1)[1]
            if oot_name not in oot_sources:
                raise ValueError(
                    f"extra_firmware 引用 source={st!r}，但 kernel.oot_sources "
                    f"未声明 {oot_name!r}")
            component_sources[st] = self.source.ensure_oot_source(
                oot_name, oot_sources[oot_name])
        for fw in extra_firmware:
            name = fw["name"]
            source_type = fw.get("source", "repo")
            if source_type == "repo":
                self._status(f"同步固件仓库: {name}")
            else:
                self._status(f"同步固件源（{source_type} 内 vendor）: {name}")
            fw_dir = self.source.ensure_extra_firmware(
                name, fw, component_sources=component_sources)
            repo_subdir = fw.get("repo_subdir", "")
            fw_base = fw_dir / repo_subdir if repo_subdir else fw_dir
            dest_base = rootfs_dir / fw.get("dest", "lib/firmware")
            for entry in fw.get("files", []):
                if isinstance(entry, dict):
                    src_rel, dest_rel = entry["src"], entry["dest"]
                else:
                    src_rel = dest_rel = entry
                src = fw_base / src_rel
                if not src.exists():
                    raise FileNotFoundError(
                        f"固件文件不存在: {src}（仓库: {name}）")
                dest = dest_base / dest_rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest)
            self._status(f"已安装 {len(fw.get('files', []))} 个固件文件 ({name})")

    # ------------------------------------------------------------------
    # 用户 / sudo / root 账号一体化配置
    # ------------------------------------------------------------------

    @staticmethod
    def _real_users(rootfs_cfg: dict) -> dict:
        """过滤 rootfs.users 字典，去掉 resolve_conditions 在每层 dict 上
        注入的 ``product`` / ``variant`` 伪 key（merge.py:141-142），仅保留
        值为 dict 的真正用户条目。

        与 KernelBuilder._oot_sources_config 同病同治；不过滤就会在
        ``for name, spec in users.items()`` 循环里取到字符串 spec。
        """
        raw = rootfs_cfg.get("users") or {}
        return {k: v for k, v in raw.items()
                if k not in ("product", "variant")
                and isinstance(v, dict)}

    def _validate_account_config(self, rootfs_cfg: dict) -> None:
        """对账号子树做编译期校验。

        - default_user 非 None 时必须存在于 users 键集（过滤伪 key 后）
        - disable_root_login=True 且 users 为空时拒绝构建（避免镜像无任何
          普通用户可登录、串口/SSH 全失联；adb 仍可达不算"可登录"）
        """
        users = self._real_users(rootfs_cfg)
        default_user = rootfs_cfg.get("default_user")
        if default_user is not None and default_user not in users:
            raise ValueError(
                f"rootfs.default_user={default_user!r} 不在 rootfs.users 中；"
                f"已声明用户: {sorted(users.keys()) or '(空)'}")
        if rootfs_cfg.get("disable_root_login") and not users:
            raise ValueError(
                "rootfs.disable_root_login=True 但 rootfs.users 为空 — "
                "镜像将无任何普通用户可登录、串口/SSH 全失联（adb 仍可达"
                "但不构成可登录通道），请至少声明一个 user 后再启用。")

    def _configure_users(self, rootfs_dir: Path, config: dict):
        """创建 group / 用户 / 设密码 / sudo / 锁 root / sshd drop-in。

        编排顺序（与 spec rootfs-user-system 对齐）：
          1) 配置校验（_validate_account_config）
          2) groupadd -f 全部顶层 groups（幂等）
          3) for each user:
               useradd -m -s <shell> -U <name>
               usermod -aG <merged> <name>
               chpasswd 写密码
               若 sudo=={"nopasswd": True} 写 /etc/sudoers.d/90-<name>
          4) 若声明 root_password 则调用 _set_root_password
          5) 若 disable_root_login 则 passwd -l root 并写 sshd drop-in
          6) 末尾硬校验：shadow root 行 + sshd drop-in 文件 + visudo -cf

        旧 board（不写 users / default_user / disable_root_login）行为：
        仅走 (1) (2) (4)，与本次改造前完全一致。
        """
        rootfs_cfg = config.get("rootfs") or {}
        self._validate_account_config(rootfs_cfg)

        groups = list(rootfs_cfg.get("groups") or [])
        users = self._real_users(rootfs_cfg)
        root_password = rootfs_cfg.get("root_password")
        disable_root_login = bool(rootfs_cfg.get("disable_root_login"))

        with ChrootContext(rootfs_dir, self.docker) as chroot:
            # (2) 预创顶层 groups（即便没有 user，下游 udev rule 也可能
            #     依赖 i2c / spi / gpio 等 group 存在）
            if groups:
                self._status(f"创建 group ({len(groups)} 个): "
                             f"{', '.join(groups)}")
                for g in groups:
                    chroot.run(["groupadd", "-f", g])

            # (3) 创建用户
            sudoers_d_written: list[str] = []
            for name, spec in users.items():
                spec = spec or {}
                shell = spec.get("shell", "/bin/bash")
                self._status(f"创建用户 {name!r} (shell={shell})")
                # -m 创家目录（自动从 /etc/skel 拷贝）；-U 创建同名主组；
                # -s 显式 shell；--badname 容忍非传统命名规则
                chroot.run(["useradd", "-m", "-U", "-s", shell, name])

                merged = self._merge_user_groups(groups, spec)
                if merged:
                    chroot.run(["usermod", "-aG", ",".join(merged), name])

                password = spec.get("password")
                if password is not None:
                    chroot.run(["chpasswd"], input=f"{name}:{password}\n")

                sudo_spec = spec.get("sudo", True)
                if isinstance(sudo_spec, dict) and sudo_spec.get("nopasswd"):
                    self._write_sudoers_nopasswd(rootfs_dir, name)
                    sudoers_d_written.append(name)

            # (4) root 密码
            if root_password:
                self._set_root_password_in_chroot(chroot, root_password)

            # (5) disable_root_login：锁 shadow + 写 sshd drop-in
            if disable_root_login:
                self._status("锁定 root 登录通道（passwd -l root + sshd drop-in）")
                chroot.run(["passwd", "-l", "root"])
                self._write_sshd_no_root_drop_in(rootfs_dir)

            # (6) 硬校验
            if root_password:
                self._verify_root_password(rootfs_dir,
                                          expect_locked=disable_root_login)
            elif disable_root_login:
                # 无 root_password 但锁了 root：shadow 字段应当以 ! 起首
                self._verify_root_locked(rootfs_dir)
            if disable_root_login:
                self._verify_sshd_no_root(rootfs_dir)
            for name in sudoers_d_written:
                # visudo -cf 在 chroot 内对 drop-in 单文件做语法校验；语法错时
                # 整个 sudoers.d 被 sudo 拒绝读取，提权失效。
                chroot.run(["visudo", "-cf", f"/etc/sudoers.d/90-{name}"])

    def _merge_user_groups(self, top_groups: list, spec: dict) -> list:
        """合并 user 实际入组集合：
          - 先取顶层 groups
          - 若 user.sudo == False 则从中扣除 "sudo"
          - 再追加 user.groups 中的额外项（去重保序）
        """
        sudo_spec = spec.get("sudo", True)
        merged: list[str] = []
        for g in top_groups:
            if g == "sudo" and sudo_spec is False:
                continue
            merged.append(g)
        for g in (spec.get("groups") or []):
            if g not in merged:
                merged.append(g)
        return merged

    def _write_sudoers_nopasswd(self, rootfs_dir: Path, name: str):
        """写入 /etc/sudoers.d/90-<name>，单行 NOPASSWD ALL，0440 root:root。"""
        path = rootfs_dir / "etc" / "sudoers.d" / f"90-{name}"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{name} ALL=(ALL:ALL) NOPASSWD:ALL\n")
        # docker 内文件已是 root 所有；权限设 0440
        self.docker.run_privileged(["chmod", "0440", str(path)])
        self.docker.run_privileged(["chown", "root:root", str(path)])

    def _write_sshd_no_root_drop_in(self, rootfs_dir: Path):
        """写入 /etc/ssh/sshd_config.d/10-flange.conf，禁 root SSH 登录。

        sshd 加载顺序：/etc/ssh/sshd_config 末尾 ``Include sshd_config.d/*.conf``，
        drop-in 设定覆盖主配置；ubuntu-base 默认即如此。
        """
        path = rootfs_dir / "etc" / "ssh" / "sshd_config.d" / "10-flange.conf"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "# flange: disable_root_login=true 下禁止 root 通过 SSH 登录。\n"
            "# adb 调试通道不受影响（adbd 不走 PAM）。\n"
            "PermitRootLogin no\n"
        )

    def _set_root_password_in_chroot(self, chroot, password: str):
        """在已打开的 chroot 上下文中设置 root 密码。

        与 _set_root_password 不同：不重复打开 ChrootContext，避免
        嵌套挂载。供 _configure_users 内部统一使用。
        """
        self._status("设置 root 密码...")
        chroot.run(["chpasswd"], input=f"root:{password}\n")

    def _set_root_password(self, rootfs_dir: Path, password: str):
        """设置 root 密码（独立入口，会自开 ChrootContext）。

        历史接口；新代码应优先走 _configure_users 一次性完成全部账号编排。
        保留此方法仅为内部复用与可能的极小路径调用。

        chpasswd 在 chroot 内执行（通过 qemu-user-static 模拟 arm64），
        读 stdin 的 user:password 行写入 /etc/shadow。

        使用 ChrootContext 确保 /proc /sys /dev 已挂载：chpasswd 通过
        libcrypt 生成盐值时可能读 /dev/urandom，缺失时会静默失败或
        产生无效哈希。

        执行后立即读 /etc/shadow 硬校验 root 行：若密码字段仍是
        锁定态（!/*/空）或格式非法，抛错而非静默产生不可登录镜像。
        """
        with ChrootContext(rootfs_dir, self.docker) as chroot:
            self._set_root_password_in_chroot(chroot, password)
        self._verify_root_password(rootfs_dir)

    def _verify_root_password(self, rootfs_dir: Path,
                               expect_locked: bool = False):
        """校验 /etc/shadow 中 root 行密码字段。

        expect_locked=True 时：允许字段以 ``!`` 起首（passwd -l 后正常状态），
        但去掉 ``!`` 后剩余部分仍应是合法 hash（即"先设密码再锁定"路径）。
        expect_locked=False 时：字段必须是合法 hash。
        """
        shadow = rootfs_dir / "etc" / "shadow"
        if not shadow.exists():
            raise RuntimeError(f"/etc/shadow 不存在: {shadow}")
        for line in shadow.read_text().splitlines():
            if not line.startswith("root:"):
                continue
            fields = line.split(":")
            if len(fields) < 2:
                raise RuntimeError(
                    f"/etc/shadow root 行格式错误: {line!r}")
            pw_hash = fields[1]
            if expect_locked:
                if not pw_hash.startswith("!"):
                    raise RuntimeError(
                        f"disable_root_login=True 但 /etc/shadow root 字段未锁定: "
                        f"{pw_hash[:40]!r}")
                inner = pw_hash.lstrip("!")
                if not inner.startswith("$"):
                    raise RuntimeError(
                        f"root 密码哈希格式非预期（去 ! 前缀后）: "
                        f"{inner[:40]!r}")
                self._status(
                    f"root 密码已写入并锁定 (hash: {pw_hash[:13]}...)")
                return
            if pw_hash in ("", "!", "*", "!!", "x"):
                raise RuntimeError(
                    f"root 密码未生效：/etc/shadow 字段仍为 {pw_hash!r}，"
                    f"chpasswd 未成功写入（检查 chroot/qemu 环境）")
            if not pw_hash.startswith("$"):
                raise RuntimeError(
                    f"root 密码哈希格式非预期: {pw_hash[:40]!r}")
            self._status(f"root 密码已写入 (hash: {pw_hash[:12]}...)")
            return
        raise RuntimeError("/etc/shadow 中未找到 root 账号行")

    def _verify_root_locked(self, rootfs_dir: Path):
        """无 root_password 但 disable_root_login=True 时的轻量校验：
        仅要求 root 行的密码字段以 ! 起首，对内容形式不做要求。"""
        shadow = rootfs_dir / "etc" / "shadow"
        for line in shadow.read_text().splitlines():
            if line.startswith("root:"):
                pw = line.split(":")[1] if ":" in line else ""
                if not pw.startswith("!"):
                    raise RuntimeError(
                        f"disable_root_login=True 但 /etc/shadow root 字段未锁定: "
                        f"{pw[:40]!r}")
                return
        raise RuntimeError("/etc/shadow 中未找到 root 账号行")

    def _verify_sshd_no_root(self, rootfs_dir: Path):
        path = rootfs_dir / "etc" / "ssh" / "sshd_config.d" / "10-flange.conf"
        if not path.exists():
            raise RuntimeError(
                f"disable_root_login=True 但 sshd drop-in 缺失: {path}")
        content = path.read_text()
        if "PermitRootLogin no" not in content:
            raise RuntimeError(
                f"sshd drop-in 内容异常，缺少 'PermitRootLogin no': "
                f"{path}")

    def _install_panel_firmware(self, rootfs_dir: Path, config: dict):
        """编译并安装 panel firmware（mainline panel-mipi-dbi-spi 兼容）。

        config["rootfs"]["panel_firmware"] 格式：
          [
            {
              "src":  "firmware/panel/<name>.txt",   # 相对 components/board/<board>/
              "dest": "<compatible[0]>.bin",         # 相对 rootfs /lib/firmware/
            }
          ]

        text 源由 builder.firmware_panel 编码为 mainline panel.bin 二进制。
        dest 与 DT compatible 的最具体字符串相符——driver 不读 firmware-name
        属性，而是用 ``<compatible[0]>.bin`` 在 /lib/firmware/ 下查找。

        缺源文件 → 直接 raise FileNotFoundError，错误信息含 board 名 + 路径。
        """
        panel_firmwares = config.get("rootfs", {}).get("panel_firmware", [])
        if not panel_firmwares:
            return
        board = config["board"]
        board_root = Path(f"components/board/{board}")
        dest_base = rootfs_dir / "lib" / "firmware"
        for fw in panel_firmwares:
            src = board_root / fw["src"]
            if not src.exists():
                raise FileNotFoundError(
                    f"panel firmware 文本源不存在: {src} (board: {board})")
            payload = _encode_panel_file(src)
            dest = dest_base / fw["dest"]
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(payload)
            self._status(
                f"panel firmware: {src.name} → /lib/firmware/{fw['dest']} "
                f"({len(payload)} 字节)")
