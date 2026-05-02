"""device-tree-overlay 组件构建策略 (vendor 无关)。

flange 的"第二来源"DT overlay：从外部 vendor overlay 仓库（默认
[radxa-overlays](https://github.com/radxa-pkg/radxa-overlays)）按
``boot.vendor_overlays`` 列表用 ``cpp + dtc`` 单独编译 ``.dtbo``，与
内核源码树的 in-tree overlay 形成两源，由 boot 组件平铺打包到同一
``/dtbs/<vendor>/overlay/`` 目录。

vendor 无关：从 ``config["vendor"]`` 读 vendor 名（如 ``rockchip`` /
``allwinner``），决定从仓库中哪个子目录取 dts。

依赖 kernel 组件的源码目录（KSRC）：``cpp`` 用 ``-I {kernel_src}/include``
解析 dts 中的 ``#include <dt-bindings/...>``。

产物：``target/device-tree-overlay/overlays/<stem>.dtbo`` 平铺单层。
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from builder.base import ComponentBuilder
from builder.dtb_overlay import vendor_overlays


def _vendor_overlays_dir(repo_src: Path, vendor: str) -> Path:
    """返回 radxa-overlays 仓库内 vendor 子目录路径。"""
    return repo_src / "arch" / "arm64" / "boot" / "dts" / vendor / "overlays"


def _format_available_stems(overlays_dir: Path, limit: int = 20) -> str:
    """格式化"可用 stem 候选"提示文本，最多列出 limit 个，附总数。"""
    if not overlays_dir.is_dir():
        return f"{overlays_dir} 不存在"
    stems = sorted(p.stem for p in overlays_dir.glob("*.dts"))
    head = stems[:limit]
    extra = f"... 共 {len(stems)} 个" if len(stems) > limit else f"共 {len(stems)} 个"
    return ", ".join(head) + ("" if not head else f" ({extra})")


class OverlaysBuilder(ComponentBuilder):
    """vendor overlay 仓库构建器（vendor 无关）。"""

    component = "device-tree-overlay"

    def build(self, config: dict) -> dict:
        """空 ``vendor_overlays`` short-circuit：仍 fetch 源码（保持内容哈希
        稳定），但不执行 cpp / dtc。这样 git ref 不变时 cache 仍命中。"""
        src_dir = self.source.ensure(self.component, config)
        self._status("源码就绪")
        # 不走 reset / patch（外部仓库不允许本地修改）
        self.compile(src_dir, config)
        return self.collect(src_dir, config)

    def configure(self, src_dir: Path, config: dict):
        pass  # 无需 configure

    def compile(self, src_dir: Path, config: dict):
        names = vendor_overlays(config)
        self._work_dir = Path(tempfile.mkdtemp(prefix="flange-overlays-"))
        self._build_dir = self._work_dir / "overlays"
        self._build_dir.mkdir()

        if not names:
            return  # short-circuit

        vendor = config.get("vendor")
        if not vendor:
            raise ValueError(
                "boot.vendor_overlays 非空但 config 缺少顶层 vendor 字段；"
                "请在 platform / SoC config 中声明 \"vendor\": \"rockchip\" / "
                "\"allwinner\" 等（与 radxa-overlays 仓库 arch/arm64/boot/dts/ "
                "下的子目录名一致）"
            )

        overlays_dir = _vendor_overlays_dir(src_dir, vendor)
        if not overlays_dir.is_dir():
            raise FileNotFoundError(
                f"vendor overlay 仓库中未找到 vendor 子目录: {overlays_dir}；"
                f"vendor={vendor!r} 是否拼写正确？"
            )

        kernel_src = self._kernel_src_dir(config)

        for stem in (n.removesuffix(".dtbo") for n in names):
            dts = overlays_dir / f"{stem}.dts"
            if not dts.is_file():
                raise FileNotFoundError(
                    f"vendor overlay 源文件不存在: {dts}；"
                    f"可用 stem 候选: {_format_available_stems(overlays_dir)}"
                )

            tmp = self._build_dir / f"{stem}.dtbo.tmp"
            dtbo = self._build_dir / f"{stem}.dtbo"

            self._status(f"编译 vendor overlay: {stem}.dtbo")
            # cpp 预处理：把 #include <dt-bindings/...> 展开
            self.docker.run([
                "cpp", "-nostdinc", "-undef",
                "-x", "assembler-with-cpp", "-E",
                "-I", str(kernel_src / "include"),
                "-I", str(overlays_dir),
                str(dts), "-o", str(tmp),
            ])
            # dtc 编译为 .dtbo（-@ 启用 phandle 标签，overlay 必备）
            self.docker.run([
                "dtc", "-@", "-I", "dts", "-O", "dtb",
                "-o", str(dtbo), str(tmp),
            ])

    def collect(self, src_dir: Path, config: dict) -> dict:
        """返回 overlays 产物目录，由 engine 拷贝到 target/device-tree-overlay/。"""
        return {"overlays": self._build_dir}

    def _kernel_src_dir(self, config: dict) -> Path:
        """解析 kernel 组件的源码目录（用作 KSRC）。

        优先使用 SourceManager.ensure 同样的解析路径——直接传 config 给它，
        与 kernel 组件 build 时拿到的目录一致；这样不依赖 kernel 是否已经
        compile，只要 fetch 完成就够（实际 device-tree-overlay 依赖 kernel
        是为了内容哈希级联，而非 compile 产物）。
        """
        return self.source.ensure("kernel", config)
