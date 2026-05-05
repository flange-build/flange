"""内核构建器基类 — 提供跨平台共享的 out-of-tree 模块编译与安装逻辑。"""

import glob
import os
import shutil
import subprocess
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
        """通过 git config core.ignoreCase 判断 FS 是否大小写不敏感。

        git clone 时会自动探测并写入 core.ignoreCase，这正是我们需要的语义
        ——"git checkout 是否会因大小写碰撞丢文件"。比自建探针更可靠，
        不受 Docker volume 元数据缓存影响。

        path 可以是仓库任意子路径，git config 会向上查找 .git 目录。
        若 path 不在 git 仓库内或探测失败，默认返回 True（保守禁用模块）。
        """
        try:
            result = subprocess.run(
                ["git", "config", "--get", "core.ignoreCase"],
                cwd=str(path), capture_output=True, text=True, check=False,
                timeout=10,
            )
            value = result.stdout.strip().lower()
            if value in ("true", "false"):
                return value == "true"
        except Exception as e:
            self._status(f"git config 探测失败（{e}），默认启用 fix")
        return True  # 保守策略

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
        """
        return config.get("kernel", {}).get("oot_modules", [])

    def _compile_oot_modules(self, src_dir: Path, config: dict, jobs: int):
        """遍历配置中的 out-of-tree 模块并逐个编译。"""
        oot_modules = self._oot_modules_config(config)
        if not oot_modules:
            return

        njobs = jobs or max((os.cpu_count() or 1) - 4, 1)
        for mod in oot_modules:
            tmpl = {"kernel_src": str(src_dir)}

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

        tmpl = {"kernel_src": str(src_dir)}

        kernel_release = self.docker.run(
            ["cat", "include/config/kernel.release"],
            cwd=str(src_dir), capture=True).stdout.strip()

        mod_base = modules_staging / "lib" / "modules" / kernel_release
        dep_file = mod_base / "modules.dep"

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

        if installed and dep_file.exists():
            existing = dep_file.read_text()
            entries = "".join(f"{r}:\n" for r in installed if r not in existing)
            if entries:
                dep_file.write_text(existing + entries)
