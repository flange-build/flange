"""NVIDIA Tegra186（L4T R32.7.6）内核构建器。

源码是 OE4T 的 linux-tegra-4.9 单仓：kernel-4.9 主体与 nvidia/（nvgpu、平台驱动、
DTS）已合并在一棵树里。L4T 的 DTS 位于 nvidia/platform/ 下，经
arch/arm64/boot/dts/Makefile 以 ``_ddot_`` 相对路径编进
``arch/arm64/boot/dts/_ddot_/.../<name>.dtb``，所以 DTB 按文件名在输出树中
唯一匹配后发布。L4T 默认以 ``-@`` 编译 DTB（stock DTB 自带 ``__symbols__``），
构建期合并 DTBO 无需额外参数。
"""

from pathlib import Path

from builder.config.canonical import kernel_device_tree
from builder.docker import BuildError
from builder.kernel_base import KernelBuilder


class Tegra186KernelBuilder(KernelBuilder):
    component = "kernel"
    ARCH = "arm64"

    def make(self, src_dir: Path, targets: list, **kwargs):
        # LOCALVERSION 显式置空：否则 setlocalversion 会因源码树不在 tag 上追加 "+"
        # （4.9.337+）。版本后缀只由 CONFIG_LOCALVERSION 决定，与 stock 的
        # 4.9.337-tegra 一致；每次 make 都要带，否则 kernel.release 会被重算。
        extra = [*(kwargs.pop("extra", None) or []), "LOCALVERSION="]
        super().make(src_dir, targets, extra=extra, **kwargs)

    def configure(self, src_dir: Path, config: dict):
        self._write_case_insensitive_fix(src_dir)
        for target in self._resolve_defconfig_targets(src_dir, config["kernel"]["defconfig"]):
            self.make(src_dir, [target], arch=self.ARCH, cross=self.CROSS)
        fragment = self._write_config_override_fragment(src_dir, config)
        if fragment is None:
            return
        # 与 qcs6490 相同：追加进 .config 再 olddefconfig，一次读写，不走
        # merge_config.sh 在 bind 挂载上反复 sed -i 的路径；后值覆盖前值。
        self.docker.run(
            ["sh", "-c", f"cat arch/{self.ARCH}/configs/{fragment} >> .config"],
            cwd=str(src_dir), label="追加 config 覆盖",
        )
        self.make(src_dir, ["olddefconfig"], arch=self.ARCH, cross=self.CROSS)

    def compile(self, src_dir: Path, config: dict):
        jobs = config.get("jobs", 0)
        # NVIDIA 驱动在新版 gcc 下仍有零星告警，-Wno-error 与其他平台一致兜底。
        self.make(
            src_dir, ["Image", "dtbs", "modules"],
            arch=self.ARCH, cross=self.CROSS, jobs=jobs,
            extra=[f"CC=ccache {self.CROSS}gcc", "HOSTCC=ccache gcc", "KCFLAGS=-Wno-error"],
            label="编译内核...",
        )
        self._compile_oot_modules(src_dir, config, jobs)

        modules_staging = src_dir / "_modules_staging"
        self._clean_modules_staging(modules_staging)
        modules_staging.mkdir(exist_ok=True)
        self.make(
            src_dir, ["modules_install"], arch=self.ARCH, cross=self.CROSS,
            extra=[f"INSTALL_MOD_PATH={modules_staging}", "INSTALL_MOD_STRIP=1"],
        )
        self._install_oot_modules(src_dir, config, modules_staging)
        # source/build 指向构建树绝对路径，进 rootfs 没有意义。
        for link_name in ("source", "build"):
            for link in (modules_staging / "lib" / "modules").glob(f"*/{link_name}"):
                if link.is_symlink():
                    link.unlink()

    def collect(self, src_dir: Path, config: dict) -> dict:
        return {
            "image": src_dir / f"arch/{self.ARCH}/boot/Image",
            "dtb": self._find_dtb(src_dir, config),
            "modules": src_dir / "_modules_staging",
            "config": src_dir / ".config",
        }

    def _find_dtb(self, src_dir: Path, config: dict) -> Path:
        """在 DTB 输出树中按文件名定位。

        L4T 的 dts Makefile 除了 ``_ddot_`` 嵌套路径，还会在 dts 根目录放一份
        同名拷贝；内容一致时取任一份，没有或内容不同都说明构建与配置不一致。
        """
        _, name = kernel_device_tree(config)
        dts_root = src_dir / f"arch/{self.ARCH}/boot/dts"
        matches = sorted(dts_root.rglob(f"{name}.dtb"))
        if not matches or len({path.read_bytes() for path in matches}) != 1:
            found = ", ".join(str(path.relative_to(src_dir)) for path in matches) or "无"
            raise BuildError(
                f"内核 DTB {name}.dtb 应在 {dts_root} 下存在且各份内容一致，实际匹配: {found}"
            )
        return matches[0]
