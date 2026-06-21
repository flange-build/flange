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

    # 全平台 u-boot/kernel 交叉编译默认工具链前缀 = gcc-10（容器内 /opt/aarch64-gcc10，见
    # docker/Dockerfile）。Ubuntu 24.04 默认 gcc-13 编老 rockchip u-boot（2017.09 基）会让
    # 整体二进制布局变化 → RK3576 UFS DMA 读 buffer 落到坏物理地址 → proper 读 GPT 拿残渣崩
    # （2026-06 逐次上板 + 反汇编坐实；radxa bsp 全程用 gcc-10）。为统一与稳妥，全平台
    # u-boot/kernel 默认用 gcc-10（kernel.org crosstool gcc-10.5，亦为内核官方推荐工具链）。
    # 子类如需别的工具链可覆盖 CROSS。详见 openspec selfbuild-rk3576-spi-image。
    CROSS: str = "/opt/aarch64-gcc10/bin/aarch64-linux-"

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
            Path(f"components/platform/{platform}/patches/{self.component}"),
            Path(f"components/board/{board}/patches/{self.component}"),
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
            Path(f"components/platform/{platform}/patches/{self.component}"),
            Path(f"components/board/{board}/patches/{self.component}"),
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
        cmd.append(f"-j{jobs or max((os.cpu_count() or 1) - 6, 1)}")
        cmd.extend(extra or [])
        cmd.extend(targets)
        self.docker.run(cmd, cwd=str(src_dir), label=label)
