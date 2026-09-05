"""内核构建器基类 — 提供跨平台共享的 out-of-tree 模块编译与安装逻辑。"""

import glob
import os
import shutil
from pathlib import Path
from builder.base import ComponentBuilder
from builder.kconfig import defconfig_targets, write_kconfig_fragment


class KernelBuilder(ComponentBuilder):
    """内核构建器基类。

    子类仍需实现 configure / compile / collect，并声明 ARCH 类属性
    （CROSS 默认继承 base ComponentBuilder = gcc-10，子类如需别的工具链可覆盖）。
    基类提供 OOT 模块的编译与安装方法，以及大小写敏感存储校验。
    子类在 build() 流程中按
    需调用 _write_case_insensitive_fix。
    """

    ARCH: str = ""

    # ---- 构建存储能力 ----

    def _write_case_insensitive_fix(self, src_dir: Path):
        """校验源码存储，保留空片段名称供已有 defconfig 列表引用。

        片段从不关闭模块。存储无法表达内核文件名时必须迁移构建目录，
        不能根据宿主文件系统静默改变目标系统的功能。
        """
        from builder.filesystem import require_case_sensitive

        require_case_sensitive(src_dir)
        fragment = src_dir / "arch" / self.ARCH / "configs/case_insensitive_fix.config"
        fragment.parent.mkdir(parents=True, exist_ok=True)
        fragment.write_text("# 构建存储已通过大小写敏感校验；无功能覆盖。\n")

    # ---- canonical Kconfig ----

    def _resolve_defconfig_targets(self, src_dir: Path, defconfig) -> list[str]:
        """返回只含 defconfig/fragment 名称的有序 make target。"""
        _ = src_dir
        return defconfig_targets(defconfig, "kernel.defconfig")

    def _write_config_override_fragment(self, src_dir: Path, config: dict) -> str | None:
        """把 ``kernel.config`` 写成所有平台共用的末尾 override fragment。"""
        name = "flange_overrides.config"
        fragment = src_dir / "arch" / self.ARCH / "configs" / name
        count = write_kconfig_fragment(
            fragment,
            (config.get("kernel") or {}).get("config"),
            field="kernel.config",
        )
        if not count:
            return None
        self._status(f"{name} 生成（{count} 项 Kconfig）")
        return name

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

        配置来源：config["kernel"]["oot_modules"]，在 SoC config.jsonnet 中声明。

        若 ``dir`` / ``make_args`` / ``ko_pattern`` 引用了独立 git 源（如
        ``{rkwifibt_src}``），需在同 ``config["kernel"]["oot_sources"]`` 字典
        中声明该 source 引用；实际 descriptor 位于顶层 ``sources``，由
        ``_oot_template_vars``
        统一 ensure 后注入模板字典。``{kernel_src}`` 始终可用。
        """
        return config.get("kernel", {}).get("oot_modules", [])

    def _oot_sources_config(self, config: dict) -> dict:
        """返回 OOT 模块的 canonical source 引用。"""
        return (config.get("kernel") or {}).get("oot_sources") or {}

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
            path = self.source.ensure_oot_source(name, cfg, config=config)
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
                self.docker.run(["bash", "-c", cmd.format(**tmpl)], cwd=str(src_dir))

            try:
                make_cmd = ["make", f"-j{njobs}"]
                make_cmd.extend(a.format(**tmpl) for a in mod.get("make_args", []))
                self.docker.run(make_cmd, cwd=str(build_dir), label=label)
            finally:
                for cmd in mod.get("post_build") or []:
                    self.docker.run(
                        ["bash", "-c", cmd.format(**tmpl)], cwd=str(src_dir), check=False
                    )

            ko_found = False
            for pattern in mod.get("ko_pattern", []):
                if glob.glob(pattern.format(**tmpl)):
                    ko_found = True
                    break
            if ko_found:
                self._status(f"{mod['label']} 编译完成")
            else:
                self._status(f"警告：{mod['label']} 编译失败，未生成 .ko")

    def _install_oot_modules(self, src_dir: Path, config: dict, modules_staging: Path):
        """将 out-of-tree 模块 .ko 安装到 modules staging 目录。"""
        oot_modules = self._oot_modules_config(config)
        if not oot_modules:
            return

        tmpl = self._oot_template_vars(src_dir, config)

        kernel_release = self.docker.run(
            ["cat", "include/config/kernel.release"], cwd=str(src_dir), capture=True
        ).stdout.strip()

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
                        [strip, "--strip-debug", "-o", str(dst), str(ko)], cwd=str(src_dir)
                    )
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
            label=f"刷新 OOT 模块索引（{len(installed)} 个）...",
        )
