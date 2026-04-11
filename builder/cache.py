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

    def compute_hash(self, component: str) -> str:
        h = hashlib.sha256()
        # 组件配置
        h.update(json.dumps(self.config.get(component, {}), sort_keys=True, default=str).encode())
        # 全局配置
        for key in ("arch", "platform", "soc", "board"):
            h.update(self.config.get(key, "").encode())

        if component == "app":
            # App 组件哈希：custom_packages 列表 + 各 app.yaml 内容
            self._hash_app_sources(h)
        else:
            # 其他组件：源码 commit + 补丁文件
            self._hash_component_sources(h, component)

        return h.hexdigest()[:16]

    def _hash_app_sources(self, h: "hashlib._Hash") -> None:
        """将 custom_packages 列表及各 App 的 app.yaml 内容混入哈希。

        哈希输入：
        - custom_packages 列表（JSON 序列化，保证顺序稳定）
        - 每个 App 目录下 app.yaml 的文件内容（按包名排序）
        """
        rootfs_cfg = self.config.get("rootfs", {})
        custom_packages: list = rootfs_cfg.get("custom_packages", [])
        # 列表本身的序列化（包名顺序变动也会导致哈希改变）
        h.update(json.dumps(sorted(custom_packages)).encode())
        # 逐个 app.yaml 文件内容
        for pkg in sorted(custom_packages):
            app_yaml = Path("app") / pkg / "app.yaml"
            if app_yaml.exists():
                h.update(app_yaml.read_bytes())
            else:
                # 文件缺失时混入占位符，避免误判为无变更
                h.update(f"missing:{pkg}".encode())

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
