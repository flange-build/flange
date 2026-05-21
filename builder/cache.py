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
#
# recovery 组件在 image 之前构建，依赖 app（recoveryctl/adbd 通过 deb 装入
# recovery rootfs）与 kernel（共享 kernel/dtb，并安装内核模块）。
DEPENDENCY_GRAPH: dict[str, list[str]] = {
    "kernel":               [],
    "bootloader":           [],
    "app":                  [],
    # device-tree-overlay 组件依赖 kernel：编译 vendor overlay 时 cpp 需要内核
    # 源码树的 include/ 目录解析 dt-bindings 头文件。kernel 源码或配置变化级联
    # 触发 vendor overlay 重 build。
    "device-tree-overlay":  ["kernel"],
    "rootfs":               ["app", "kernel"],
    "boot":                 ["kernel", "device-tree-overlay"],
    "recovery":             ["app", "kernel"],
    "image":                ["boot", "bootloader", "rootfs", "recovery"],
}


# 各组件必须存在的产物（相对 target/<board>/<product>/<variant>/<component>/）。
# 支持字面量文件名和 glob 通配（如 "*.dtb"）。
# 缓存命中时校验这些文件存在，防止 .build_hash 有效但产物被误删导致下游失败。
# app 组件不校验：custom_packages 为空时无 deb 输出是合法状态。
# recovery 组件仅在 enabled 时校验：禁用时无产物是合法状态（运行时短路）。
# 值可以是通用产物列表，也可以是按 platform 分派的产物列表。
REQUIRED_ARTIFACTS: dict[str, list[str] | dict[str, list[str]]] = {
    "kernel":     ["Image", "*.dtb"],
    "bootloader": {
        "rockchip": ["u-boot.itb", "idbloader.img", "miniloader.bin"],
        "allwinnera733": ["boot0_sdcard.bin", "boot0_ufs.bin",
                          "boot_package.fex"],
    },
    "boot":       ["boot.img"],
    "rootfs":     ["rootfs.img"],
    "recovery":   ["recovery.img"],
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
      - rootfs base 阶段哈希 + overlay + 账号子树（root_password /
        disable_root_login / users / default_user / groups）等（rootfs）
    """

    def __init__(self, config: dict, target_base: Path = None):
        self.config = config
        board = config["board"]
        product = config.get("product", "default")
        variant = config.get("variant", "release")
        self.target_dir = (target_base or Path(".build/target")) / board / product / variant
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
        if isinstance(required, dict):
            required = required.get(self.config.get("platform", ""), [])
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
        elif component == "recovery":
            self._mix_recovery(h)
        else:
            # kernel / bootloader / boot / image / device-tree-overlay
            h.update(json.dumps(
                self.config.get(component, {}),
                sort_keys=True, default=str).encode())
            self._mix_source_tree(h, component)

            # 构建产物需消费 partitions 布局的组件
            if component in ("boot", "image"):
                self._mix_partitions(h)

            # device-tree-overlay 组件输出集由 boot.vendor_overlays /
            # boot.board_overlays + vendor 共同决定，并由板私有 dtso 源目录
            # 内容驱动，必须全部混入；否则 boot 子配置或板私有源变化不会级联
            # 到此组件。
            if component == "device-tree-overlay":
                h.update(b"vendor:")
                h.update(self.config.get("vendor", "").encode())
                h.update(b"vendor_overlays:")
                vlist = sorted(
                    (self.config.get("boot") or {}).get("vendor_overlays") or []
                )
                h.update(json.dumps(vlist).encode())
                h.update(b"board_overlays:")
                blist = sorted(
                    (self.config.get("boot") or {}).get("board_overlays") or []
                )
                h.update(json.dumps(blist).encode())
                # 板私有 dtso 源目录内容（如有）：dtso 改动须触发重 build
                board = self.config.get("board", "")
                board_dts_dir = Path(f"components/board/{board}/dtso")
                if board_dts_dir.exists():
                    h.update(b"board_overlays_src:")
                    self._hash_directory(h, board_dts_dir)
                # package overlay：名单 + 各 .dtso 源文件内容
                h.update(b"package_overlays:")
                plist = sorted(
                    (self.config.get("boot") or {}).get("package_overlays")
                    or [])
                h.update(json.dumps(plist).encode())
                for rel in sorted((self.config.get("packages_meta") or {})
                                  .get("overlay_src_paths") or []):
                    p = Path(rel)
                    if p.is_file():
                        h.update(b"package_overlay_src:")
                        h.update(rel.encode())
                        h.update(p.read_bytes())

            # bootloader 额外依赖 rkbin firmware
            if component == "bootloader":
                self._mix_rkbin(h)

            # kernel 额外依赖 OOT 模块独立源 git HEAD —— branch 跟踪
            # 场景下（如 rkwifibt develop 分支），仓库 HEAD 推进必须级联
            # 失效 kernel build。json.dumps 已覆盖声明本身的变化（repo
            # url / branch 改动），但 HEAD commit 是 ensure 后才知道的
            # 运行时事实，要单独混入。
            if component == "kernel":
                self._mix_kernel_oot_sources(h)
                # package OOT 驱动源目录内容：被选中编译的 driver 源改动须
                # 级联失效 kernel build（json.dumps(kernel) 已覆盖路径/名单，
                # 这里补内容）。
                for rel in sorted((self.config.get("packages_meta") or {})
                                  .get("kernel_src_paths") or []):
                    d = Path(rel)
                    if d.is_dir():
                        h.update(b"package_driver_src:")
                        h.update(rel.encode())
                        self._hash_directory(h, d)

        result = h.hexdigest()[:16]
        self._hash_cache[component] = result
        return result

    # --- rootfs / recovery 分阶段缓存接口（Phase 1 base snapshot） ---

    def compute_phase_hash(self, component: str, phase: str) -> str:
        """计算组件指定阶段的哈希。

        rootfs/recovery 的 base 阶段哈希分别按各自 packages 集合计算 ——
        recovery.packages 与 rootfs.packages 通常不同（recovery 维护系统
        是精简集合），各自独立缓存避免互相污染。
        """
        if component == "rootfs" and phase == "base":
            return self._compute_rootfs_base_hash()
        if component == "recovery" and phase == "base":
            return self._compute_recovery_base_hash()
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

    def _compute_recovery_base_hash(self) -> str:
        """recovery Phase 1 哈希：rootfs.url（与 normal rootfs 共用 base
        tarball） + sorted(recovery.packages) + arch。

        与 rootfs 同源 ubuntu-base tarball，但安装的 apt 包集合是 recovery
        维护系统专属（typically 精简：systemd / udev / e2fsprogs / dosfstools
        / parted / gdisk / zstd 等），独立于 rootfs.packages。
        """
        h = hashlib.sha256()
        h.update(self.config.get("rootfs", {}).get("url", "").encode())
        recovery_cfg = self.config.get("recovery", {})
        packages = sorted(recovery_cfg.get("packages", []))
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
            Path("components/rootfs/overlay"),
            Path(f"components/platform/{self.config.get('platform', '')}/overlay"),
            Path(f"components/board/{self.config['board']}/overlay"),
        ]:
            if overlay_dir.exists():
                self._hash_directory(h, overlay_dir)

        rootfs_cfg = self.config.get("rootfs", {})
        # custom_packages 列表（排序后 JSON）
        custom_packages = sorted(rootfs_cfg.get("custom_packages", []))
        h.update(json.dumps(custom_packages).encode())
        # 账号子树：root_password / disable_root_login / users / default_user
        # / groups。任一改动须触发 rootfs 重建（旧实现仅 hash root_password，
        # 新增用户或改 sudo 配置不会失效缓存，会产出陈旧镜像）。
        # json.dumps(sort_keys=True) 保证 dict 键顺序无关、嵌套结构稳定。
        account_subtree = {
            "root_password":      rootfs_cfg.get("root_password", ""),
            "disable_root_login": bool(rootfs_cfg.get("disable_root_login")),
            "users":              rootfs_cfg.get("users") or {},
            "default_user":       rootfs_cfg.get("default_user"),
            "groups":             rootfs_cfg.get("groups") or [],
        }
        h.update(b"account:")
        h.update(json.dumps(account_subtree, sort_keys=True,
                            default=str).encode())
        # extra_firmware 配置（repo/branch/files 变化须触发重建）
        extra_fw = rootfs_cfg.get("extra_firmware", [])
        h.update(json.dumps(extra_fw, sort_keys=True, default=str).encode())
        # source="local" 条目：blob 文件内容随仓库携带，config JSON 不会变,
        # 但 blob 字节变了必须重建。逐 entry 解析 components/board/<board>/
        # <src_dir>/<file> 并把字节流混入。
        board = self.config.get("board", "")
        for fw in extra_fw:
            if fw.get("source") != "local":
                continue
            src_dir = fw.get("src_dir", "")
            if not src_dir or not board:
                continue
            fw_base = Path(f"components/board/{board}/{src_dir}")
            if not fw_base.is_dir():
                continue
            self._hash_directory(h, fw_base)
        # extra_debs 配置（url/sha256/name 变化须触发重建）
        extra_debs = rootfs_cfg.get("extra_debs", [])
        h.update(json.dumps(extra_debs, sort_keys=True, default=str).encode())
        # partitions 影响 rootfs.img 大小
        self._mix_partitions(h)

    # --- 哈希输入混合：recovery ---

    def _mix_recovery(self, h: "hashlib._Hash") -> None:
        """recovery 组件特化哈希。

        上游 kernel/app 哈希已由 compute_hash 的 Merkle 级联接管，本函数只
        混入 recovery 自身可变的输入：
          - config["recovery"] 子树（packages / custom_packages / transport
            / protected_partitions / enabled）
          - rootfs.url（recovery 复用 rootfs base tarball 来源）
          - components/recovery/overlay 与平台/board 级 recovery overlay 目录
            （存在时递归哈希）
          - partitions 配置（recovery 分区大小变化要触发重建）
        """
        recovery_cfg = self.config.get("recovery", {})
        h.update(b"recovery:")
        h.update(json.dumps(recovery_cfg, sort_keys=True, default=str).encode())

        # recovery rootfs base tarball 源（与 normal rootfs 共用）
        rootfs_url = self.config.get("rootfs", {}).get("url", "")
        h.update(rootfs_url.encode())

        platform = self.config.get("platform", "")
        board = self.config.get("board", "")
        for overlay_dir in [
            Path("components/recovery/overlay"),
            Path(f"components/platform/{platform}/recovery-overlay"),
            Path(f"components/board/{board}/recovery-overlay"),
        ]:
            if overlay_dir.exists():
                self._hash_directory(h, overlay_dir)

        self._mix_partitions(h)

    # --- 哈希输入混合：app ---

    def _mix_app_sources(self, h: "hashlib._Hash") -> None:
        """将 custom_packages 列表及各 App 的完整源码内容混入 h。

        集合为 rootfs.custom_packages 与启用时 recovery.custom_packages 的并集，
        与 AppBuilder.build_all 的来源保持一致，避免 recoveryctl 改动后 app
        组件未失效。
        """
        from builder.config.apps import gather_custom_packages
        custom_packages = gather_custom_packages(self.config)
        h.update(json.dumps(custom_packages).encode())
        for pkg in custom_packages:
            app_dir = Path("components/app") / pkg
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
        src_dir = Path(".build/sources") / component / self.config["board"]
        if src_dir.exists():
            h.update(b"src:")
            h.update(self._git_head(src_dir).encode())

        # 补丁
        platform = self.config.get("platform", "")
        board = self.config["board"]
        for patch_dir in [
            Path(f"components/platform/{platform}/patches/{component}"),
            Path(f"components/board/{board}/patches/{component}"),
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
        fw_dir = Path(f".build/sources/firmware/{self.config['platform']}")
        if fw_dir.exists():
            h.update(b"rkbin:")
            h.update(self._git_head(fw_dir).encode())

    # --- 哈希输入混合：kernel.oot_sources ---

    def _mix_kernel_oot_sources(self, h: "hashlib._Hash") -> None:
        """混入 kernel.oot_sources 各独立源仓库的 git HEAD。

        典型场景：rkwifibt 仓库声明为 ``branch: develop`` 跟踪远端，仓库
        每次 ensure 时 reset 到 origin/develop 最新 commit。声明 dict 本身
        没变，但 HEAD 改了，必须靠这里把 HEAD 混入触发 kernel 重 build
        （含 OOT 模块重编 + 拷入 lib/modules 的 .ko 替换）。

        oot_sources 目录路径与 SourceManager.ensure_oot_source 一致。
        """
        raw = (self.config.get("kernel", {}) or {}).get("oot_sources", {})
        # 过滤 resolve_conditions 注入的 product/variant 伪 key（详见
        # KernelBuilder._oot_sources_config 注释）
        oot_sources = {k: v for k, v in raw.items()
                       if k not in ("product", "variant")
                       and isinstance(v, dict)}
        if not oot_sources:
            return
        h.update(b"oot_sources:")
        for name in sorted(oot_sources):
            repo_dir = Path(f".build/sources/oot-modules/{name}")
            if repo_dir.exists():
                h.update(name.encode())
                h.update(b"=")
                h.update(self._git_head(repo_dir).encode())
                h.update(b";")

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
