"""增量构建缓存 — 基于内容哈希判断组件是否需要重建。

哈希策略（Merkle tree 风格）：
  组件哈希 = f(上游依赖哈希 + 组件自身配置 + 源码/补丁 + 其他影响产物的输入)

任一上游变更都会级联使下游哈希失效，确保增量构建始终产出一致的产物。
"""

import hashlib
import json
import os
import subprocess
from pathlib import Path


# 组件依赖图：键为组件名，值为该组件依赖的上游组件列表。
# cache 用此图做 Merkle 哈希级联；engine 用此图做拓扑排序。
# 保持单一定义源以避免两处不一致。
DEPENDENCY_GRAPH: dict[str, list[str]] = {
    "kernel":     [],
    "bootloader": [],
    "app":        [],
    "rootfs":     ["app", "kernel"],
    "boot":       ["kernel"],
    "image":      ["boot", "bootloader", "rootfs"],
}


# 各组件必须存在的产物（相对 target/<board>/<product>/<variant>/<component>/）。
# 支持字面量文件名和 glob 通配（如 "*.dtb"）。
# 缓存命中时校验这些文件存在，防止 .build_hash 有效但产物被误删导致下游失败。
# app 组件不校验：custom_packages 为空时无 deb 输出是合法状态。
REQUIRED_ARTIFACTS: dict[str, list[str]] = {
    "kernel":     ["Image", "*.dtb"],
    "bootloader": ["u-boot.itb", "idbloader.img", "miniloader.bin"],
    "boot":       ["boot.img"],
    "rootfs":     ["rootfs.img"],
    "image":      ["raw.img"],
}


class BuildCache:
    """基于内容哈希的增量构建缓存。

    哈希输入（Merkle 级联）：
      - 上游依赖组件的哈希
      - 全局配置（arch/platform/soc/board）
      - 组件自身的 config 分支
      - 源码 git HEAD + 补丁文件内容（有源码树的组件）
      - partitions 配置（boot/rootfs/image）
      - rkbin firmware git HEAD（bootloader）
      - App 源码目录递归哈希（app）
      - rootfs base 阶段哈希 + overlay + root_password 等（rootfs）
    """

    def __init__(self, config: dict, target_base: Path = None):
        self.config = config
        board = config["board"]
        product = config.get("product", "default")
        variant = config.get("variant", "release")
        self.target_dir = (target_base or Path("target")) / board / product / variant
        # 记忆化：避免 image→boot→kernel 等路径上重复计算
        self._hash_cache: dict[str, str] = {}

    # --- 主入口：组件级哈希查询 ---

    def is_up_to_date(self, component: str) -> bool:
        """判断组件是否可跳过构建。

        三层校验（任一失败都视为缓存失效）：
          0. local_path 模式短路：当前组件或任意传递上游声明了 local_path 时，
             框架放弃缓存决策，强制重建并级联到下游，由底层构建系统（make /
             mke2fs 等）自己做增量。理由：local_path 指向用户正在 hack 的
             目录，内容变化不走 git，没有可靠的廉价指纹；强行按源码树哈希
             会假命中（"内容变了但哈希没变"）。
          1. .build_hash 文件存在且内容等于当前 compute_hash
          2. REQUIRED_ARTIFACTS 中声明的产物全部存在
        """
        if self._has_local_upstream(component):
            return False

        hash_file = self.target_dir / component / ".build_hash"
        if not hash_file.exists():
            return False
        if hash_file.read_text().strip() != self.compute_hash(component):
            return False
        if not self._required_artifacts_present(component):
            return False
        return True

    def _has_local_upstream(self, component: str) -> bool:
        """检查组件自身或任意传递依赖是否声明了 local_path。

        用于 local_path 模式的级联失效：kernel 声明了 local_path，
        boot/image 也会跟着强制重建，确保下游产物总是基于最新的
        kernel 产物重新组装。
        """
        if self.config.get(component, {}).get("local_path"):
            return True
        for dep in DEPENDENCY_GRAPH.get(component, []):
            if self._has_local_upstream(dep):
                return True
        return False

    def _required_artifacts_present(self, component: str) -> bool:
        """校验 REQUIRED_ARTIFACTS 中声明的产物是否都存在。

        未在 REQUIRED_ARTIFACTS 中声明的组件（如 app）直接返回 True。
        """
        required = REQUIRED_ARTIFACTS.get(component)
        if not required:
            return True
        component_dir = self.target_dir / component
        if not component_dir.is_dir():
            return False
        for pattern in required:
            if any(ch in pattern for ch in "*?["):
                # glob 模式
                if not any(component_dir.glob(pattern)):
                    return False
            else:
                # 字面量文件名
                if not (component_dir / pattern).exists():
                    return False
        return True

    def store(self, component: str):
        hash_file = self.target_dir / component / ".build_hash"
        hash_file.parent.mkdir(parents=True, exist_ok=True)
        hash_file.write_text(self.compute_hash(component))

    def compute_hash(self, component: str) -> str:
        """计算组件的完整哈希（含依赖链级联）。"""
        if component in self._hash_cache:
            return self._hash_cache[component]

        h = hashlib.sha256()

        # 1. 上游依赖哈希（Merkle 链）：任一上游变化都级联失效
        for dep in DEPENDENCY_GRAPH.get(component, []):
            h.update(b"dep:")
            h.update(dep.encode())
            h.update(self.compute_hash(dep).encode())

        # 2. 全局配置：任何组件都受其影响
        for key in ("arch", "platform", "soc", "board"):
            h.update(f"{key}={self.config.get(key, '')}".encode())

        # 3. 组件特化哈希
        if component == "rootfs":
            self._mix_rootfs_customize(h)
        elif component == "app":
            self._mix_app_sources(h)
        else:
            # kernel / bootloader / boot / image
            h.update(json.dumps(
                self.config.get(component, {}),
                sort_keys=True, default=str).encode())
            self._mix_source_tree(h, component)

            # 构建产物需消费 partitions 布局的组件
            if component in ("boot", "image"):
                self._mix_partitions(h)

            # bootloader 额外依赖 rkbin firmware
            if component == "bootloader":
                self._mix_rkbin(h)

        result = h.hexdigest()[:16]
        self._hash_cache[component] = result
        return result

    # --- rootfs 分阶段缓存接口（Phase 1 base snapshot） ---

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
        return (hash_file.read_text().strip()
                == self.compute_phase_hash(component, phase))

    def store_phase(self, component: str, phase: str):
        """保存指定阶段的哈希。"""
        hash_file = self.target_dir / component / f".{phase}_hash"
        hash_file.parent.mkdir(parents=True, exist_ok=True)
        hash_file.write_text(self.compute_phase_hash(component, phase))

    # --- 哈希输入混合：rootfs ---

    def _compute_rootfs_base_hash(self) -> str:
        """Phase 1 哈希：rootfs.url + sorted(rootfs.packages) + arch。

        仅覆盖 Phase 1 的输入，不含 Phase 2 customize 的内容。
        """
        h = hashlib.sha256()
        rootfs_cfg = self.config.get("rootfs", {})
        h.update(rootfs_cfg.get("url", "").encode())
        packages = sorted(rootfs_cfg.get("packages", []))
        h.update(json.dumps(packages).encode())
        h.update(self.config.get("arch", "").encode())
        return h.hexdigest()[:16]

    def _mix_rootfs_customize(self, h: "hashlib._Hash") -> None:
        """将 rootfs customize 阶段的输入混入 h。

        注意：上游 app 依赖已由 compute_hash 在 Merkle 级联中处理，
        这里无需再 hash app deb 文件内容。
        """
        # Phase 1 基线（url + packages + arch）
        h.update(self._compute_rootfs_base_hash().encode())

        # overlay 目录递归哈希（rootfs → platform → board）
        for overlay_dir in [
            Path("rootfs/overlay"),
            Path(f"platform/{self.config.get('platform', '')}/overlay"),
            Path(f"board/{self.config['board']}/overlay"),
        ]:
            if overlay_dir.exists():
                self._hash_directory(h, overlay_dir)

        rootfs_cfg = self.config.get("rootfs", {})
        # custom_packages 列表（排序后 JSON）
        custom_packages = sorted(rootfs_cfg.get("custom_packages", []))
        h.update(json.dumps(custom_packages).encode())
        # root 密码
        h.update(rootfs_cfg.get("root_password", "").encode())
        # extra_firmware 配置（repo/branch/files 变化须触发重建）
        extra_fw = rootfs_cfg.get("extra_firmware", [])
        h.update(json.dumps(extra_fw, sort_keys=True, default=str).encode())
        # partitions 影响 rootfs.img 大小
        self._mix_partitions(h)

    # --- 哈希输入混合：app ---

    def _mix_app_sources(self, h: "hashlib._Hash") -> None:
        """将 custom_packages 列表及各 App 的完整源码内容混入 h。"""
        rootfs_cfg = self.config.get("rootfs", {})
        custom_packages: list = rootfs_cfg.get("custom_packages", [])
        h.update(json.dumps(sorted(custom_packages)).encode())
        for pkg in sorted(custom_packages):
            app_dir = Path("app") / pkg
            if app_dir.exists():
                self._hash_directory(h, app_dir)
            else:
                h.update(f"missing:{pkg}".encode())

    # --- 哈希输入混合：源码树 + 补丁（kernel/bootloader） ---

    def _mix_source_tree(self, h: "hashlib._Hash", component: str) -> None:
        """混入源码 git HEAD + 补丁文件内容。

        若源码目录或补丁目录不存在（如 boot/image 没有源码树），安全跳过。
        """
        # 源码 commit
        src_dir = Path("sources") / component / self.config["board"]
        if src_dir.exists():
            h.update(b"src:")
            h.update(self._git_head(src_dir).encode())

        # 补丁
        platform = self.config.get("platform", "")
        board = self.config["board"]
        for patch_dir in [
            Path(f"platform/{platform}/patches/{component}"),
            Path(f"board/{board}/patches/{component}"),
        ]:
            if patch_dir.exists():
                for p in sorted(patch_dir.glob("*.patch")):
                    h.update(b"patch:")
                    h.update(p.name.encode())
                    h.update(p.read_bytes())

    # --- 哈希输入混合：partitions 配置 ---

    def _mix_partitions(self, h: "hashlib._Hash") -> None:
        """混入 partitions 配置（entries 的 offset/size/type 全部参与）。"""
        partitions = self.config.get("partitions", {})
        h.update(b"partitions:")
        h.update(json.dumps(partitions, sort_keys=True, default=str).encode())

    # --- 哈希输入混合：rkbin firmware ---

    def _mix_rkbin(self, h: "hashlib._Hash") -> None:
        """混入 rkbin firmware 仓库的 git HEAD。

        bootloader 构建时会从 rkbin 读 BL31/DDR init/SPL 等二进制，
        rkbin 升级会改变这些二进制，必须触发 bootloader 重建。
        """
        fw_dir = Path(f"sources/firmware/{self.config['platform']}")
        if fw_dir.exists():
            h.update(b"rkbin:")
            h.update(self._git_head(fw_dir).encode())

    # --- 工具函数 ---

    def _git_head(self, repo_dir: Path) -> str:
        """读取指定 git 仓库的 HEAD commit hash，失败返回 'unknown'。"""
        try:
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=repo_dir, capture_output=True, text=True, check=True,
            )
            return result.stdout.strip()
        except subprocess.CalledProcessError:
            return "unknown"

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
            if path.is_symlink():
                h.update(os.readlink(path).encode())
            else:
                h.update(path.read_bytes())
