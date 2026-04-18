"""组件构建基类 — 管理源码生命周期、补丁应用。"""

import os
from abc import ABC, abstractmethod
from pathlib import Path
from builder.docker import DockerRunner
from builder.source import SourceManager


class ComponentBuilder(ABC):
    """组件构建基类。

    子类声明 component 属性并实现 configure/compile/collect。
    基类负责：源码获取 → 源码重置 → 补丁应用 → 调子类 → 返回产物。
    """
    component: str = ""
    cache: "BuildCache | None" = None   # 由 engine 注入，供子类使用分阶段缓存
    output: "BuildOutput | None" = None  # 由 engine 注入，统一输出

    def __init__(self, docker: DockerRunner, source: SourceManager):
        self.docker = docker
        self.source = source

    def _status(self, msg: str):
        """通过 output 输出状态（兼容 output 未注入的场景）。"""
        if self.output:
            self.output.status(msg)

    def build(self, config: dict) -> dict:
        src_dir = self.source.ensure(self.component, config)
        self._status("源码就绪")
        if not config.get("_local_mode", {}).get(self.component):
            self.reset_source(src_dir)
            patches = self._count_patches(config)
            self.apply_patches(src_dir, config)
            if patches > 0:
                self._status(f"补丁应用 ({patches} patches)")
        self.configure(src_dir, config)
        self.compile(src_dir, config)
        result = self.collect(src_dir, config)
        self._status("产物收集")
        return result

    def _count_patches(self, config: dict) -> int:
        """统计补丁数量。"""
        platform = config["platform"]
        board = config["board"]
        count = 0
        for patch_dir in [
            Path(f"platform/{platform}/patches/{self.component}"),
            Path(f"board/{board}/patches/{self.component}"),
        ]:
            if patch_dir.exists():
                count += len(list(patch_dir.glob("*.patch")))
        return count

    def reset_source(self, src_dir: Path):
        """重置源码树，保留 .o 等编译产物（增量编译）。

        Linux 内核源码中存在仅大小写不同的文件（如 xt_connmark.h / xt_CONNMARK.h），
        在 macOS 大小写不敏感文件系统上 git checkout 会报 "unable to create file"
        并返回非零退出码，但实际已完成重置，因此不检查返回值。
        """
        self.docker.run(["git", "checkout", "-f", "."], cwd=str(src_dir),
                        check=False)

    def apply_patches(self, src_dir: Path, config: dict):
        """按序应用平台补丁 + 板级补丁"""
        platform = config["platform"]
        board = config["board"]
        all_patches = []
        for patch_dir in [
            Path(f"platform/{platform}/patches/{self.component}"),
            Path(f"board/{board}/patches/{self.component}"),
        ]:
            if patch_dir.exists():
                all_patches.extend(sorted(patch_dir.glob("*.patch")))
        for patch in all_patches:
            abs_patch = str(patch.resolve())
            try:
                self.docker.run(["git", "apply", abs_patch], cwd=str(src_dir))
            except Exception:
                self.docker.run(["patch", "-p1", "-i", abs_patch], cwd=str(src_dir))

    @abstractmethod
    def configure(self, src_dir: Path, config: dict): ...

    @abstractmethod
    def compile(self, src_dir: Path, config: dict): ...

    @abstractmethod
    def collect(self, src_dir: Path, config: dict) -> dict: ...

    def make(self, src_dir: Path, targets: list, *,
             arch: str = "", cross: str = "", jobs: int = 0, extra: list = None,
             label: str = ""):
        """封装 make 调用"""
        cmd = ["make"]
        if arch: cmd.append(f"ARCH={arch}")
        if cross: cmd.append(f"CROSS_COMPILE={cross}")
        cmd.append(f"-j{jobs or max((os.cpu_count() or 1) - 4, 1)}")
        cmd.extend(extra or [])
        cmd.extend(targets)
        self.docker.run(cmd, cwd=str(src_dir), label=label)
