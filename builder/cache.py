"""增量构建缓存 — 基于内容哈希判断组件是否需要重建。

哈希策略（Merkle tree 风格）：
  组件哈希 = f(上游依赖哈希 + 组件自身配置 + 源码/补丁 + 其他影响产物的输入)

任一上游变更都会级联使下游哈希失效，确保增量构建始终产出一致的产物。
"""

import ast
import hashlib
import importlib
import json
import os
import re
import subprocess
from pathlib import Path

from builder.config.canonical import userspace_arch
from builder.patches import normalize_excluded_patches
from builder.paths import PROJECT_ROOT
from builder.source import SourceManager, component_source_descriptor


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
        # 裸 FIP（pyamlboot USB 推送）与 SD/eMMC dd 格式都被 flash 消费；
        # 缺门禁时缓存可以在产物已被删除的情况下命中，刷出没有 bootloader
        # 的设备。usb_bl2/usb_tpl 是旧式两段上传的备用产物，不列为必需。
        "amlogic": ["u-boot.bin", "u-boot.bin.sd.bin"],
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


# builder/ 下与任何组件产物无关的模块：刷写、在线维护、部署、脚手架与
# 清单查询。它们不参与构建，改动不应让 kernel/rootfs 等重编。其余文件
# （含未来新增的顶层模块）默认仍进指纹，漏登记只会退化为过度失效而非
# 漏失效。
BUILD_LOGIC_EXCLUDE_FILES: frozenset[str] = frozenset({
    "recovery_host.py",
    "deploy.py",
    "scaffold.py",
    "app_list.py",
    "oot_mounts.py",
})

# builder/flash/ 是唯一两半性质不同的包，按文件登记：
#
#   构建期（**进**指纹）：plan.py 与 generate.py 从 FINAL_CONFIG 推导
#   flash-config.json，model.py 是它的 schema，spi.py 合成 spi.img ——
#   这些产物都进 image 组件缓存，改它们必须让下游失效。
#
#   宿主机执行期（**不进**指纹）：strategy.py / execute.py / console.py
#   调用 rkdeveloptool、qdl 一类工具往板子里写，不产出任何构建产物。
#
# 拆包之前这两半挤在一个 1812 行的模块里，只能整文件排除 —— 于是改
# flash-config 的生成规则不会让 image 失效（漏失效），而改一句刷写命令行
# 会让整棵树重编（过失效）。两个方向的错误同时存在。
# console.py 不在排除表里：构建期的 generate.py 用它打状态行。它只是终端
# 配色，改动实际影响不到产物 —— 但"实际影响不到"是判断，不是保证。按既定
# 政策，含糊的文件一律留在指纹里：过度失效只是多花时间，漏失效是产物错误。
# 每个组件的通用入口模块。用途有两个，必须分清：
#
#   1. 求该组件的 import 闭包（"这个组件的构建实际会走到哪些代码"）。
#   2. 汇总出"已登记"文件集 —— 出现在**任何**组件闭包里的文件。
#
# 第 2 点是兜底的判据：不在任何闭包里的文件（新增的顶层模块、只经
# importlib 动态加载而 AST 看不见的模块）仍进**全部**组件的指纹。这样
# 漏登记退化为过度失效，而不是漏失效。
#
# 所以这张表必须覆盖**所有**组件，即使某个组件并不收窄 —— 漏一个组件，
# 它专属的模块就会被判成"未登记"，反过来把它塞进 kernel 的指纹里，收窄
# 当场失效。
BUILD_LOGIC_ENTRY: dict[str, str] = {
    "kernel": "kernel_base.py",
    "bootloader": "base.py",
    "rootfs": "rootfs.py",
    "recovery": "recovery.py",
    "boot": "extlinux.py",
    "image": "image.py",
    "app": "app.py",
    "amp": "app.py",
    "device-tree-overlay": "overlays.py",
}

# 真正按闭包**收窄**指纹的组件。
#
# 只对叶子组件做：它们不消费其他组件的产物，参与构建的代码是一个能静态
# 推导干净的小集合。rootfs / app / image 这类消费上游产物、且按配置动态
# 路由到大量模块的组件不在此列 —— 收窄它们的收益抵不上漏失效的风险。
#
# 收益：改 rootfs.py / app.py / 刷写代码的任何一处，kernel 与 bootloader
# 不再重编（kernel 单次 222s，bootloader 约 90s）。
BUILD_LOGIC_SCOPED: frozenset[str] = frozenset({"kernel", "bootloader"})

# 无论闭包如何，永远算进每个受限组件指纹的文件。
#
# engine.py 编排构建并把产物收集到 target 目录 —— 改它会改变落盘的内容，
# 但它 import 了几乎所有 builder，跟着它求闭包等于不收窄。所以它只贡献
# 自己这一个文件，不展开 import。
BUILD_LOGIC_ALWAYS: tuple[str, ...] = ("engine.py",)


BUILD_LOGIC_EXCLUDE_PATHS: frozenset[str] = frozenset({
    "flash/strategy.py",
    "flash/execute.py",
})

# 仅被 scaffold.py 消费的工程模板目录。
BUILD_LOGIC_EXCLUDE_DIRS: frozenset[str] = frozenset({"templates"})

# 平台包之间的 re-export（qualcommsc8280xp 直接复用 qualcommqcs6490 的实现）：
# 构建逻辑指纹只保留"当前平台目录"会把被复用的实现漏掉，改它不会让本 target
# 失效。用它跟随 import 把实际参与构建的平台包全部纳入。
_PLATFORM_IMPORT_RE = re.compile(
    r"(?:from|import)\s+builder\.platforms\.([A-Za-z_][A-Za-z0-9_]*)")

# 与任何组件产物都无关的顶层配置键：CLI 注入的输出级别、并行度，以及只被
# builder/flash/generate.py 消费的刷写身份（它们决定 flash-config.json，不进任何组件
# 产物）。
CONFIG_IRRELEVANT_ALWAYS: frozenset[str] = frozenset({
    "verbose", "quiet", "jobs",
    "flash_identity", "flash_spi_loader", "flash_storage", "flash_tool",
})

# 各组件明确**不消费**的顶层配置键。组件哈希混入「canonical 配置去掉这些
# 键」的切片，替代原先无差别混入的 jsonnet_hash（整份 canonical + 全部
# jsonnet 文件字节）——后者让改 rootfs.hostname、甚至给某个 config.jsonnet
# 加一行注释，都要重编 kernel(222s) + bootloader(127s) + app(644s)。
#
# 判据保守：只列有证据表明该组件任何代码路径都不读的键；漏登记只会退化为
# 过度失效，不会漏失效。已核实的两处跨子树消费必须保留：
#   - kernel 经 builder/dtb_overlay.py 读 boot.overlays.intree；
#   - rockchip bootloader 读 amp.enabled 校验 U-Boot AMP 选项。
CONFIG_IRRELEVANT_KEYS: dict[str, frozenset[str]] = {
    # partitions 只被 boot/image/rootfs/recovery 消费，且已由 _mix_partitions
    # 对它们显式建模；kernel/bootloader/dto 三家不读它（已 grep 全部平台核实）。
    # 不剔除的话，调一次 rootfs 的 image_size 就要赔 kernel 222s + bootloader
    # 127s + dto 6s。
    "kernel": frozenset({
        "rootfs", "recovery", "image", "storage", "amp", "partitions",
        "external_apps", "external_app_dirs",
    }),
    "bootloader": frozenset({
        "rootfs", "recovery", "image", "partitions",
        "kernel", "kernel_bsp", "kernel_device",
        "external_apps", "external_app_dirs",
    }),
    "boot": frozenset({
        "rootfs", "image", "external_apps", "external_app_dirs",
    }),
    # device-tree-overlay 依赖 kernel，实际敏感面是「自身切片 ∪ kernel 切片」：
    # 这里只列 kernel 也剔除的键，否则写了也会被 Merkle 级联带回来，徒增误导。
    "device-tree-overlay": frozenset({
        "rootfs", "recovery", "image", "storage", "amp", "partitions",
        "external_apps", "external_app_dirs",
    }),
    "amp": frozenset({
        "rootfs", "recovery", "kernel", "bootloader", "boot", "image",
        "partitions", "storage", "rkbin",
    }),
    "app": frozenset({
        "kernel", "kernel_bsp", "kernel_device", "bootloader", "boot",
        "image", "partitions", "storage", "rkbin", "amp", "vendor",
    }),
    # rootfs / recovery / image 消费面最广（分区布局、存储、上游产物路由），
    # 不做剔除。
}


# App 的编译与打包只由这几个模块决定；per-app 哈希用它替代整棵 builder/
# 的逻辑指纹，避免改 flash.py / kernel_base.py 之类无关代码就重编全部 App。
APP_LOGIC_FILES: tuple[str, ...] = (
    "builder/app.py",
    "builder/app_spec.py",
    "builder/deb.py",
    "builder/docker.py",
    "builder/config/apps.py",
    "docker/Dockerfile",
    "docker-compose.yml",
)


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
        disable_root_login / users / default_user / default_session /
        groups）等（rootfs）
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
            # 按每个 App 的产物清单逐个校验，而非只比 *.deb 总数：多 deb 的
            # vendor App（rockchip-multimedia 一家就产 17 个）会把计数门禁
            # 稀释到形同虚设 —— 删掉别的 App 的 deb 仍判"齐全"。
            from builder.config.apps import gather_custom_packages
            for package in gather_custom_packages(self.config):
                manifest = self.read_app_manifest(package)
                if manifest is None or "debs" not in manifest:
                    return False
                for name in manifest["debs"]:
                    if not (component_dir / name).is_file():
                        return False
            return True
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
        component_dir = self.target_dir / component
        # 判定阶段可能已记忆化旧 HEAD；构建/源码准备完成后必须重新计算整条
        # Merkle 链，写入实际参与构建的输入身份。
        self._hash_cache = {}
        self._atomic_write(
            component_dir / ".build_hash", self.compute_hash(component))
        # 分段指纹存档：下次判定失效时能直接指出是哪一段变了，而不是只告诉
        # 用户"要重建"（见 explain / flange why）。
        self._atomic_write(
            component_dir / ".build_hash.json",
            json.dumps(self.hash_segments(component),
                       ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        )

    def explain(self, component: str) -> dict:
        """解释该组件当前的缓存状态：命中，还是哪几段输入变了。

        返回 ``{"component", "up_to_date", "reasons": [...]}``；reasons 里每
        项形如 ``{"segment", "before", "after"}``，segment 名即重建理由（见
        hash_segments）。没有存档时 reasons 为空、理由记在 ``note``。
        """
        current = self.hash_segments(component)
        archive_path = self.target_dir / component / ".build_hash.json"
        result = {
            "component": component,
            "up_to_date": self.is_up_to_date(component),
            "reasons": [],
            "note": "",
        }
        if self._has_local_upstream(component):
            result["note"] = "组件或其上游声明了 local_path，框架放弃缓存决策"
            return result
        if not archive_path.is_file():
            result["note"] = "没有上次构建的分段存档（首次构建或缓存已清理）"
            return result
        try:
            archived = json.loads(archive_path.read_text())
        except (OSError, json.JSONDecodeError):
            result["note"] = "分段存档损坏，按未命中处理"
            return result
        for name in sorted(set(current) | set(archived)):
            before, after = archived.get(name), current.get(name)
            if before != after:
                result["reasons"].append(
                    {"segment": name, "before": before, "after": after})
        if not result["reasons"] and not result["up_to_date"]:
            result["note"] = "输入未变，但必需产物缺失"
        return result

    def compute_hash(self, component: str) -> str:
        """计算组件的完整哈希（含依赖链级联）。

        哈希由若干**具名分段**组合而成（见 hash_segments）：上游依赖、全局
        身份、配置切片、构建逻辑、组件自身输入。分段化让"为什么重建"可以被
        直接回答 —— 见 ``explain`` 与 ``flange why``。
        """
        if not hasattr(self, "_hash_cache"):
            # 兼容少量通过 ``__new__`` 构造的测试/调用方。
            self._hash_cache = {}
        if component in self._hash_cache:
            return self._hash_cache[component]

        segments = self.hash_segments(component)
        result = hashlib.sha256(
            json.dumps(segments, sort_keys=True).encode()
        ).hexdigest()[:16]
        self._hash_cache[component] = result
        return result

    def hash_segments(self, component: str) -> dict:
        """返回组件哈希的分段指纹。

        分段名即"重建理由"：
          - ``dep:<上游>``  上游组件产物变了（Merkle 级联）
          - ``identity``    平台 / SoC / 板 / 架构等构建身份
          - ``config``      该组件相关的配置切片（见 CONFIG_IRRELEVANT_KEYS）
          - ``logic``       参与构建的 builder 代码与 Docker 定义
          - ``own``         该组件自己的输入：源码、补丁、overlay、App 等
        """
        segments = {}
        for dep in DEPENDENCY_GRAPH.get(component, []):
            segments[f"dep:{dep}"] = self.compute_hash(dep)

        identity = hashlib.sha256()
        identity.update(b"cache-contract-v3")
        identity.update(f"architecture={userspace_arch(self.config)}".encode())
        for key in ("platform", "soc", "board"):
            identity.update(f"{key}={self.config.get(key, '')}".encode())
        segments["identity"] = identity.hexdigest()

        # 按组件裁剪的 canonical 配置切片，替代旧的全局 jsonnet_hash。
        # jsonnet_hash 仍保留在 ResolvedConfig 上供诊断，但不再进组件哈希：
        # 它混入了 jsonnet 源文件的原始字节，连"只加一行注释"都会让全部
        # 组件失效。切片以求值结果为准，语义不变的编辑不再触发重建。
        segments["config"] = self._config_slice_hash(component)
        segments["logic"] = self._build_logic_hash(component)
        segments["own"] = self._component_own_hash(component)
        return segments

    def _component_own_hash(self, component: str) -> str:
        """组件自身输入的指纹：源码、补丁、配置子树、overlay、App 等。"""
        h = hashlib.sha256()
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

        return h.hexdigest()

    # --- rootfs / recovery 分阶段缓存接口（Phase 1 base snapshot） ---

    def compute_phase_hash(self, component: str, phase: str) -> str:
        """计算组件指定阶段的哈希。

        用途只有一个：作为 base 快照的**文件名**（内容寻址），命中判定就是
        "这个文件名存在与否"。因此不需要另写一个 ``.base_hash`` 记录文件 ——
        文件名本身就是那条记录。

        rootfs/recovery 的 base 阶段哈希分别按各自 packages 集合计算 ——
        recovery.packages 与 rootfs.packages 通常不同（recovery 维护系统
        是精简集合），各自独立缓存避免互相污染。
        """
        if component == "rootfs" and phase == "base":
            return self._compute_rootfs_base_hash()
        if component == "recovery" and phase == "base":
            return self._compute_recovery_base_hash()
        raise ValueError(f"不支持的分阶段哈希: {component}.{phase}")

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
        # / default_session / groups。任一改动须触发 rootfs 重建（旧实现仅
        # hash root_password，新增用户或改 sudo 配置不会失效缓存，会产出
        # 陈旧镜像）。
        # json.dumps(sort_keys=True) 保证 dict 键顺序无关、嵌套结构稳定。
        account_subtree = {
            "root_password":      rootfs_cfg.get("root_password", ""),
            "disable_root_login": bool(rootfs_cfg.get("disable_root_login")),
            "users":              rootfs_cfg.get("users") or {},
            "default_user":       rootfs_cfg.get("default_user"),
            "default_session":    rootfs_cfg.get("default_session"),
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
        # panel firmware 的**文本源内容**：rootfs_cfg 的 json.dumps 只覆盖
        # src/dest 声明，改 init 序列而不改路径会命中缓存、刷出与源码不符的
        # 镜像（面板 bringup 正是反复改 init 序列的场景）。
        board = self.config.get("board", "")
        for entry in rootfs_cfg.get("panel_firmware") or []:
            source = entry.get("src") if isinstance(entry, dict) else None
            if not source:
                continue
            path = self._project_path("components", "board", board, source)
            h.update(b"panel_firmware_src:")
            h.update(str(source).encode())
            h.update(path.read_bytes() if path.is_file() else b"missing")
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
        """将 custom_packages 列表及各 App 的 per-app 哈希混入 h。

        集合为 rootfs.custom_packages 与启用时 recovery.custom_packages 的并集，
        与 AppBuilder.build_all 的来源保持一致，避免 recoveryctl 改动后 app
        组件未失效。

        单个 App 的源码内容由 ``compute_app_hash`` 覆盖（含包级附加输入与
        build.deps 级联），组件级哈希只做汇总 —— 组件失效仍会调用
        ``AppBuilder.build_all``，但 build_all 内部按 App 逐个判定，未变的
        App 直接复用既有 deb。
        """
        from builder.config.apps import gather_custom_packages
        custom_packages = gather_custom_packages(self.config)
        h.update(json.dumps(custom_packages).encode())
        for pkg in custom_packages:
            h.update(b"app:")
            h.update(pkg.encode())
            h.update(self.compute_app_hash(pkg).encode())

    # --- per-App 二级缓存（app 组件内部粒度） ---

    # 每个 App 的产物清单目录，位于 target/<b>/<p>/<v>/app/ 下。
    APP_MANIFEST_DIR = ".manifest"

    def app_manifest_path(self, app_name: str) -> Path:
        """返回单个 App 的产物清单路径。"""
        return (self.target_dir / "app" / self.APP_MANIFEST_DIR
                / f"{app_name}.json")

    def read_app_manifest(self, app_name: str) -> dict | None:
        """读取 App 产物清单；不存在或损坏返回 None。"""
        path = self.app_manifest_path(app_name)
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            return None
        return data if isinstance(data, dict) else None

    def compute_app_hash(self, app_name: str, _stack: tuple = ()) -> str:
        """计算单个 App 的内容哈希。

        输入：目标用户态 arch、App 打包逻辑指纹（APP_LOGIC_FILES，不含整棵
        builder/）、external_apps 描述符（local_path 归一化为项目相对路径，
        使宿主机与容器算出同一值）、App 源码目录递归内容、包级附加输入
        （packages_meta.app_src_paths，如 rockchip-multimedia 的 patches/），
        以及 build.deps 中同属本次构建集合的上游 App 哈希（Merkle 级联）。

        刻意**不**混入 jsonnet_hash 与整棵 builder/ 的逻辑指纹：那会让任一
        配置或任一 builder 文件改动重编全部 App，正是要消除的过度失效。
        """
        cached = getattr(self, "_app_hash_cache", None)
        if cached is None:
            cached = self._app_hash_cache = {}
        if app_name in cached:
            return cached[app_name]
        if app_name in _stack:
            # 循环依赖由 AppBuilder._resolve_build_order 显式报错，这里止步即可。
            return "cycle"

        h = hashlib.sha256()
        h.update(b"app-hash-v1")
        h.update(f"arch={userspace_arch(self.config)}".encode())
        h.update(b"logic:")
        h.update(self._app_logic_hash().encode())
        h.update(f"name={app_name}".encode())

        source_cfg = (self.config.get("external_apps") or {}).get(app_name)
        if source_cfg:
            h.update(b"source:")
            h.update(json.dumps(
                self._portable_app_source(source_cfg),
                sort_keys=True, default=str).encode())

        app_dir = self._registered_app_source_dir(app_name)
        if app_dir.is_dir():
            self._hash_directory(h, app_dir)
        else:
            h.update(f"missing:{app_name}".encode())

        for relative in self._app_extra_source_paths(app_name):
            path = Path(relative)
            if not path.is_absolute():
                path = self._project_path(relative)
            h.update(b"extra:")
            h.update(relative.encode())
            if path.is_dir():
                self._hash_directory(h, path)
            elif path.is_file():
                h.update(path.read_bytes())
            else:
                h.update(b"missing")

        for dep in self._app_build_deps(app_name):
            h.update(b"dep:")
            h.update(dep.encode())
            h.update(self.compute_app_hash(dep, _stack + (app_name,)).encode())

        result = h.hexdigest()[:16]
        cached[app_name] = result
        return result

    def is_app_up_to_date(self, app_name: str) -> bool:
        """判断单个 App 是否可跳过构建。

        与组件级 ``is_up_to_date`` 同构的三层校验：外部本地源码短路、清单
        哈希一致、清单声明的 deb 全部存在。
        """
        if self._app_source_is_local(app_name):
            return False
        manifest = self.read_app_manifest(app_name)
        if manifest is None or "debs" not in manifest:
            return False
        if manifest.get("hash") != self.compute_app_hash(app_name):
            return False
        deb_dir = self.target_dir / "app"
        for name in manifest["debs"]:
            if not (deb_dir / name).is_file():
                return False
        staging = manifest.get("staging")
        if staging and not Path(staging).is_dir():
            # 下游 App 靠这棵树拿头文件与库：它被删了就必须重建上游，
            # 否则下游会在 configure 阶段莫名其妙地失败。
            return False
        return True

    def store_app(self, app_name: str, debs: list,
                  staging: str | None = None) -> None:
        """写入单个 App 的产物清单。

        与组件级 ``store`` 不同，这里刻意复用**判定期**算出的哈希：App 源码
        是目录内容而非 git HEAD，判定后无需再解析；沿用判定期值可让"构建
        期间又改了源码"在下一次被正确检出，而不是被写成已构建。

        ``staging`` 是该 App 供下游消费的产物树（见 app.yaml 的
        ``build.staging``）。它不是 deb、不进 rootfs，但下游 App 的 configure
        依赖它，因此同样进产物门禁。
        """
        payload = {
            "hash": self.compute_app_hash(app_name),
            "debs": sorted(Path(deb).name for deb in debs),
        }
        if staging:
            payload["staging"] = staging
        self._atomic_write(
            self.app_manifest_path(app_name),
            json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n",
        )

    def _app_names_for_explain(self) -> list:
        """返回本次配置下参与构建的 App 名单（供 flange why 展开 app 组件）。"""
        from builder.config.apps import gather_custom_packages
        return gather_custom_packages(self.config)

    def _app_logic_hash(self) -> str:
        """App 打包逻辑指纹（APP_LOGIC_FILES 的内容）。"""
        cached = getattr(self, "_app_logic_hash_cache", None)
        if cached is not None:
            return cached
        h = hashlib.sha256()
        for relative in APP_LOGIC_FILES:
            path = self._project_path(relative)
            h.update(relative.encode())
            h.update(path.read_bytes() if path.is_file() else b"missing")
        self._app_logic_hash_cache = h.hexdigest()
        return self._app_logic_hash_cache

    def _portable_app_source(self, source_cfg: dict) -> dict:
        """把 external_apps 条目里的绝对 local_path 归一化为项目相对路径。

        宿主机（/Volumes/...）与容器（/workspace）看到的绝对路径不同，直接
        哈希会让同一份源码在两侧算出不同值。
        """
        return self._portable_source(source_cfg)

    def _portable_source(self, descriptor: dict) -> dict:
        """把 source descriptor 里的 local_path 归一化为机器无关表达。

        组件与 App 两侧共用一份 —— 各写一份的后果是其中一侧仍把绝对路径
        混进哈希，而这类"同一份源码算出两个值"的问题不会报错，只会表现为
        缓存莫名不命中。
        """
        if not isinstance(descriptor, dict):
            return descriptor
        local_path = descriptor.get("local_path")
        if not local_path:
            return descriptor
        portable = dict(descriptor)
        portable["local_path"] = self._portable_path(local_path)
        return portable

    def _portable_path(self, path: "Path | str") -> str:
        """把路径归一化成**与机器无关**的哈希输入。

        项目根内的路径取相对路径；项目根之外的取 `external:<末级名>`，丢掉
        机器相关的前缀。

        丢掉前缀是有意的：同一个仓库在宿主机是 /Volumes/bsp/flange，在容器里
        是 /workspace，在 CI 上又是别的路径。把绝对路径混进哈希，同一份源码
        在三处算出三个值 —— 缓存永远不命中，而现象是"明明没改却全量重建"。

        项目根之外的路径，两台机器指向的本来就是各自的检出，用末级名做身份、
        内容另行哈希才是对的。
        """
        resolved = Path(path)
        try:
            return resolved.resolve().relative_to(self.project_root).as_posix()
        except ValueError:
            return f"external:{resolved.name}"

    def _app_extra_source_paths(self, app_name: str) -> list:
        """返回该 App 声明的包级附加哈希输入（相对项目根）。

        由 ``builder/packages.py`` 在展开 vendor component 时写入
        ``packages_meta.app_src_paths``，用于覆盖位于 App 目录之外、但确实
        参与构建的内容（如 rockchip-multimedia 的 ``patches/``）。
        """
        meta = (self.config.get("packages_meta") or {}).get("app_src_paths")
        if not isinstance(meta, dict):
            return []
        return sorted(meta.get(app_name) or [])

    def _app_build_deps(self, app_name: str) -> list:
        """返回该 App 在本次构建集合内的 build.deps（与构建顺序一致）。

        集合外的依赖被 ``AppBuilder._resolve_build_order`` 忽略（视为已在
        系统中），故也不进哈希。
        """
        from builder.app_spec import load_spec
        from builder.config.apps import gather_custom_packages

        app_dir = self._registered_app_source_dir(app_name)
        if not (app_dir / "app.yaml").is_file():
            return []
        try:
            spec = load_spec(app_dir)
        except Exception:
            return []
        in_set = set(gather_custom_packages(self.config))
        return sorted(dep for dep in spec.build.deps if dep in in_set)

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
                h.update(self._portable_path(proj).encode())
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
        """返回组件实际使用的仓库配置。

        与 ComponentBuilder 共用 ``builder/source.py`` 的同一判据 —— 两处各写
        一份曾让 local_path 的两半语义只兑现了缓存那一半。
        """
        return component_source_descriptor(self.config, component)

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
        h.update(json.dumps(
            self._portable_source(descriptor),
            sort_keys=True, default=str).encode())
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
                h.update(f"missing:{self._portable_path(local_path)}".encode())
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

    def _config_slice_hash(self, component: str) -> str:
        """返回该组件相关的 canonical 配置切片指纹。

        切片 = 完整配置去掉「与所有组件无关的键」与「该组件明确不消费的键」。
        剔除表见 CONFIG_IRRELEVANT_ALWAYS / CONFIG_IRRELEVANT_KEYS。
        """
        cached = getattr(self, "_config_slice_cache", None)
        if cached is None:
            cached = self._config_slice_cache = {}
        if component in cached:
            return cached[component]
        irrelevant = (
            CONFIG_IRRELEVANT_ALWAYS
            | CONFIG_IRRELEVANT_KEYS.get(component, frozenset())
        )
        payload = {
            key: value for key, value in self.config.items()
            if key not in irrelevant
        }
        # source descriptor 里的 local_path 是绝对路径（开发者本机的检出）。
        # 直接进配置切片，会让同一份源码在宿主机、容器、CI 上算出三个不同的
        # 哈希 —— 缓存永远不命中，而现象只是"明明没改却全量重建"。
        for key in ("sources", "external_apps"):
            section = payload.get(key)
            if isinstance(section, dict):
                payload[key] = {
                    name: self._portable_source(descriptor)
                    for name, descriptor in section.items()
                }
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, default=str).encode()
        ).hexdigest()
        cached[component] = digest
        return digest

    def _build_logic_hash(self, component: str = "") -> str:
        """返回该组件参与构建的 builder 代码与 Docker 定义的内容指纹。

        排除与组件产物无关的模块（刷写 / 部署 / 脚手架 / 清单查询、脚手架
        模板）与**非当前平台**的构建规则：改 ``builder/flash/strategy.py``
        或别的平台的 kernel.py 不该让本平台的 kernel 重编。未登记的文件
        默认仍进指纹，所以漏登记只会退化为过度失效，不会漏失效。

        叶子组件（见 ``BUILD_LOGIC_SCOPED``）再进一步：只哈希它**实际
        import 到**的那些模块。范围由 AST 静态推导，不是手写清单 ——
        手写清单会随代码演进而失准，而这里失准的方向是漏失效。兜底同样
        保守：不在任何组件闭包里的文件仍进全部组件的指纹。
        """
        cache_key = component if component in BUILD_LOGIC_SCOPED else ""
        cached = getattr(self, "_logic_hash_cache", {})
        if cache_key in cached:
            return cached[cache_key]
        scope = self._build_logic_scope(cache_key) if cache_key else None
        h = hashlib.sha256()
        builder_dir = self._project_path("builder")
        platforms = self._build_logic_platforms()
        if builder_dir.is_dir():
            entries = []
            for path in builder_dir.rglob("*"):
                if not path.is_file():
                    continue
                rel = path.relative_to(builder_dir)
                if self._skip_build_logic(rel, platforms):
                    continue
                if scope is not None and rel.as_posix() not in scope:
                    continue
                entries.append((rel.as_posix(), path))
            for rel_posix, path in sorted(entries):
                h.update(rel_posix.encode())
                if path.is_symlink():
                    h.update(os.readlink(path).encode())
                else:
                    h.update(path.read_bytes())
        for relative in ("docker/Dockerfile", "docker-compose.yml"):
            path = self._project_path(relative)
            if path.is_file():
                h.update(relative.encode())
                h.update(path.read_bytes())
        cached[cache_key] = h.hexdigest()
        self._logic_hash_cache = cached
        return cached[cache_key]

    def _build_logic_scope(self, component: str) -> frozenset[str]:
        """该叶子组件实际参与构建的 builder 文件（相对 builder/ 的 posix 路径）。

        范围 = 从入口模块出发的 **import 传递闭包** ∪ **未被任何组件登记的
        文件**。两部分各自对应一类风险：

        - 闭包用 AST 静态推导而不是手写清单。手写清单会随代码演进失准，而
          这里失准的方向是**漏失效** —— 组件依赖的模块改了却不重建，产物
          是旧的，而且没有任何现象提示你。
        - 兜底把"不属于任何组件闭包"的文件仍算进来。新增一个顶层模块、或
          通过 importlib 动态加载而 AST 看不见的模块，都落在这一档：结果
          是过度失效（多编一次），不是漏失效。

        `tests/builder/test_build_logic_scope.py` 用**运行时** import 的
        真实结果反向校验闭包完整性 —— 静态分析看不见的动态导入会在那里暴露。
        """
        cached = getattr(self, "_logic_scope_cache", {})
        if component in cached:
            return cached[component]

        builder_dir = self._project_path("builder")
        platforms = self._build_logic_platforms()
        # 对**所有**组件求闭包，才能判断一个文件是否"已登记"。只对
        # BUILD_LOGIC_SCOPED 里的组件应用收窄。
        closures = {
            name: self._import_closure(builder_dir, name, platforms)
            for name in BUILD_LOGIC_ENTRY
        }
        registered = frozenset().union(*closures.values()) if closures else frozenset()

        unregistered = set()
        if builder_dir.is_dir():
            for path in builder_dir.rglob("*.py"):
                rel = path.relative_to(builder_dir).as_posix()
                if rel not in registered:
                    unregistered.add(rel)

        cached[component] = frozenset(closures[component] | unregistered)
        self._logic_scope_cache = cached
        return cached[component]

    def _import_closure(self, builder_dir: Path, component: str,
                        platforms: frozenset) -> set[str]:
        """从组件入口模块出发，沿 `builder.*` import 求传递闭包。"""
        seeds = [BUILD_LOGIC_ENTRY[component]]
        # 不展开 import 的文件：它们自身的字节要算，但跟着它们的 import 求
        # 闭包等于不收窄。
        #   - engine.py：编排构建并收集产物，引用了几乎所有 builder。
        #   - platforms/<p>/__init__.py：分派器，create_builder 里逐组件
        #     懒加载全部构建器；ARTIFACT_NAMES 影响产物收集所以要算字节，
        #     但它 import 的 rootfs/image/amp 与 kernel 无关。
        opaque = list(BUILD_LOGIC_ALWAYS)
        for platform in sorted(platforms):
            seeds.append(f"platforms/{platform}/{component}.py")
            opaque.append(f"platforms/{platform}/__init__.py")

        seen: set[str] = {
            rel for rel in opaque if (builder_dir / rel).is_file()
        }
        pending = [rel for rel in seeds if (builder_dir / rel).is_file()]
        while pending:
            rel = pending.pop()
            if rel in seen:
                continue
            seen.add(rel)
            try:
                tree = ast.parse((builder_dir / rel).read_text())
            except (OSError, SyntaxError):
                continue
            for module in self._builder_imports(tree):
                for candidate in (f"{module}.py", f"{module}/__init__.py"):
                    if (builder_dir / candidate).is_file():
                        pending.append(candidate)
        return seen

    @staticmethod
    def _builder_imports(tree: "ast.AST") -> set[str]:
        """AST 里所有 `builder.x.y` 引用，返回相对 builder/ 的模块路径。"""
        found: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                name = node.module
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("builder."):
                        found.add(alias.name[len("builder."):].replace(".", "/"))
                continue
            else:
                continue
            if name.startswith("builder."):
                found.add(name[len("builder."):].replace(".", "/"))
        return found

    def _skip_build_logic(self, rel: Path, platforms: frozenset) -> bool:
        """判断 builder/ 下的相对路径是否应排除出构建逻辑指纹。"""
        if any(part in self.HASH_EXCLUDE_DIRS for part in rel.parts[:-1]):
            return True
        if rel.suffix in self.HASH_EXCLUDE_EXTS:
            return True
        if rel.name in self.HASH_EXCLUDE_NAMES:
            return True
        if len(rel.parts) == 1 and rel.name in BUILD_LOGIC_EXCLUDE_FILES:
            return True
        if rel.as_posix() in BUILD_LOGIC_EXCLUDE_PATHS:
            return True
        if rel.parts[0] in BUILD_LOGIC_EXCLUDE_DIRS:
            return True
        # 平台构建规则只保留本 target 实际执行的那些包；platforms/__init__.py
        # 是分派入口，保留。platforms 为空表示解析不出（如测试里的假平台），
        # 此时不做过滤，保守地全部纳入。
        if (platforms and rel.parts[0] == "platforms" and len(rel.parts) > 1
                and rel.parts[1] != "__init__.py"
                and rel.parts[1] not in platforms):
            return True
        return False

    def _build_logic_platforms(self) -> frozenset:
        """返回本 target 实际执行的平台包名（跟随平台间的 re-export）。

        解析不到任何目录时返回空集，调用方据此放弃平台过滤 —— 宁可多编，
        也不能漏掉真正参与构建的实现。
        """
        cached = getattr(self, "_logic_platforms_cache", None)
        if cached is not None:
            return cached
        root = self._project_path("builder", "platforms")
        kept: set[str] = set()
        pending = [self.config.get("platform", "")]
        while pending:
            name = pending.pop()
            if not name or name in kept or not (root / name).is_dir():
                continue
            kept.add(name)
            for path in sorted((root / name).rglob("*.py")):
                if "__pycache__" in path.parts:
                    continue
                try:
                    text = path.read_text()
                except OSError:
                    continue
                pending.extend(_PLATFORM_IMPORT_RE.findall(text))
        self._logic_platforms_cache = frozenset(kept)
        return self._logic_platforms_cache

    # 目录递归哈希排除规则。
    #
    # 排除判定基于**相对被哈希目录**的路径段，而不是绝对路径：被哈希的
    # 目录自身可能就叫 ``build``（如 package 的 vendor App
    # ``components/packages/rockchip-multimedia/build/``），也可能位于
    # ``.build/`` 之下（git 来源 App 的 ``.build/sources/apps/<name>/``）。
    # 按绝对路径判定会把整棵树静默跳过，哈希退化为空目录 —— 源码改了却
    # 判定"未变"，复用陈旧产物。
    HASH_EXCLUDE_DIRS = {"__pycache__", ".git", "build", ".build", "node_modules"}
    HASH_EXCLUDE_EXTS = {".pyc", ".o"}
    # 宿主机噪声文件：未被 git 跟踪，纳入会让同一 commit 在不同机器上
    # 算出不同哈希，产生无源码改动的重建。
    HASH_EXCLUDE_NAMES = {".DS_Store"}

    def _hash_directory(self, h: "hashlib._Hash", directory: Path) -> None:
        """递归 hash 目录下所有文件（排除构建产物和临时文件）。

        按相对路径排序确保哈希稳定。
        """
        entries = []
        for path in directory.rglob("*"):
            if path.is_dir():
                continue
            rel = path.relative_to(directory)
            # 只看相对路径的目录段：文件名本身叫 build/.build 不算派生物。
            if any(part in self.HASH_EXCLUDE_DIRS for part in rel.parts[:-1]):
                continue
            if path.suffix in self.HASH_EXCLUDE_EXTS:
                continue
            if path.name in self.HASH_EXCLUDE_NAMES:
                continue
            entries.append((rel.as_posix(), path))

        for rel_posix, path in sorted(entries):
            h.update(rel_posix.encode())
            if path.is_symlink():
                h.update(os.readlink(path).encode())
            else:
                h.update(path.read_bytes())
