"""组件构建基类 — 管理源码生命周期、补丁应用。"""

import os
import tempfile
from abc import ABC, abstractmethod
from contextlib import nullcontext
from pathlib import Path
from typing import TYPE_CHECKING
from builder.docker import DockerRunner
from builder.patches import normalize_excluded_patches
from builder.paths import COMPONENTS_ROOT
from builder.source import SourceManager, component_local_path

if TYPE_CHECKING:
    from builder.cache import BuildCache
    from builder.output import BuildOutput


class ComponentBuilder(ABC):
    """组件构建基类。

    子类声明 component 属性并实现 configure/compile/collect。
    基类负责：源码获取 → 源码重置 → 补丁应用 → 调子类 → 返回产物。
    """

    component: str = ""
    context = None
    task_plan = None
    app_report = None
    cache: "BuildCache | None" = None  # 由 engine 注入，供子类使用分阶段缓存
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

    @property
    def components_root(self) -> Path:
        return self.context.components_root if self.context else COMPONENTS_ROOT

    def work_dir(self, label: str | None = None) -> Path:
        """每次执行使用目标所属目录中的独立暂存区。"""
        if self.context is None:
            raise RuntimeError("组件执行必须注入 WorkspaceContext")
        root = (
            self.context.build_root / "work" / self.context.target.key / (label or self.component)
        )
        root.mkdir(parents=True, exist_ok=True)
        return Path(tempfile.mkdtemp(prefix="run-", dir=root))

    def execute(self, plan) -> dict:
        """执行与 fingerprint 消费同一份声明配置。"""
        self.task_plan = plan
        return self.build(plan.value("config"))

    def _status(self, msg: str):
        """通过 output 输出状态（兼容 output 未注入的场景）。"""
        if self.output:
            self.output.status(msg)

    def _step(self, label: str):
        """生命周期动作拥有明确边界，输出未注入时仍可独立执行。"""
        return self.output.step(label) if self.output else nullcontext()

    def build(self, config: dict) -> dict:
        with self._step("准备源码"):
            src_dir = self.source.ensure(self.component, config)
            if component_local_path(config, self.component):
                # 本地源已经复制隔离，不重置用户快照或重复打补丁。
                self._status("使用本地源码快照")
            else:
                self.reset_source(src_dir)
                self._remove_patch_created_files(src_dir, config)
                patches = self._count_patches(config)
                self.apply_patches(src_dir, config)
                if patches > 0:
                    self._status(f"已应用 {patches} 个补丁")
        with self._step("配置构建"):
            self.configure(src_dir, config)
        self.compile(src_dir, config)
        with self._step("收集产物"):
            result = self.collect(src_dir, config)
        return result

    def _count_patches(self, config: dict) -> int:
        """统计补丁数量。"""
        return len(self._patch_paths(config))

    def _patch_paths(self, config: dict) -> list[Path]:
        """返回当前组件实际适用的平台与板级补丁。

        ``<component>.exclude_patches`` 可按文件名或仓库相对路径排除不适用于
        当前构建路由的补丁。例如 vendor FIT（扁平设备树镜像）启动必须保留
        DTS bootargs，因此可排除仅为 extlinux 准备的 U-Boot 补丁。

        默认不排除任何补丁，既有 target 行为保持不变。
        """
        component_config = config.get(self.component, {}) or {}
        excluded_names = set(
            normalize_excluded_patches(
                component_config.get("exclude_patches"),
                f"{self.component}.exclude_patches",
            )
        )
        applicable: list[Path] = []
        for patch in self._all_patch_paths(config):
            relative = patch.relative_to(self.components_root.parent).as_posix()
            if patch.name in excluded_names or relative in excluded_names:
                continue
            applicable.append(patch)
        return applicable

    def _all_patch_paths(self, config: dict) -> list[Path]:
        """返回当前平台/board 为组件声明的全部 patch，包括被路由排除者。"""
        platform = config["platform"]
        board = config["board"]
        patches: list[Path] = []
        for patch_dir in (
            self.components_root / "platform" / platform / "patches" / self.component,
            self.components_root / "board" / board / "patches" / self.component,
        ):
            if patch_dir.is_dir():
                patches.extend(sorted(patch_dir.glob("*.patch")))
        return patches

    def reset_source(self, src_dir: Path):
        """重置源码树，保留 .o 等编译产物（增量编译）。

        只操作 SourceManager 提供的目标独立工作树。重置失败必须停止，
        避免把不完整源码当作有效构建输入。
        """
        self.docker.run(["git", "checkout", "-f", "."], cwd=str(src_dir))

    def _remove_patch_created_files(self, src_dir: Path, config: dict) -> None:
        """删除上次 patch 明确新增的文件，使增量源码树可重复打补丁。

        ``git checkout -f .`` 只还原 tracked 文件；patch 中从 ``/dev/null``
        新增的 DTS/defconfig 会作为 untracked 文件残留，下一次 ``git apply``
        因目标已存在而失败。这里仅解析当前适用 patch 的 ``--- /dev/null`` /
        ``+++ b/<path>`` 对并删除对应文件，不执行 ``git clean``，因此保留 .o、
        下载物及其他增量缓存。本地源码模式本来就跳过 reset/patch，不受影响。
        """
        root = src_dir.resolve()
        # 扫描全部声明 patch，而不是只看当前适用集合。这样从 product A
        # 切到排除某 patch 的 product B 时，也能删除 A 留下的 untracked 文件。
        for patch in self._all_patch_paths(config):
            lines = patch.read_text().splitlines()
            for index, line in enumerate(lines[:-1]):
                if line != "--- /dev/null":
                    continue
                target_line = lines[index + 1]
                if not target_line.startswith("+++ b/"):
                    continue
                relative = target_line[len("+++ b/") :]
                target = (src_dir / relative).resolve()
                if not target.is_relative_to(root):
                    raise ValueError(f"补丁新增文件路径越出源码树: {patch}: {relative}")
                if target.is_symlink() or target.is_file():
                    target.unlink()
                elif target.exists():
                    raise IsADirectoryError(f"补丁声明新增文件但目标是目录: {target}")

    def apply_patches(self, src_dir: Path, config: dict):
        """按序应用平台补丁 + 板级补丁"""
        for patch in self._patch_paths(config):
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

    def make(
        self,
        src_dir: Path,
        targets: list,
        *,
        arch: str = "",
        cross: str = "",
        jobs: int = 0,
        extra: list = None,
        label: str = "",
    ):
        """封装 make 调用"""
        cmd = ["make"]
        if arch:
            cmd.append(f"ARCH={arch}")
        if cross:
            cmd.append(f"CROSS_COMPILE={cross}")
        cmd.append(f"-j{jobs or max((os.cpu_count() or 1) - 6, 1)}")
        cmd.extend(extra or [])
        cmd.extend(targets)
        self.docker.run(cmd, cwd=str(src_dir), label=label)
