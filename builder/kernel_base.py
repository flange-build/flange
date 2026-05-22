"""内核构建器基类 — 提供跨平台共享的 out-of-tree 模块编译与安装逻辑。"""

import glob
import os
import shutil
from pathlib import Path
from builder.base import ComponentBuilder


class KernelBuilder(ComponentBuilder):
    """内核构建器基类。

    子类仍需实现 configure / compile / collect，
    并声明 ARCH / CROSS 类属性。
    基类提供 OOT 模块的编译与安装方法，以及大小写不敏感 FS 适配
    fragment 生成逻辑（macOS / Windows）。子类在 build() 流程中按
    需调用 _write_case_insensitive_fix。
    """

    ARCH: str = ""
    CROSS: str = ""

    # ---- 大小写不敏感 FS 适配 ----

    def _is_case_insensitive_fs(self, path: Path) -> bool:
        """实地探针：在 path 下创建大写命名文件，看小写名能否命中同一 inode。

        Why: 早期实现读 git config core.ignoreCase，但该键只在 clone 当时探测
        一次写入；仓库被跨 FS 拷贝/挂载后值不会更新，且 git 在敏感 FS 上**不写**
        这个键（缺失即默认 false），原实现把"键缺失"误判为"探测失败 → 保守禁用"，
        在区分大小写分区上仍会启用 case_insensitive_fix。

        实地探针反映"当下文件系统对 git checkout 的实际行为"，正是我们需要的
        语义。探针失败时仍保守返回 True。
        """
        probe_upper = path / ".flange_case_probe_UPPER"
        probe_lower = path / ".flange_case_probe_upper"
        try:
            probe_upper.touch()
            return probe_lower.exists()
        except OSError as e:
            self._status(f"FS 大小写探针失败（{e}），默认启用 fix")
            return True
        finally:
            # 不敏感 FS 上 upper/lower 是同一文件，删一次即可；
            # 敏感 FS 上 lower 从未创建，missing_ok 兜底。
            probe_upper.unlink(missing_ok=True)
            probe_lower.unlink(missing_ok=True)

    def _write_case_insensitive_fix(self, src_dir: Path):
        """生成 config fragment 禁用大小写不敏感 FS 上文件名冲突的模块。

        Linux 内核中存在仅大小写不同的 .c/.h 文件对（xt_MARK.c / xt_mark.c 等），
        在 macOS (HFS+/APFS 默认) 上是同一个文件，git checkout 后只保留一个，
        导致模块编译失败。

        只在检测到大小写不敏感 FS 时才禁用这些模块；在 Linux ext4 等
        大小写敏感 FS 上写入空 fragment，保留这些功能。

        本方法平台无关：写入 ``arch/<ARCH>/configs/case_insensitive_fix.config``，
        子类需把 ``"case_insensitive_fix.config"`` 加到 SoC config 的
        ``kernel.defconfig`` list 末尾，并保证 configure() 支持 list 形式
        defconfig 合并。

        冲突文件对（git checkout warning 显示的完整列表）：
          xt_CONNMARK.h/c     xt_connmark.h/c
          xt_DSCP.h/c         xt_dscp.h/c
          xt_MARK.h/c         xt_mark.h/c
          xt_RATEEST.h/c      xt_rateest.h/c
          xt_TCPMSS.h/c       xt_tcpmss.h/c
          ipt_ECN.h/c         ipt_ecn.h/c
          ipt_TTL.h/c         ipt_ttl.h/c
          ip6t_HL.h/c         ip6t_hl.h/c
        """
        fix_config = src_dir / "arch" / self.ARCH / "configs" / "case_insensitive_fix.config"
        if not self._is_case_insensitive_fs(src_dir):
            # 大小写敏感 FS — 无需禁用，保留 netfilter 功能。
            # 写入空 fragment 以满足 defconfig 合并步骤（make <name>.config 需要文件存在）。
            fix_config.write_text(
                "# 大小写敏感文件系统 — 无需禁用冲突模块\n"
            )
            self._status("FS 大小写敏感，跳过 case_insensitive_fix")
            return
        fix_config.write_text(
            "# macOS 大小写不敏感 FS 上文件名冲突的 netfilter 模块 — 全部禁用\n"
            "# 伞形配置（实际驱动构建规则的入口）——优先禁用\n"
            "# xt_mark.c / xt_mark.h 冲突 xt_MARK.h\n"
            "CONFIG_NETFILTER_XT_MARK=n\n"
            "CONFIG_NETFILTER_XT_TARGET_MARK=n\n"
            "CONFIG_NETFILTER_XT_MATCH_MARK=n\n"
            "# xt_connmark.c / xt_connmark.h 冲突 xt_CONNMARK.h\n"
            "CONFIG_NETFILTER_XT_CONNMARK=n\n"
            "CONFIG_NETFILTER_XT_TARGET_CONNMARK=n\n"
            "CONFIG_NETFILTER_XT_MATCH_CONNMARK=n\n"
            "# xt_DSCP.c / xt_dscp.c 冲突\n"
            "CONFIG_NETFILTER_XT_TARGET_DSCP=n\n"
            "CONFIG_NETFILTER_XT_MATCH_DSCP=n\n"
            "# xt_HL.c / xt_hl.c 冲突\n"
            "CONFIG_NETFILTER_XT_TARGET_HL=n\n"
            "CONFIG_NETFILTER_XT_MATCH_HL=n\n"
            "# xt_RATEEST.c / xt_rateest.c 冲突\n"
            "CONFIG_NETFILTER_XT_TARGET_RATEEST=n\n"
            "CONFIG_NETFILTER_XT_MATCH_RATEEST=n\n"
            "# xt_TCPMSS.c / xt_tcpmss.c 冲突 — TARGET (mangle) 与 MATCH 都要关\n"
            "CONFIG_NETFILTER_XT_TARGET_TCPMSS=n\n"
            "CONFIG_NETFILTER_XT_MATCH_TCPMSS=n\n"
            "# xt_ecn.c 自身没有大小写对手，但 xt_ecn.h include 了 xt_dscp.h；\n"
            "# 后者已被上面 DSCP collide 处理 disable，但 uapi 头在 git checkout\n"
            "# 阶段就因 collide 丢了 lowercase 一份，xt_ecn.o 编译时 #include\n"
            "# 找不到 xt_dscp.h 直接 fatal error。统一关掉 xt_ecn 这两个 target/match\n"
            "# 切断 build 链。\n"
            "CONFIG_NETFILTER_XT_TARGET_ECN=n\n"
            "CONFIG_NETFILTER_XT_MATCH_ECN=n\n"
            "# ipt/ip6t 头文件冲突（ipt_ECN.h vs ipt_ecn.h 等）\n"
            "CONFIG_IP_NF_TARGET_ECN=n\n"
            "CONFIG_IP_NF_MATCH_ECN=n\n"
            "CONFIG_IP_NF_TARGET_TTL=n\n"
            "CONFIG_IP_NF_MATCH_TTL=n\n"
            "CONFIG_IP6_NF_TARGET_HL=n\n"
            "CONFIG_IP6_NF_MATCH_HL=n\n"
        )
        self._status("FS 大小写不敏感，启用 case_insensitive_fix")

    # ---- modules_install staging 清理 ----

    def _clean_modules_staging(self, modules_staging: Path) -> None:
        """清理 _modules_staging/lib/modules/ 子目录，去掉旧 release 残留。

        ``make modules_install INSTALL_MOD_PATH=...`` 只**创建**当前
        ``$(KERNELRELEASE)`` 子目录，**不删除**旧版本目录。当
        LOCALVERSION_AUTO / dirty hash / kernel.config 变化导致 release
        字符串在两次 build 之间不同（典型例子：6.1.115-1245587-gxxx-dirty
        vs 6.1.115-gxxx-dirty），lib/modules/ 下会累积多个版本目录全部
        被 cp 进 rootfs 与 recovery，**撑爆分区**（实测 rkr5.1 上每版本
        ~38 MB，两版本就 76 MB，加上 base + apt 包后 recovery 512 MB
        放不下）。

        平台 KernelBuilder 在调用 ``make modules_install`` 之前调本方法
        清掉 lib/modules，强制只保留当前 release。staging 根目录其他
        子目录不受影响。
        """
        modules_lib = modules_staging / "lib" / "modules"
        if modules_lib.exists():
            shutil.rmtree(modules_lib)

    # ---- out-of-tree 内核模块 ----

    def _oot_modules_config(self, config: dict) -> list[dict]:
        """从配置中提取 out-of-tree 模块声明列表。

        每个声明是 dict，包含：
          - dir: str        — 构建入口目录，支持 {kernel_src} 模板变量
          - label: str      — 状态显示名
          - make_args: list — 传给 make 的额外参数，支持 {kernel_src}
          - ko_pattern: str — glob 模式匹配编译产物 .ko，支持 {kernel_src}
          - pre_build: list|None  — 编译前执行的 shell 命令，支持 {kernel_src}
          - post_build: list|None — 编译后执行的 shell 命令，支持 {kernel_src}

        配置来源：config["kernel"]["oot_modules"]，在 SoC config.py 中声明。

        若 ``dir`` / ``make_args`` / ``ko_pattern`` 引用了独立 git 源（如
        ``{rkwifibt_src}``），需在同 ``config["kernel"]["oot_sources"]`` 字典
        中声明该源（``{<name>: {repo, branch, ...}}``），由 ``_oot_template_vars``
        统一 ensure 后注入模板字典。``{kernel_src}`` 始终可用。
        """
        return config.get("kernel", {}).get("oot_modules", [])

    def _oot_sources_config(self, config: dict) -> dict:
        """OOT 模块独立源声明字典。键是源名（如 ``rkwifibt``），值是 git
        仓库 cfg（_ensure_repo 可识别的字段）。返回空字典表示无独立源，
        OOT 模块只引用 ``{kernel_src}``。

        过滤 ``product`` / ``variant`` 这两个 reserved key —— 它们被
        ``resolve_conditions`` 递归注入到所有 dict 子树（详见
        ``builder/config/merge.py``），对 oot_sources 这种"源名 → cfg"
        语义的 dict 是脏数据。其余子 cfg dict 内层多出来的 product/variant
        不影响 _ensure_repo（只读已知字段）。
        """
        raw = (config.get("kernel", {}) or {}).get("oot_sources", {}) or {}
        return {k: v for k, v in raw.items()
                if k not in ("product", "variant") and isinstance(v, dict)}

    def _oot_template_vars(self, src_dir: Path, config: dict) -> dict[str, str]:
        """构造 OOT 模块字段格式化用的模板字典。

        始终包含 ``kernel_src``、``kernel_src_abs``、``arch``、``cross_compile``。
        ``kernel_src_abs`` 是 ``kernel_src`` 的绝对化形式——hardware-feature
        package 合成的 OOT 条目用它做 ``KSRC=`` / ``-C``，因为这些条目以驱动
        目录为 cwd 编译，相对的 ``kernel_src`` 在该 cwd 下无法解析。``arch`` /
        ``cross_compile`` 来自平台 kernel builder 的类属性，让 package 条目
        无需感知具体平台即可拿到正确交叉前缀。

        对每个 ``kernel.oot_sources`` 声明的源 ``<name>``，先 ``ensure_oot_source``
        拿到本地路径，再注入键 ``<name>_src``（``-`` 替换为 ``_`` 以满足 Python
        format 标识符规则）。

        幂等：cache 依赖图保证 kernel build 入口先于本调用，重复 ensure
        只是 git fetch + reset --hard，无副作用。
        """
        tmpl: dict[str, str] = {
            "kernel_src": str(src_dir),
            "kernel_src_abs": str(Path(src_dir).resolve()),
            "arch": self.ARCH,
            "cross_compile": self.CROSS,
        }
        for name, cfg in self._oot_sources_config(config).items():
            path = self.source.ensure_oot_source(name, cfg)
            tmpl[f"{name.replace('-', '_')}_src"] = str(path)
        return tmpl

    def _compile_oot_modules(self, src_dir: Path, config: dict, jobs: int):
        """遍历配置中的 out-of-tree 模块并逐个编译。"""
        oot_modules = self._oot_modules_config(config)
        if not oot_modules:
            return

        njobs = jobs or max((os.cpu_count() or 1) - 6, 1)
        tmpl = self._oot_template_vars(src_dir, config)
        for mod in oot_modules:
            build_dir = Path(mod["dir"].format(**tmpl))
            if not build_dir.is_dir():
                self._status(f"跳过 {mod['label']}：目录不存在 {mod['dir']}")
                continue

            label = f"编译 {mod['label']}..."
            self._status(label)

            for cmd in mod.get("pre_build") or []:
                self.docker.run(
                    ["bash", "-c", cmd.format(**tmpl)],
                    cwd=str(src_dir))

            try:
                make_cmd = ["make", f"-j{njobs}"]
                make_cmd.extend(
                    a.format(**tmpl) for a in mod.get("make_args", []))
                self.docker.run(make_cmd, cwd=str(build_dir), label=label)
            finally:
                for cmd in mod.get("post_build") or []:
                    self.docker.run(
                        ["bash", "-c", cmd.format(**tmpl)],
                        cwd=str(src_dir), check=False)

            ko_found = False
            for pattern in mod.get("ko_pattern", []):
                if glob.glob(pattern.format(**tmpl)):
                    ko_found = True
                    break
            if ko_found:
                self._status(f"{mod['label']} 编译完成")
            else:
                self._status(f"警告：{mod['label']} 编译失败，未生成 .ko")

    def _install_oot_modules(self, src_dir: Path, config: dict,
                              modules_staging: Path):
        """将 out-of-tree 模块 .ko 安装到 modules staging 目录。"""
        oot_modules = self._oot_modules_config(config)
        if not oot_modules:
            return

        tmpl = self._oot_template_vars(src_dir, config)

        kernel_release = self.docker.run(
            ["cat", "include/config/kernel.release"],
            cwd=str(src_dir), capture=True).stdout.strip()

        mod_base = modules_staging / "lib" / "modules" / kernel_release

        strip = f"{self.CROSS}strip"
        installed = []
        for mod in oot_modules:
            for pattern in mod.get("ko_pattern", []):
                for ko_path in glob.glob(pattern.format(**tmpl)):
                    ko = Path(ko_path)
                    if not ko.exists():
                        continue
                    rel = f"updates/{ko.name}"
                    dst = mod_base / "updates" / ko.name
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    self.docker.run(
                        [strip, "--strip-debug",
                         "-o", str(dst), str(ko)],
                        cwd=str(src_dir))
                    installed.append(rel)
                    self._status(f"OOT 模块安装: {rel}")

        if not installed:
            return

        # 重新生成 modules.{dep,alias,symbols,...} 与 .bin 索引：
        # ``make modules_install`` 只覆盖 in-tree 模块，新增的 updates/<name>.ko
        # 没被纳入 modules.alias —— PCI/USB hotplug 拿到 MODALIAS 后查不到
        # 对应 module，开机不自动 load（表面现象：lsmod 不见 module，但
        # 手动 ``depmod -a && modprobe <name>`` 后能正常 bind 设备）。
        # ``depmod -b <staging> <release>`` 扫描 ``<staging>/lib/modules/<release>/``
        # 下所有 .ko（含 updates/）重写全部索引。手写追加 modules.dep 不够，
        # 因为 alias / symbols / bin 索引同样要刷新。
        self.docker.run(
            ["depmod", "-b", str(modules_staging), kernel_release],
            cwd=str(src_dir),
            label=f"刷新 OOT 模块索引（{len(installed)} 个）...")
