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
    cache: "BuildCache | None" = None  # 由 engine 注入，供子类使用分阶段缓存

    def __init__(self, docker: DockerRunner, source: SourceManager):
        self.docker = docker
        self.source = source

    def build(self, config: dict) -> dict:
        src_dir = self.source.ensure(self.component, config)
        if not config.get("_local_mode", {}).get(self.component):
            self.reset_source(src_dir)
            self.apply_patches(src_dir, config)
        self.configure(src_dir, config)
        self.compile(src_dir, config)
        return self.collect(src_dir, config)

    def reset_source(self, src_dir: Path):
        """重置源码树，保留 .o 等编译产物（增量编译）"""
        self.docker.run(["git", "checkout", "-f", "."], cwd=str(src_dir))

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
             arch: str = "", cross: str = "", jobs: int = 0, extra: list = None):
        """封装 make 调用"""
        cmd = ["make"]
        if arch: cmd.append(f"ARCH={arch}")
        if cross: cmd.append(f"CROSS_COMPILE={cross}")
        cmd.append(f"-j{jobs or os.cpu_count() or 1}")
        cmd.extend(extra or [])
        cmd.extend(targets)
        self.docker.run(cmd, cwd=str(src_dir))
