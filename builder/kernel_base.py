"""内核构建器基类 — 提供跨平台共享的 out-of-tree 模块编译与安装逻辑。"""

import glob
import os
from pathlib import Path
from builder.base import ComponentBuilder


class KernelBuilder(ComponentBuilder):
    """内核构建器基类。

    子类仍需实现 configure / compile / collect，
    并声明 ARCH / CROSS 类属性。
    基类提供 OOT 模块的编译与安装方法，子类在 compile() 中按需调用。
    """

    ARCH: str = ""
    CROSS: str = ""

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
