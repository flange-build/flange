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
        return h.hexdigest()[:16]
