"""增量构建缓存 — 基于内容哈希判断组件是否需要重建。

哈希策略（Merkle tree 风格）：
  组件哈希 = f(上游依赖哈希 + 组件自身配置 + 源码/补丁 + 其他影响产物的输入)

任一上游变更都会级联使下游哈希失效，确保增量构建始终产出一致的产物。
"""

import hashlib
import importlib
import json
import os
import subprocess
from pathlib import Path

from builder.config.canonical import userspace_arch
from builder.patches import normalize_excluded_patches
from builder.paths import PROJECT_ROOT
from builder.source import SourceManager


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
    # rootfs 依赖 device-tree-overlay：grub-with-dtb 平台（无运行时 overlay）
    # 在 rootfs 装内核 dtb 时需消费 .dtbo 经 fdtoverlay 预合并到 base dtb；
    # U-Boot/extlinux 平台 device-tree-overlay 产物在无 overlay 声明时为空，
    # 此依赖在那些平台是 no-op（多一条拓扑边、不增加实际工作）。
    "rootfs":               ["app", "kernel", "device-tree-overlay"],
    "boot":                 ["kernel", "device-tree-overlay"],
    "recovery":             ["app", "kernel"],
    # amp 协处理器固件（裸机 HAL / RT-Thread）是叶子组件：无上游（不需 kernel
    # 头），按 config.amp.enabled 门控（仿 recovery）。image 依赖它，使 amp.img
    # 在整盘组装前就绪；amp 关闭时 engine 短路跳过、下游 image 因 amp.img 缺失
    # 自动跳过 amp 分区。
    "amp":                  [],
    "image":                ["boot", "bootloader", "rootfs", "recovery", "amp"],
}


# 各组件默认必须存在的产物（相对 target/<board>/<product>/<variant>/<component>/）。
# 支持字面量文件名和 glob 通配（如 "*.dtb"）。
# 缓存命中时校验这些文件存在，防止 .build_hash 有效但产物被误删导致下游失败。
# app 组件不校验：custom_packages 为空时无 deb 输出是合法状态。
# recovery 组件仅在 enabled 时校验：禁用时无产物是合法状态（运行时短路）。
# 值可以是通用产物列表，也可以是按 platform 分派的产物列表。
DEFAULT_REQUIRED_ARTIFACTS: dict[str, list[str] | dict[str, list[str]]] = {
    "bootloader": {
        "rockchip": ["u-boot.itb", "idbloader.img", "miniloader.bin"],
        "allwinnera733": ["boot0_sdcard.bin", "boot0_ufs.bin",
                          "boot_package.fex"],
    },
    "boot":       ["boot.img"],
    "rootfs":     ["rootfs.img"],
    "recovery":   ["recovery.img"],
    "amp":        ["amp.img"],
    "image":      ["raw.img"],
}

# 向后兼容仍按旧常量读取 kernel 默认产物的外部代码；动态路由由
# ``BuildCache._required_artifacts`` 统一解析，不修改该兼容字典。
REQUIRED_ARTIFACTS = {
    **DEFAULT_REQUIRED_ARTIFACTS,
    "kernel": ["Image", "*.dtb"],
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

    def __init__(
        self,
        config: dict,
        target_base: Path = None,
        project_root: Path = None,
    ):
        self.config = config
        self.project_root = Path(project_root or PROJECT_ROOT).resolve()
        board = config["board"]
        product = config.get("product", "default")
        variant = config.get("variant", "release")
        default_target = self.project_root / ".build" / "target"
        self.target_dir = (target_base or default_target) / board / product / variant
        # 记忆化：避免 image→boot→kernel 等路径上重复计算
        self._hash_cache: dict[str, str] = {}

    def _project_path(self, *parts: str) -> Path:
        """按注入的项目根解析路径，兼容少量 ``__new__`` 测试调用方。"""
        return Path(getattr(self, "project_root", PROJECT_ROOT), *parts)

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
        descriptor = self._component_source_config(component)
        if descriptor.get("local_path"):
            return True
        if component == "amp":
            amp_name = (self.config.get("amp") or {}).get("app")
            if amp_name and self._app_source_is_local(amp_name):
                return True
        if component == "app":
            from builder.config.apps import gather_custom_packages
            if any(
                self._app_source_is_local(name)
                for name in gather_custom_packages(self.config)
            ):
                return True
        for dep in DEPENDENCY_GRAPH.get(component, []):
            if self._has_local_upstream(dep):
                return True
        return False

    def _app_source_is_local(self, app_name: str) -> bool:
        """外部 local_path / external_app_dirs 属于开发态本地源码。

        这类源码不依赖 git ref，组件及下游必须放弃缓存命中，确保 OOT 修改
        不会复用旧 deb、rootfs 或 amp.img。
        """
        if (self._project_path(
                "components", "app", app_name, "app.yaml")).is_file():
            return False
        source_dir = self._registered_app_source_dir(app_name)
        if not (source_dir / "app.yaml").is_file():
            return True
        try:
            source_dir.resolve().relative_to(
                self._project_path("components").resolve())
            return False
        except ValueError:
            return True

    def _required_artifacts_present(self, component: str) -> bool:
        """按 FINAL_CONFIG 路由校验组件必需产物是否都存在。

        未声明的组件（如 app）直接返回 True。kernel image、rootfs 格式与
        image GPT/MTD 输出均按当前 target 动态解析。
        """
        required = self._required_artifacts(component)
        if not required:
            return True
        component_dir = self.target_dir / component
        if not component_dir.is_dir():
            return False
        if component == "app":
            from builder.config.apps import gather_custom_packages
            return (len(list(component_dir.glob("*.deb")))
                    >= len(gather_custom_packages(self.config)))
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

    def _required_artifacts(self, component: str) -> list[str]:
        """返回当前配置下组件的必需产物列表。"""
        if component == "app":
            from builder.config.apps import gather_custom_packages
            return ["*.deb"] if gather_custom_packages(self.config) else []
        if component == "device-tree-overlay":
            from builder.dtb_overlay import (
                board_overlays,
                package_overlays,
                vendor_overlays,
            )
            names = (vendor_overlays(self.config)
                     + board_overlays(self.config)
                     + package_overlays(self.config))
            return [f"overlays/{name}" for name in names]
        if component == "kernel":
            kernel = self.config.get("kernel") or {}
            image = kernel.get("image", "Image")
            from builder.config.canonical import kernel_device_tree
            _, dts = kernel_device_tree(self.config)
            required = [image, f"{dts}.dtb" if dts else "*.dtb"]
            if kernel.get("boot_format", "extlinux") == "fit":
                required.append("boot.img")
            return required
        if component == "rootfs":
            image_format = (self.config.get("rootfs") or {}).get(
                "image_format", "ext4")
            return ["rootfs.ubi" if image_format == "ubi" else "rootfs.img"]
        if component == "image":
            partition_format = (self.config.get("partitions") or {}).get(
                "format", "gpt")
            if (self.config.get("storage") or {}).get("type") == "spinand":
                return ["mtd-bundle.json", "parameter.txt"]
            return [
                "mtd-bundle.json" if partition_format == "mtd" else "raw.img"
            ]
        if (component == "bootloader"
                and (self.config.get("bootloader") or {}).get(
                    "edk2_firmware")):
            bootloader = self.config["bootloader"]
            base = "edk2-spi-firmware/"
            required = [
                base + bootloader.get(
                    "firehose_loader", "prog_firehose_ddr.elf"),
                base + bootloader.get("spi_rawprogram", "rawprogram0.xml"),
                base + bootloader.get("spi_patch", "patch0.xml"),
            ]
            ufs_firehose = bootloader.get("ufs_firehose") or {}
            if ufs_firehose:
                required.append(base + ufs_firehose.get(
                    "filename", ufs_firehose["url"].rsplit("/", 1)[-1]))
            for asset in (bootloader.get("ufs_provisions") or {}).values():
                if not isinstance(asset, dict) or not asset.get("url"):
                    continue
                required.append(base + asset.get(
                    "filename", asset["url"].rsplit("/", 1)[-1]))
            return required

        required = DEFAULT_REQUIRED_ARTIFACTS.get(component)
        if isinstance(required, dict):
            return list(required.get(self.config.get("platform", ""), []))
        return list(required or [])

    def store(self, component: str):
        hash_file = self.target_dir / component / ".build_hash"
        # 判定阶段可能已记忆化旧 HEAD；构建/源码准备完成后必须重新计算整条
        # Merkle 链，写入实际参与构建的输入身份。
        self._hash_cache = {}
        self._atomic_write(hash_file, self.compute_hash(component))

    def compute_hash(self, component: str) -> str:
        """计算组件的完整哈希（含依赖链级联）。"""
        if not hasattr(self, "_hash_cache"):
            # 兼容少量通过 ``__new__`` 构造的测试/调用方。
            self._hash_cache = {}
        if component in self._hash_cache:
            return self._hash_cache[component]

        h = hashlib.sha256()

        # 1. 上游依赖哈希（Merkle 链）：任一上游变化都级联失效
        for dep in DEPENDENCY_GRAPH.get(component, []):
            h.update(b"dep:")
            h.update(dep.encode())
            h.update(self.compute_hash(dep).encode())

        # 2. 全局配置：任何组件都受其影响
        h.update(b"cache-contract-v2")
        h.update(f"architecture={userspace_arch(self.config)}".encode())
        for key in ("platform", "soc", "board"):
            h.update(f"{key}={self.config.get(key, '')}".encode())
        # Jsonnet 求值元数据通过 dict 子类属性携带，不污染 canonical JSON。
        # 任一实际 import 或 target 维度变化都必须使全部组件缓存失效。
        h.update(b"jsonnet_config:")
        h.update(getattr(self.config, "jsonnet_hash", "").encode())
        h.update(b"build_logic:")
        h.update(self._build_logic_hash().encode())

        # 3. 组件特化哈希
        if component == "rootfs":
            self._mix_rootfs_customize(h)
        elif component == "app":
            self._mix_app_sources(h)
        elif component == "recovery":
            self._mix_recovery(h)
        elif component == "amp":
            self._mix_amp_sources(h)
        else:
            # kernel / bootloader / boot / image / device-tree-overlay
            h.update(json.dumps(
                self.config.get(component, {}),
                sort_keys=True, default=str).encode())
            self._mix_source_tree(h, component)

            # 构建产物需消费 partitions 布局的组件
            if component in ("boot", "image"):
                self._mix_partitions(h)

            # device-tree-overlay 组件输出集由 boot.overlays.vendor /
            # boot.overlays.board + vendor 共同决定，并由板私有 dtso 源目录
            # 内容驱动，必须全部混入；否则 boot 子配置或板私有源变化不会级联
            # 到此组件。
            if component == "device-tree-overlay":
                from builder.dtb_overlay import (
                    board_overlays,
                    package_overlays,
                    vendor_overlays,
                )
                h.update(b"vendor:")
                h.update(self.config.get("vendor", "").encode())
                h.update(b"vendor_overlays:")
                vlist = sorted(vendor_overlays(self.config))
                h.update(json.dumps(vlist).encode())
                h.update(b"board_overlays:")
                blist = sorted(board_overlays(self.config))
                h.update(json.dumps(blist).encode())
                # 板私有 dtso 源目录内容（如有）：dtso 改动须触发重 build
                board = self.config.get("board", "")
                board_dts_dir = self._project_path(
                    "components", "board", board, "dtso")
                if board_dts_dir.exists():
                    h.update(b"board_overlays_src:")
                    self._hash_directory(h, board_dts_dir)
                # package overlay：名单 + 各 .dtso 源文件内容
                h.update(b"package_overlays:")
                plist = sorted(package_overlays(self.config))
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
                h.update(b"rkbin_config:")
                h.update(json.dumps(
                    self.config.get("rkbin") or {}, sort_keys=True,
                    default=str).encode())
                self._mix_rkbin(h)
                self._mix_source(h, "amlogic-boot-fip")

            # kernel 额外依赖 OOT 模块独立源 git HEAD —— branch 跟踪
            # 场景下（如 rkwifibt develop 分支），仓库 HEAD 推进必须级联
            # 失效 kernel build。json.dumps 已覆盖声明本身的变化（repo
            # url / branch 改动），但 HEAD commit 是 ensure 后才知道的
            # 运行时事实，要单独混入。
            if component == "kernel":
                for name in ("kernel_bsp", "kernel_device"):
                    cfg = self.config.get(name) or {}
                    h.update(f"{name}:".encode())
                    h.update(json.dumps(
                        cfg, sort_keys=True, default=str).encode())
                    self._mix_extra_repo(h, name, cfg)
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

            if component == "boot":
                h.update(b"recovery_enabled:")
                h.update(str(bool((self.config.get("recovery") or {}).get(
                    "enabled", False))).encode())

            if component == "image":
                for key in ("storage", "rkbin"):
                    h.update(f"{key}:".encode())
                    h.update(json.dumps(
                        self.config.get(key) or {}, sort_keys=True,
                        default=str).encode())

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
        self._atomic_write(hash_file, self.compute_phase_hash(component, phase))

    @staticmethod
    def _atomic_write(path: Path, content: str) -> None:
        """在同目录写临时文件后原子替换，避免中断留下半个哈希。"""
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f"{path.name}.tmp")
        temporary.write_text(content)
        os.replace(temporary, path)

    # --- 哈希输入混合：rootfs ---

    def _compute_rootfs_base_hash(self) -> str:
        """Phase 1 哈希：可信 tarball、APT 输入、arch 与 emulator。

        仅覆盖 Phase 1 的输入，不含 Phase 2 customize 的内容。
        """
        h = hashlib.sha256()
        rootfs_cfg = self.config.get("rootfs", {})
        h.update(rootfs_cfg.get("url", "").encode())
        h.update(rootfs_cfg.get("sha256", "").encode())
        packages = sorted(rootfs_cfg.get("packages", []))
        h.update(json.dumps(packages).encode())
        h.update(json.dumps(bool(
            rootfs_cfg.get("install_recommends", False)
        )).encode())
        h.update(json.dumps(
            rootfs_cfg.get("extra_apt_sources") or [],
            sort_keys=True, default=str).encode())
        h.update(userspace_arch(self.config).encode())
        h.update(rootfs_cfg.get("emulator", "").encode())
        return h.hexdigest()[:16]

    def _compute_recovery_base_hash(self) -> str:
        """recovery Phase 1 哈希：rootfs.url（与 normal rootfs 共用 base
        tarball） + sorted(recovery.packages) + arch。

        与 rootfs 同源 ubuntu-base tarball，但安装的 apt 包集合是 recovery
        维护系统专属（typically 精简：systemd / udev / e2fsprogs / dosfstools
        / parted / gdisk / zstd 等），独立于 rootfs.packages。
        """
        h = hashlib.sha256()
        rootfs_cfg = self.config.get("rootfs", {})
        h.update(rootfs_cfg.get("url", "").encode())
        h.update(rootfs_cfg.get("sha256", "").encode())
        recovery_cfg = self.config.get("recovery", {})
        packages = sorted(recovery_cfg.get("packages", []))
        h.update(json.dumps(packages).encode())
        h.update(userspace_arch(self.config).encode())
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
            self._project_path("components", "rootfs", "overlay"),
            self._project_path(
                "components", "platform",
                self.config.get("platform", ""), "overlay"),
            self._project_path(
                "components", "board", self.config["board"], "overlay"),
        ]:
            if overlay_dir.exists():
                self._hash_directory(h, overlay_dir)

        rootfs_cfg = self.config.get("rootfs", {})
        # builder/rootfs.py 与平台实现会消费 hostname、软件源、firmware、
        # image route 等完整子树；以完整配置作为 customize 契约，避免新增字段
        # 时再次出现漏 hash。
        h.update(b"rootfs_config:")
        h.update(json.dumps(rootfs_cfg, sort_keys=True, default=str).encode())
        h.update(b"storage:")
        h.update(json.dumps(
            self.config.get("storage") or {}, sort_keys=True,
            default=str).encode())
        # 输出路由与 UBI 几何直接决定最终 rootfs 产物；不影响 Phase 1 base
        # 内容，故只进入 customize hash。
        rootfs_route = {
            "image_format": rootfs_cfg.get("image_format", "ext4"),
            "ubi": rootfs_cfg.get("ubi") or {},
        }
        h.update(b"rootfs_route:")
        h.update(json.dumps(
            rootfs_route, sort_keys=True, default=str).encode())
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
        # extra_firmware 配置和 source 内容变化须触发重建。
        extra_fw = rootfs_cfg.get("extra_firmware", [])
        h.update(json.dumps(extra_fw, sort_keys=True, default=str).encode())
        for _, cfg in self._repo_firmware():
            self._mix_source(h, cfg["source"]["name"])
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
            self._project_path("components", "recovery", "overlay"),
            self._project_path(
                "components", "platform", platform, "recovery-overlay"),
            self._project_path(
                "components", "board", board, "recovery-overlay"),
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
            source_cfg = (self.config.get("external_apps") or {}).get(pkg)
            if source_cfg:
                h.update(json.dumps(
                    source_cfg, sort_keys=True, default=str).encode())
            app_dir = self._registered_app_source_dir(pkg)
            if app_dir.exists():
                self._hash_directory(h, app_dir)
            else:
                h.update(f"missing:{pkg}".encode())

    def _registered_app_source_dir(self, app_name: str) -> Path:
        """只读解析 App 源目录，不触发网络 clone。"""
        local = self._project_path("components", "app", app_name)
        if (local / "app.yaml").is_file():
            return local
        external = (self.config.get("external_apps") or {}).get(app_name) or {}
        if external.get("local_path"):
            return Path(external["local_path"])
        if external.get("git"):
            return self._project_path(".build", "sources", "apps", app_name)
        for directory in self.config.get("external_app_dirs") or []:
            candidate = Path(directory) / app_name
            if (candidate / "app.yaml").is_file():
                return candidate
        return local

    # --- 哈希输入混合：amp ---

    def _mix_amp_sources(self, h: "hashlib._Hash") -> None:
        """amp 组件特化哈希。

        amp 源在 components/amp/ 仓库内（不走 .build/sources），现有
        _mix_source_tree 抓不到，故单独混入。为避免给每块板（amp 默认关）都
        遍历庞大 SDK 目录，仅在 amp.enabled 时哈希实际用到的工程子树：
          - config.amp 子树（enabled/mode/soc_project/memory/app）—— 始终（廉价）
          - 启用时：平台专属的 amp 工程目录 + amp.app 指向的源码目录

        AMP 非 Rockchip/rk3568 专属——amp 源的目录布局是**平台专属知识**
        （rockchip 是 hal/project/<soc> 或 rt-thread/bsp/...，别的平台不同）。
        故 cache 保持平台无关：委托平台模块的可选 ``amp_source_dirs(config)``
        返回需哈希的目录（无该函数则不混入 SDK 目录，仅靠 config.amp 哈希）。
        """
        amp_cfg = self.config.get("amp", {})
        h.update(b"amp:")
        h.update(json.dumps(amp_cfg, sort_keys=True, default=str).encode())
        if not amp_cfg.get("enabled"):
            return  # 禁用：仅 hash 配置，跳过 SDK 目录遍历（既有板零开销）

        for proj in self._amp_source_dirs():
            if proj.is_dir():
                h.update(b"amp_proj:")
                h.update(str(proj).encode())
                self._hash_directory(h, proj)
        # amp.app 用户工程源（平台无关，复用 app 体系的 components/app/<name>）
        app_name = amp_cfg.get("app")
        if app_name:
            source_cfg = (self.config.get("external_apps") or {}).get(app_name)
            if source_cfg:
                h.update(json.dumps(
                    source_cfg, sort_keys=True, default=str).encode())
            app_dir = self._registered_app_source_dir(app_name)
            if app_dir.is_dir():
                h.update(b"amp_app:")
                self._hash_directory(h, app_dir)

    def _amp_source_dirs(self) -> list:
        """委托平台模块解析 amp 工程源目录（平台专属布局知识）。

        平台模块可选导出 ``amp_source_dirs(config) -> list[str]``；未导出则返回
        空（cache 不混入 SDK 目录，仅靠 config.amp 哈希）。仿 engine 用
        importlib 取平台模块，保持 cache 平台无关。
        """
        platform = self.config.get("platform", "")
        if not platform:
            return []
        try:
            mod = importlib.import_module(f"builder.platforms.{platform}")
        except Exception:
            return []
        fn = getattr(mod, "amp_source_dirs", None)
        if fn is None:
            return []
        try:
            paths = []
            for value in fn(self.config):
                path = Path(value)
                paths.append(
                    path if path.is_absolute() else self._project_path(value)
                )
            return paths
        except Exception:
            return []

    # --- 哈希输入混合：源码树 + 补丁（kernel/bootloader） ---

    def _mix_source_tree(self, h: "hashlib._Hash", component: str) -> None:
        """混入源码 git HEAD + 补丁文件内容。

        若源码目录或补丁目录不存在（如 boot/image 没有源码树），安全跳过。
        """
        # 源码 commit
        project_root = Path(getattr(self, "project_root", PROJECT_ROOT))
        component_config = self.config.get(component, {}) or {}
        source_name = (component_config.get("source") or {}).get("name")
        descriptor = (self.config.get("sources") or {}).get(source_name) or {}
        if descriptor.get("local_path"):
            src_dir = Path(descriptor["local_path"])
        elif descriptor:
            src_dir = (
                project_root / ".build" / "sources" / "repos"
                / SourceManager.source_identity(descriptor)
            )
        else:
            return
        if src_dir.exists():
            h.update(b"src:")
            h.update(self._git_head(src_dir).encode())

        # 补丁
        platform = self.config.get("platform", "")
        board = self.config["board"]
        excluded = set(normalize_excluded_patches(
            (self.config.get(component) or {}).get("exclude_patches"),
            f"{component}.exclude_patches",
        ))
        for patch_dir in [
            project_root / "components" / "platform" / platform
            / "patches" / component,
            project_root / "components" / "board" / board
            / "patches" / component,
        ]:
            if patch_dir.exists():
                for p in sorted(patch_dir.glob("*.patch")):
                    relative = p.relative_to(project_root).as_posix()
                    if p.name in excluded or relative in excluded:
                        continue
                    h.update(b"patch:")
                    h.update(p.name.encode())
                    h.update(p.read_bytes())

    def _component_source_config(self, component: str) -> dict:
        """返回组件实际使用的仓库配置。"""
        source_name = (
            (self.config.get(component) or {}).get("source") or {}
        ).get("name")
        return (self.config.get("sources") or {}).get(source_name, {}) or {}

    # --- 哈希输入混合：partitions 配置 ---

    def _mix_partitions(self, h: "hashlib._Hash") -> None:
        """混入 partitions 配置与 parameter 文件内容。"""
        partitions = self.config.get("partitions", {})
        h.update(b"partitions:")
        h.update(json.dumps(partitions, sort_keys=True, default=str).encode())
        parameter = partitions.get("parameter")
        if parameter:
            path = Path(parameter)
            if not path.is_absolute():
                path = self._project_path(str(path))
            h.update(b"parameter:")
            if path.is_file():
                h.update(path.read_bytes())
            else:
                h.update(f"missing:{parameter}".encode())

    # --- 哈希输入混合：rkbin firmware ---

    def _mix_rkbin(self, h: "hashlib._Hash") -> None:
        """混入 rkbin firmware 仓库的 git HEAD。

        bootloader 构建时会从 rkbin 读 BL31/DDR init/SPL 等二进制，
        rkbin 升级会改变这些二进制，必须触发 bootloader 重建。
        """
        source = (self.config.get("rkbin") or {}).get("source") or {}
        if source.get("name"):
            self._mix_source(h, source["name"])

    def _mix_source(self, h: "hashlib._Hash", name: str) -> None:
        """混入 canonical source descriptor 与当前 HEAD（存在时）。"""
        descriptor = (self.config.get("sources") or {}).get(name)
        if not descriptor:
            return
        h.update(f"source:{name}:".encode())
        h.update(json.dumps(descriptor, sort_keys=True, default=str).encode())
        local_path = descriptor.get("local_path")
        if local_path:
            path = Path(local_path)
            if not path.is_absolute():
                path = self._project_path(local_path)
            if path.is_dir():
                self._hash_directory(h, path)
            elif path.is_file():
                h.update(path.read_bytes())
            else:
                h.update(f"missing:{local_path}".encode())
            return
        repo_dir = self._project_path(
            ".build", "sources", "repos",
            SourceManager.source_identity(descriptor),
        )
        if repo_dir.exists():
            h.update(self._git_head(repo_dir).encode())

    def _mix_extra_repo(self, h: "hashlib._Hash", name: str,
                        cfg: dict) -> None:
        """混入 SourceManager.ensure_extra 对应仓库的 HEAD。"""
        source_name = (cfg.get("source") or {}).get("name")
        if source_name:
            self._mix_source(h, source_name)

    def _repo_firmware(self):
        """迭代 rootfs 中引用 canonical source 的 firmware。"""
        for entry in (self.config.get("rootfs") or {}).get(
                "extra_firmware") or []:
            if isinstance(entry.get("source"), dict):
                yield entry.get("name", "firmware"), entry

    # --- 哈希输入混合：kernel.oot_sources ---

    def _mix_kernel_oot_sources(self, h: "hashlib._Hash") -> None:
        """混入 kernel.oot_sources 各独立源仓库的 git HEAD。

        典型场景：rkwifibt 仓库声明为 ``branch: develop`` 跟踪远端，仓库
        每次 ensure 时 reset 到 origin/develop 最新 commit。声明 dict 本身
        没变，但 HEAD 改了，必须靠这里把 HEAD 混入触发 kernel 重 build
        （含 OOT 模块重编 + 拷入 lib/modules 的 .ko 替换）。

        oot_sources 目录路径与 SourceManager.ensure_oot_source 一致。
        """
        oot_sources = (
            (self.config.get("kernel") or {}).get("oot_sources") or {}
        )
        if not oot_sources:
            return
        h.update(b"oot_sources:")
        for name in sorted(oot_sources):
            self._mix_source(h, oot_sources[name]["source"]["name"])
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

    def _build_logic_hash(self) -> str:
        """返回 builder 与 Docker 构建定义的一次性内容指纹。"""
        cached = getattr(self, "_logic_hash_cache", None)
        if cached is not None:
            return cached
        h = hashlib.sha256()
        builder_dir = self._project_path("builder")
        if builder_dir.is_dir():
            self._hash_directory(h, builder_dir)
        for relative in ("docker/Dockerfile", "docker-compose.yml"):
            path = self._project_path(relative)
            if path.is_file():
                h.update(relative.encode())
                h.update(path.read_bytes())
        self._logic_hash_cache = h.hexdigest()
        return self._logic_hash_cache

    # 目录递归哈希排除规则
    HASH_EXCLUDE_DIRS = {"__pycache__", ".git", "build", ".build", "node_modules"}
    HASH_EXCLUDE_EXTS = {".pyc", ".o"}

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
