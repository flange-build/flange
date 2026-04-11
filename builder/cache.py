"""增量构建缓存 — 基于内容哈希判断组件是否需要重建。"""

import hashlib
import json
import subprocess
from pathlib import Path


class BuildCache:
    """基于内容哈希的增量构建缓存。

    哈希输入：组件配置值 + 源码 commit + 补丁文件内容 + 全局配置
    """

    def __init__(self, config: dict, target_base: Path = None):
        self.config = config
        board = config["board"]
        product = config.get("product", "default")
        variant = config.get("variant", "release")
        self.target_dir = (target_base or Path("target")) / board / product / variant

    def is_up_to_date(self, component: str) -> bool:
        hash_file = self.target_dir / component / ".build_hash"
        if not hash_file.exists():
            return False
        return hash_file.read_text().strip() == self.compute_hash(component)

    def store(self, component: str):
        hash_file = self.target_dir / component / ".build_hash"
        hash_file.parent.mkdir(parents=True, exist_ok=True)
        hash_file.write_text(self.compute_hash(component))

    # --- 分阶段缓存接口 ---

    def compute_phase_hash(self, component: str, phase: str) -> str:
        """计算组件指定阶段的哈希。目前仅支持 ("rootfs", "base")。"""
        if component == "rootfs" and phase == "base":
            return self._compute_rootfs_base_hash()
        raise ValueError(f"不支持的分阶段哈希: {component}.{phase}")

    def is_phase_up_to_date(self, component: str, phase: str) -> bool:
        """检查指定阶段缓存是否有效。"""
        hash_file = self.target_dir / component / f".{phase}_hash"
        if not hash_file.exists():
            return False
        return hash_file.read_text().strip() == self.compute_phase_hash(component, phase)

    def store_phase(self, component: str, phase: str):
        """保存指定阶段的哈希。"""
        hash_file = self.target_dir / component / f".{phase}_hash"
        hash_file.parent.mkdir(parents=True, exist_ok=True)
        hash_file.write_text(self.compute_phase_hash(component, phase))

    # --- 组件级哈希 ---

    def compute_hash(self, component: str) -> str:
        if component == "rootfs":
            return self._compute_rootfs_customize_hash()

        h = hashlib.sha256()
        # 组件配置
        h.update(json.dumps(self.config.get(component, {}), sort_keys=True, default=str).encode())
        # 全局配置
        for key in ("arch", "platform", "soc", "board"):
            h.update(self.config.get(key, "").encode())

        if component == "app":
            self._hash_app_sources(h)
        else:
            self._hash_component_sources(h, component)

        return h.hexdigest()[:16]

    def _compute_rootfs_base_hash(self) -> str:
        """Phase 1 哈希：rootfs.url + sorted(rootfs.packages) + arch。"""
        h = hashlib.sha256()
        rootfs_cfg = self.config.get("rootfs", {})
        h.update(rootfs_cfg.get("url", "").encode())
        packages = sorted(rootfs_cfg.get("packages", []))
        h.update(json.dumps(packages).encode())
        h.update(self.config.get("arch", "").encode())
        return h.hexdigest()[:16]

    def _compute_rootfs_customize_hash(self) -> str:
        """Phase 2 哈希：base_hash + overlay + custom_packages + app debs。"""
        h = hashlib.sha256()
        # 级联依赖：base 变了，customize 也变
        h.update(self._compute_rootfs_base_hash().encode())
        # overlay 目录递归哈希
        board = self.config["board"]
        overlay_dir = Path(f"board/{board}/overlay")
        if overlay_dir.exists():
            self._hash_directory(h, overlay_dir)
        # custom_packages 列表
        rootfs_cfg = self.config.get("rootfs", {})
        custom_packages = sorted(rootfs_cfg.get("custom_packages", []))
        h.update(json.dumps(custom_packages).encode())
        # App deb 文件哈希
        self._hash_app_debs(h)
        return h.hexdigest()[:16]

    def _hash_app_debs(self, h: "hashlib._Hash") -> None:
        """hash target/.../app/*.deb 文件内容。"""
        app_deb_dir = self.target_dir / "app"
        if not app_deb_dir.exists():
            h.update(b"no-debs")
            return
        deb_files = sorted(app_deb_dir.glob("*.deb"))
        if not deb_files:
            h.update(b"no-debs")
            return
        for deb in deb_files:
            h.update(deb.name.encode())
            h.update(deb.read_bytes())

    def _hash_app_sources(self, h: "hashlib._Hash") -> None:
        """将 custom_packages 列表及各 App 的完整源码内容混入哈希。

        哈希输入：
        - custom_packages 列表（JSON 序列化，保证顺序稳定）
        - 每个 App 目录下的所有文件内容（递归 hash，排除构建产物）
        """
        rootfs_cfg = self.config.get("rootfs", {})
        custom_packages: list = rootfs_cfg.get("custom_packages", [])
        h.update(json.dumps(sorted(custom_packages)).encode())
        for pkg in sorted(custom_packages):
            app_dir = Path("app") / pkg
            if app_dir.exists():
                self._hash_directory(h, app_dir)
            else:
                h.update(f"missing:{pkg}".encode())

    # 目录递归哈希排除规则
    HASH_EXCLUDE_DIRS = {"__pycache__", ".git", "build", ".build", "node_modules"}
    HASH_EXCLUDE_EXTS = {".pyc", ".o", ".so"}

    def _hash_directory(self, h: "hashlib._Hash", directory: Path) -> None:
        """递归 hash 目录下所有文件（排除构建产物和临时文件）。

        按相对路径排序确保哈希稳定。
        """
        entries = []
        for path in directory.rglob("*"):
            if path.is_dir():
                continue
            if any(part in self.HASH_EXCLUDE_DIRS for part in path.parts):
                continue
            if path.suffix in self.HASH_EXCLUDE_EXTS:
                continue
            entries.append(path)

        for path in sorted(entries):
            rel = path.relative_to(directory)
            h.update(str(rel).encode())
            h.update(path.read_bytes())

    def _hash_component_sources(self, h: "hashlib._Hash", component: str) -> None:
        """将源码 commit 和补丁文件内容混入哈希（非 app 组件使用）。"""
        # 源码 commit
        src_dir = Path("sources") / component / self.config["board"]
        if src_dir.exists():
            try:
                result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=src_dir,
                                        capture_output=True, text=True, check=True)
                h.update(result.stdout.strip().encode())
            except subprocess.CalledProcessError:
                h.update(b"unknown")
        # 补丁文件
        platform = self.config.get("platform", "")
        board = self.config["board"]
        for patch_dir in [
            Path(f"platform/{platform}/patches/{component}"),
            Path(f"board/{board}/patches/{component}"),
        ]:
            if patch_dir.exists():
                for p in sorted(patch_dir.glob("*.patch")):
                    h.update(p.read_bytes())
