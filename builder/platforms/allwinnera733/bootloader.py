"""Allwinner A733 Bootloader 构建策略 — 源码构建模式。

从 u-boot-aw2501 仓库（含 7 个子模块）编译出：
  - boot0_sdcard.bin        SD 卡启动的 Allwinner SPL（预编译 boot0 + sys_config patch）
  - boot0_ufs.bin            UFS 启动的 SPL
  - boot_package.fex         U-Boot + BL31 + SCP 打包体（dragonsecboot -pack）

构建依赖：
  - Linaro ARM 7.2.1 (32-bit, arm-linux-gnueabi) — 编译 U-Boot
  - RISC-V 工具链                                  — 编译 AR100S SCP 固件
  - Allwinner 专有工具（tools/ 子模块）            — update_boot0, dragonsecboot 等
  - lib32stdc++6 + lib32z1                        — 运行 32-bit x86 Allwinner 工具
"""

from pathlib import Path
from builder.base import ComponentBuilder


class AllwinnerA733BootloaderBuilder(ComponentBuilder):
    component = "bootloader"

    def build(self, config: dict) -> dict:
        """从 u-boot-aw2501 源码构建 boot0 + boot_package.fex。"""
        src_dir = self.source.ensure(self.component, config)
        self._status("U-Boot 源码就绪（含子模块）")

        # 源码重置 — recurse 模式需要同时重置子模块
        if not config.get("_local_mode", {}).get(self.component):
            self._reset_with_submodules(src_dir)

        # 准备工具链：Linaro ARM（U-Boot 32-bit 编译）+ RISC-V（arisc SCP 固件）
        bl_cfg = config["bootloader"]
        # Linaro ARM → src_dir/toolchains/
        self._ensure_toolchain(
            label="Linaro ARM",
            tarball_name=bl_cfg["toolchain_tarball"],
            tarball_url=bl_cfg["toolchain_url"],
            dest_dir=src_dir / "toolchains",
        )
        # RISC-V → src_dir/arisc/ar100s/tools/（arisc Makefile 硬编码此路径）
        self._ensure_toolchain(
            label="RISC-V",
            tarball_name=bl_cfg["riscv_tarball"],
            tarball_url=bl_cfg["riscv_url"],
            dest_dir=src_dir / "arisc" / "ar100s" / "tools",
        )

        # 构建产品 target（如 radxa-cubie-a7z）
        target = config["bootloader"]["target"]
        self._status(f"编译 {target}...")
        # -j1 强制串行：Allwinner 构建规则中存在 race condition
        # （sys_config.bin 被多个 boot0 target 共享，并行时相互覆盖）
        self.docker.run(
            ["make", "-C", str(src_dir), f"-j1", target],
            label=f"make {target}...",
        )

        self._target = target
        self._src_dir = src_dir
        return self.collect(src_dir, config)

    def _reset_with_submodules(self, src_dir: Path):
        """重置主仓库 + 所有子模块。"""
        self.docker.run(["git", "checkout", "-f", "."], cwd=str(src_dir),
                        check=False)
        # 子模块同样重置（构建可能污染子模块）
        self.docker.run(
            ["git", "submodule", "foreach", "--recursive",
             "git checkout -f . && git clean -fd"],
            cwd=str(src_dir), check=False,
        )
        # 清理主仓库 untracked（保留 toolchains/、out/ 等构建产物）
        # 这里不跑 git clean -fd，因为会删除工具链和构建缓存

    def _ensure_toolchain(self, *, label: str, tarball_name: str,
                          tarball_url: str, dest_dir: Path):
        """下载并解压指定工具链到 dest_dir。

        通用化方案：传入 tarball 文件名、URL、目标目录，
        按 {dest_dir}/{tarball_stem}/ 判断是否已解压。
        """
        tarball = dest_dir / tarball_name
        extracted = dest_dir / tarball_name.replace(".tar.xz", "").replace(".tar.gz", "")

        # 验证 bin/ 非空才认为已解压（空目录残留视为未完成）
        bin_dir = extracted / "bin"
        if bin_dir.is_dir() and any(bin_dir.iterdir()):
            return  # 已解压

        dest_dir.mkdir(parents=True, exist_ok=True)
        if not tarball.exists():
            self._status(f"下载 {label} 工具链...")
            self.docker.run(
                ["wget", "-q", "-O", str(tarball), tarball_url],
                label=f"下载 {label} 工具链...",
            )
        self._status(f"解压 {label} 工具链...")
        self.docker.run(
            ["tar", "xavf", str(tarball), "-C", str(dest_dir)],
            label=f"解压 {label} 工具链...",
        )

    def configure(self, src_dir: Path, config: dict):
        pass

    def compile(self, src_dir: Path, config: dict):
        pass

    def collect(self, src_dir: Path, config: dict) -> dict:
        target = self._target
        out_dir = src_dir / "out" / target
        result = {}
        for name in ("boot0_sdcard.bin", "boot0_ufs.bin",
                     "boot0_spinor.bin", "boot_package.fex"):
            path = out_dir / name
            if path.exists():
                key = name.rsplit(".", 1)[0]  # boot0_sdcard / boot_package ...
                result[key] = path
        if not result:
            raise FileNotFoundError(
                f"bootloader 产物未找到，检查 {out_dir} 内容")
        return result
