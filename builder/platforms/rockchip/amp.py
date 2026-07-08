"""Rockchip AMP 协处理器固件构建策略。

产物：amp.img —— SDK 自带 mkimage 用 amp_linux.its 把从核固件打成的 FIT 镜像。
产品形态 = Linux + 1 个 A55 从核：amp_linux.its 含 1 个 firmware 从核节点
（cpu3）+ linux 配置节点（cpu0/arm64）；U-Boot 先把从核拉起，再引导 Linux。

分层模型（关键）：
  - components/amp/rockchip/hal = 只读 HAL SDK（被引用，不就地构建）。SDK 经
    rockchip-hal.cmake 暴露 CMake 接口（裸机工具链 + rockchip_hal_target 函数）。
  - 从核应用代码 = 一个 amp 类型 app（components/app/<config.amp.app>，自带
    CMakeLists 引用 rockchip-hal.cmake），由本 builder 用 cmake 构建出 firmware.bin。
  本 builder（mode=hal）= 调 app 的 CMake → firmware.bin → mkimage → amp.img →
  交引擎收集/分区/刷写。不再 stage 源进 SDK、不在 SDK 里就地构建。

amp 源在 components/amp/ 与 components/app/ 仓库内（不走 .build/sources），故覆写
build() 跳过 source.ensure/reset/patch（仿 boot.py），直接 compile()+collect()。
CMake 构建在独立 tmpdir、mkimage 也在 tmpdir，均不污染 git 跟踪树。

内存布局单一事实源（config.amp.memory）：
  - 编译/链接腿：经 -DROCKCHIP_AMP_* 传给 app 的 CMakeLists → rockchip_hal_target，
    驱动 firmware 链接地址(FIRMWARE_BASE)与预处理链接脚本的 MEMORY 区。
  - 打包腿：mkimage 用 amp_linux.its，其 load 由本 builder 渲染成 config 的
    cpu_base（与链接地址一致），渲染到 tmpdir 不改 SDK 跟踪的 .its。
  - DTS 腿：由 kernel dts 交叉校验保障（见 amp-runtime-bringup spec）。
"""

import os
import re
import shutil
import tempfile
from pathlib import Path
from builder.base import ComponentBuilder
from builder.docker import BuildError
from builder.app_spec import AppSpecError, SwiftBuildConfig, load_spec

# AMP 内存布局默认值（单一事实源应由 SoC 配置 config.amp.memory 提供；此处为
# 兜底默认）。cpu_base 不用 SDK 默认 0x2800000——会与 flange ~37MB 内核镜像
# 冲突致固件保留失败；权威值见 rk3566/config.py 的 amp.memory 注释。
_DEFAULT_MEMORY = {
    "cpu": 3,                  # 从核 mpidr index（amp_linux.its 的 amp3）
    "cpu_base": 0x07000000,    # 从核固件 link/load 地址（同时写进 .its 的 load）
    "dram_size": 0x00800000,
    "sram_base": 0xFF000000,
    "sram_size": 0x00100000,
    "shmem_base": 0x07800000,
    "shmem_size": 0x00400000,
    "rpmsg_base": 0x07C00000,
    "rpmsg_size": 0x00500000,
}

_HAL_ROOT = "components/amp/rockchip/hal"
_RTT_ROOT = "components/amp/rockchip/rt-thread"
# 容器内官方裸机工具链（docker/Dockerfile 安装），供 rt-thread rtconfig.py 的
# os.getenv("RTT_EXEC_PATH") 覆盖其写死的 prebuilts 路径。
_RTT_EXEC_PATH = "/opt/arm-none-eabi-gcc10/bin"
_SWIFT_ARCHIVE_SUBDIR = "flange_swift"


class RockchipAmpBuilder(ComponentBuilder):
    component = "amp"

    def build(self, config: dict) -> dict:
        """amp 源在 components/amp/ 仓库内，跳过 source.ensure / reset / patch。"""
        self.compile(None, config)
        return self.collect(None, config)

    def configure(self, src_dir, config: dict):
        pass  # amp 无独立 configure 步骤

    # --- config 解析 ---

    def _amp_cfg(self, config: dict) -> dict:
        return config.get("amp") or {}

    def _mode(self, config: dict) -> str:
        mode = self._amp_cfg(config).get("mode", "hal")
        if mode not in ("hal", "rt-thread"):
            raise ValueError(f"amp.mode 非法: {mode!r}（须为 hal 或 rt-thread）")
        return mode

    def _soc_project(self, config: dict) -> str:
        soc = self._amp_cfg(config).get("soc_project")
        if not soc:
            raise ValueError(
                "amp.soc_project 未声明；应由 SoC 配置提供（如 rk3566 设为 'rk3568'）")
        return soc

    def _memory(self, config: dict) -> dict:
        mem = dict(_DEFAULT_MEMORY)
        mem.update(self._amp_cfg(config).get("memory") or {})
        return mem

    def _jobs(self) -> int:
        return max((os.cpu_count() or 1) - 6, 1)

    # --- compile ---

    def compile(self, src_dir, config: dict):
        # DTS 第三腿一致性：amp dts #include 的 rk3568-amp.dtsi 地址必须与
        # config.amp.memory 一致（best-effort：kernel 源就绪时校验）。
        self._assert_dts_consistency(config)
        mode = self._mode(config)
        if mode == "hal":
            self._amp_img = self._compile_hal(config)
        else:
            self._amp_img = self._compile_rtthread(config)

    def _assert_dts_consistency(self, config: dict):
        """交叉比对 kernel 的 rk3568-amp.dtsi 的 SHMEM/RPMSG 地址与 config.amp.memory。

        rk3568-amp.dtsi 提供的 amp-shmem / rpmsg 段地址必须与 config 的
        shmem_base / rpmsg_base 一致（DTS 第三腿一致性兜底）。从核固件地址
        （cpu_base）不在此校验：它由 amp.py 同时驱动 make 的 FIRMWARE_CPU_BASE
        与 amp_linux.its 的 load（单一事实源、无漂移空间），且在 board 的 amp dts
        里覆盖 amp-cpu3 entry + 固件保留区——rk3568-amp.dtsi 自带的 entry 已被
        覆盖，不再代表真实值，故不读它。kernel 源未就绪时跳过（best-effort）。
        """
        mem = self._memory(config)
        board = config.get("board", "")
        dtsi = Path(
            f".build/sources/kernel/{board}"
            "/arch/arm64/boot/dts/rockchip/rk3568-amp.dtsi")
        if not dtsi.is_file():
            self._status("跳过 dts 交叉校验：rk3568-amp.dtsi 未就绪（kernel 源未拉取）")
            return
        text = dtsi.read_text()
        checks = []
        m = re.search(r"amp-shmem@([0-9a-fA-F]+)", text)
        if m:
            checks.append(("amp_shmem", int(m.group(1), 16), mem["shmem_base"]))
        m = re.search(r"\brpmsg@([0-9a-fA-F]+)", text)
        if m:
            checks.append(("rpmsg", int(m.group(1), 16), mem["rpmsg_base"]))
        for name, dts_val, cfg_val in checks:
            if dts_val != cfg_val:
                raise ValueError(
                    f"dts 交叉校验失败：{name} dts={hex(dts_val)} != "
                    f"config.amp.memory={hex(cfg_val)}；请对齐内存布局单一事实源")
        self._status(f"dts 交叉校验通过（{len(checks)} 项 SHMEM/RPMSG 地址一致）")

    def _amp_app_dir(self, config: dict) -> Path:
        """解析 config.amp.app → amp app 工程目录（components/app/<name>）。

        amp app 按 mode 二分：
          - hal：自带 CMake 的独立工程，经 rockchip-hal.cmake 引用 HAL SDK，产
            firmware.bin（要求有 CMakeLists.txt）。
          - rt-thread：叠到 RT-Thread BSP 模板的轻量 overlay（applications/ +
            可选 .config），无 CMakeLists.txt。
        两 mode 均 SDK 只读引用、不就地构建。amp.app 必填。
        """
        app_name = self._amp_cfg(config).get("app")
        if not app_name:
            raise ValueError(
                "amp.app 未声明：amp 固件由一个 amp 类型 app 提供。在 board 的 amp "
                "段设 \"app:amp\": \"<name>\"；新建用 "
                "`flange create app --type amp --mode <hal|rt-thread> <name>`。")
        app_dir = Path("components/app") / app_name
        mode = self._mode(config)
        if mode == "hal":
            if not (app_dir / "CMakeLists.txt").is_file():
                raise FileNotFoundError(
                    f"amp.app '{app_name}' 缺 CMakeLists.txt（{app_dir}）；hal amp "
                    "app 须是引用 rockchip-hal.cmake 的 CMake 工程。")
        else:  # rt-thread
            if not (app_dir / "applications").is_dir():
                raise FileNotFoundError(
                    f"amp.app '{app_name}' 缺 applications/ 目录（{app_dir}）；"
                    "rt-thread amp app 须是叠到 BSP 模板的 overlay。")
        return app_dir

    def _compile_hal(self, config: dict) -> Path:
        """mode=hal：构建 amp app 的 CMake 工程（引用 HAL SDK 的 rockchip-hal.cmake）
        产出从核 firmware.bin，再 mkimage 打 amp.img。

        内存布局（config.amp.memory，单一事实源）经 -DROCKCHIP_AMP_* 传给 app 的
        CMakeLists → rockchip_hal_target（同时驱动 firmware 链接地址与链接脚本）。
        """
        soc = self._soc_project(config)
        mem = self._memory(config)
        cpu = mem["cpu"]
        app_dir = self._amp_app_dir(config)

        hal_cmake = os.path.abspath(f"{_HAL_ROOT}/rockchip-hal.cmake")
        build_dir = Path(tempfile.mkdtemp(prefix="flange-amp-build-"))
        self._status(
            f"AMP(cmake) 配置 {app_dir.name}（{soc.upper()}, cpu{cpu}, "
            f"base={hex(mem['cpu_base'])}）...")
        self.docker.run(
            ["cmake", "-S", str(app_dir), "-B", str(build_dir),
             f"-DCMAKE_TOOLCHAIN_FILE={hal_cmake}",
             f"-DROCKCHIP_AMP_SOC={soc.upper()}",
             f"-DROCKCHIP_AMP_CPU={cpu}",
             f"-DROCKCHIP_AMP_FIRMWARE_BASE={hex(mem['cpu_base'])}",
             f"-DROCKCHIP_AMP_DRAM_SIZE={hex(mem['dram_size'])}",
             f"-DROCKCHIP_AMP_SHMEM_BASE={hex(mem['shmem_base'])}",
             f"-DROCKCHIP_AMP_SHMEM_SIZE={hex(mem['shmem_size'])}",
             f"-DROCKCHIP_AMP_LINUX_RPMSG_BASE={hex(mem['rpmsg_base'])}",
             f"-DROCKCHIP_AMP_LINUX_RPMSG_SIZE={hex(mem['rpmsg_size'])}"],
            label="amp:cmake")
        self.docker.run(
            ["cmake", "--build", str(build_dir), f"-j{self._jobs()}"],
            label=f"amp:build:{app_dir.name}")

        firmware_bin = build_dir / "firmware.bin"
        if not firmware_bin.is_file():
            raise FileNotFoundError(
                f"amp app 未产出 firmware.bin（{firmware_bin}）；确认 CMakeLists "
                "的 executable target 名为 'firmware'（见 rockchip-hal.cmake 用法）。")
        return self._mkimage_fit(soc, firmware_bin, cpu, mem)

    def _mkimage_fit(self, soc: str, firmware_bin: Path, cpu: int,
                     mem: dict, its_path=None, incbin_name=None) -> Path:
        """用 SDK 自带 mkimage 把从核固件 .bin 打成 FIT amp.img。

        amp_linux.its 的 load 改成 config.cpu_base（单一事实源），与固件链接地址
        （hal: rockchip-hal.cmake 的 FIRMWARE_BASE；rt-thread: RTT_PRMEM_BASE）一致；
        渲染到独立 tmpdir（不污染 git 跟踪的 SDK .its）。firmware.bin 改名为 .its
        incbin 引用名（incbin 相对 .its 所在目录解析，故同放 tmpdir）。

        参数化：its_path 缺省 = HAL project 的 amp_linux.its、incbin_name 缺省 =
        hal<cpu>.bin（保持 hal 原行为）；rt-thread 传 BSP 的 amp_linux.its +
        rtt<cpu>.bin。mkimage 为通用 U-Boot 工具，两 mode 复用 HAL SDK 内置的。
        """
        if its_path is None:
            its_path = (Path(f"{_HAL_ROOT}/project/{soc}")
                        / "Image" / "amp_linux.its")
        if incbin_name is None:
            incbin_name = f"hal{cpu}.bin"
        its_txt = Path(its_path).read_text()
        its_txt = re.sub(
            r"(\bload\s*=\s*<\s*)0x[0-9a-fA-F]+(\s*>)",
            lambda m: m.group(1) + hex(mem["cpu_base"]) + m.group(2),
            its_txt)
        work = Path(tempfile.mkdtemp(prefix="flange-amp-"))
        (work / "amp_linux.its").write_text(its_txt)
        shutil.copy2(firmware_bin, work / incbin_name)
        mkimage = os.path.abspath(f"{_HAL_ROOT}/tools/mkimage")
        self._status(f"AMP 打包 amp.img（FIT, load={hex(mem['cpu_base'])}）...")
        self.docker.run(
            [mkimage, "-f", "amp_linux.its", "-E", "-p", "0xe00", "amp.img"],
            cwd=str(work), extra_mounts=[work], label="amp:mkimage")
        return work / "amp.img"

    def _rtt_bsp_dir(self, soc: str) -> Path:
        """定位 RT-Thread BSP 模板目录：<soc>-32（-32 = Cortex-A55 AArch32）。"""
        bsp = Path(_RTT_ROOT) / "bsp" / "rockchip" / f"{soc}-32"
        if not (bsp / "SConstruct").is_file():
            raise FileNotFoundError(
                f"RT-Thread BSP 模板不存在或不完整: {bsp}（缺 SConstruct）")
        return bsp

    @staticmethod
    def _merge_kconfig_fragment(base_config: Path, fragment: Path) -> None:
        """把 app 的 .config 片段按符号名合并进 staged BSP 的 .config。

        片段每行形如 `CONFIG_X=y` 或 `# CONFIG_X is not set`：同符号替换 base 中
        既有行，base 无则追加。让 rt-thread app 只需声明 Kconfig 增量（轻量 overlay）
        而非整份 .config；合并后由 scons --useconfig 从结果重生成 rtconfig.h。
        """
        def _sym(line: str):
            m = re.match(r"\s*#?\s*(CONFIG_[A-Za-z0-9_]+)", line)
            return m.group(1) if m else None

        frag_by_sym = {}
        for line in fragment.read_text().splitlines():
            s = _sym(line)
            if s:
                frag_by_sym[s] = line
        out, seen = [], set()
        for line in base_config.read_text().splitlines():
            s = _sym(line)
            if s and s in frag_by_sym:
                out.append(frag_by_sym[s])
                seen.add(s)
            else:
                out.append(line)
        for s, line in frag_by_sym.items():
            if s not in seen:
                out.append(line)
        base_config.write_text("\n".join(out) + "\n")

    def _load_amp_app_spec(self, app_dir: Path):
        """加载 amp app 的 app.yaml，并把 AppSpecError 转成带路径的错误。"""
        try:
            return load_spec(app_dir)
        except AppSpecError as exc:
            raise ValueError(f"amp app 描述文件无效（{app_dir}/app.yaml）：{exc}") from exc

    @staticmethod
    def _swift_cfg_enabled(swift_cfg) -> bool:
        return bool(swift_cfg and swift_cfg.enabled)

    def _build_swift_package(
        self,
        app_dir: Path,
        bsp_tmp: Path,
        swift_cfg: SwiftBuildConfig,
    ) -> Path:
        """用 SwiftPM 构建 Embedded Swift static archive 并复制进 staged BSP。"""
        package_dir = app_dir / swift_cfg.package_path
        if not package_dir.is_dir():
            raise FileNotFoundError(
                f"build.swift.package_path 不存在或不是目录: {package_dir}")
        if not (package_dir / "Package.swift").is_file():
            raise FileNotFoundError(
                f"SwiftPM package 缺 Package.swift: {package_dir}")

        archive_name = f"lib{swift_cfg.product}.a"
        scratch_dir = bsp_tmp / "build" / "flange-swiftpm"
        pch_dir = bsp_tmp / "build" / "flange-swift-pch"
        archive_dir = bsp_tmp / "applications" / _SWIFT_ARCHIVE_SUBDIR
        archive_dir.mkdir(parents=True, exist_ok=True)
        staged_archive = archive_dir / archive_name

        # Swift archive 曾出现重命名 object 后旧成员残留的问题；每次构建前清掉
        # scratch 与 staged archive，保证 SCons 链接的是本轮 SwiftPM 结果。
        shutil.rmtree(scratch_dir, ignore_errors=True)
        shutil.rmtree(pch_dir, ignore_errors=True)
        if staged_archive.exists():
            staged_archive.unlink()
        scratch_dir.mkdir(parents=True, exist_ok=True)
        pch_dir.mkdir(parents=True, exist_ok=True)

        self._status(
            f"AMP(scons) 构建 Embedded Swift package "
            f"{package_dir.name}:{swift_cfg.product}...")
        try:
            self.docker.run(["swift", "--version"], capture=True)
        except Exception as exc:
            raise BuildError(
                "build.swift.enabled=true 但 Docker build 容器内不可调用 swift；"
                "请先在 docker/Dockerfile 固定安装 Embedded Swift 工具链。") from exc

        cmd = [
            "swift", "build",
            "-c", "release",
            "--package-path", str(package_dir),
            "--scratch-path", str(scratch_dir),
            "--product", swift_cfg.product,
            "--triple", swift_cfg.target_triple,
            "-Xswiftc", "-target",
            "-Xswiftc", swift_cfg.target_triple,
            "-Xswiftc", "-enable-experimental-feature",
            "-Xswiftc", "Embedded",
            "-Xswiftc", "-wmo",
            "-Xswiftc", "-parse-as-library",
            "-Xswiftc", "-Osize",
            "-Xswiftc", "-no-allocations",
            "-Xswiftc", "-Xfrontend",
            "-Xswiftc", "-disable-stack-protector",
            "-Xswiftc", "-Xfrontend",
            "-Xswiftc", "-function-sections",
            "-Xswiftc", "-Xfrontend",
            "-Xswiftc", "-enable-single-module-llvm-emission",
            "-Xswiftc", "-pch-output-dir",
            "-Xswiftc", str(pch_dir),
            "-Xcc", "-mcpu=cortex-a55+crypto",
            "-Xcc", "-mfloat-abi=hard",
            "-Xcc", "-marm",
            "-Xcc", "-fno-pic",
            "-Xcc", "-fno-pie",
            "-Xcc", f"-I{app_dir / 'include'}",
            "-Xcc", f"-I{bsp_tmp}",
        ]
        cmd.extend(swift_cfg.extra_flags)
        self.docker.run(
            cmd,
            extra_mounts=[bsp_tmp.parent],
            label=f"amp:rtt:swift:{swift_cfg.product}")

        candidates = sorted(scratch_dir.rglob(archive_name))
        if not candidates:
            raise FileNotFoundError(
                f"SwiftPM 未产出 {archive_name}（scratch={scratch_dir}）")
        shutil.copy2(candidates[-1], staged_archive)
        return staged_archive

    def _stage_swift_bridge_header(
        self,
        app_dir: Path,
        applications_dir: Path,
        swift_cfg: SwiftBuildConfig,
    ) -> list[str]:
        """把 C bridge header 复制到 staged applications 并返回 SConscript include 目录。"""
        if not swift_cfg.c_header:
            return []

        header_src = app_dir / swift_cfg.c_header
        if not header_src.is_file():
            raise FileNotFoundError(
                f"build.swift.c_header 不存在: {header_src}")

        rel_parent = Path(swift_cfg.c_header).parent
        if str(rel_parent) == ".":
            header_dst_dir = applications_dir
        else:
            header_dst_dir = applications_dir / rel_parent
        header_dst_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(header_src, header_dst_dir / header_src.name)
        return [str(rel_parent)] if str(rel_parent) != "." else []

    def _write_swift_sconscript(
        self,
        applications_dir: Path,
        swift_cfg: SwiftBuildConfig,
        include_dirs: list[str],
    ) -> None:
        """在 staged applications 目录生成 SConscript，把 Swift archive 注入链接。"""
        include_exprs = ["cwd", "str(Dir('#'))"]
        for rel_dir in include_dirs:
            include_exprs.append(
                f"os.path.abspath(os.path.join(cwd, {rel_dir!r}))")
        include_exprs.append(
            f"os.path.abspath(os.path.join(cwd, {_SWIFT_ARCHIVE_SUBDIR!r}))")
        include_text = "[" + ", ".join(include_exprs) + "]"
        content = f"""from building import *
import os

cwd = GetCurrentDir()
src = Glob('*.c') + Glob('*.cpp')
CPPPATH = {include_text}
LIBPATH = [os.path.abspath(os.path.join(cwd, {_SWIFT_ARCHIVE_SUBDIR!r}))]
LIBS = [{swift_cfg.product!r}]

group = DefineGroup('Applications', src, depend = [''],
                    CPPPATH = CPPPATH, LIBPATH = LIBPATH, LIBS = LIBS)

Return('group')
"""
        (applications_dir / "SConscript").write_text(content)

    def _prepare_rtthread_swift(
        self,
        app_dir: Path,
        bsp_tmp: Path,
        swift_cfg: SwiftBuildConfig,
    ) -> Path:
        """准备 RT-Thread staged BSP 的 SwiftPM archive、头文件与 SConscript。"""
        app_sconscript = app_dir / "applications" / "SConscript"
        if app_sconscript.exists():
            raise ValueError(
                "启用 build.swift 时暂不支持 app 自带 applications/SConscript；"
                f"请删除或改由 builder 生成（{app_sconscript}）。")

        applications_dir = bsp_tmp / "applications"
        archive = self._build_swift_package(app_dir, bsp_tmp, swift_cfg)
        include_dirs = self._stage_swift_bridge_header(
            app_dir, applications_dir, swift_cfg)
        self._write_swift_sconscript(applications_dir, swift_cfg, include_dirs)
        return archive

    def _compile_rtthread(self, config: dict) -> Path:
        """mode=rt-thread：把 RT-Thread BSP 模板 stage 到 tmpdir、叠加 amp app
        overlay、由 config.amp.memory 注入 scons 环境变量后 scons 构建产出
        rtthread.bin → rtt<cpu>.bin，再 mkimage 打 amp.img。

        SDK 只读：只 stage BSP 目录（小）到 tmpdir，RTT_ROOT 指向原地只读 SDK 根；
        scons 的 variant_dir（相对 BSP 启动目录）保证 .o/产物全落 tmpdir，SDK 树
        零写入（PYTHONDONTWRITEBYTECODE=1 兜住 import SConscript 的 __pycache__）。

        内存布局单一事实源（config.amp.memory）经环境变量注入，与 hal 的 CMake -D
        落到同名下游宏：cpu_base→RTT_PRMEM_BASE→FIRMWARE_BASE，dram_size→
        RTT_PRMEM_SIZE→DRAM_SIZE，其余同名（见 rtconfig.py）。
        """
        soc = self._soc_project(config)
        mem = self._memory(config)
        cpu = mem["cpu"]
        app_dir = self._amp_app_dir(config)
        app_spec = self._load_amp_app_spec(app_dir)
        bsp_src = self._rtt_bsp_dir(soc)

        # --- stage 可写 RTT_ROOT 镜像 → tmpdir（保 SDK 只读语义）---
        # 只读庞大内核树（src/components/libcpu/include/third_party/tools）symlink 到真
        # SDK：scons 以 building.py 显式 variant_dir 把对象重定向到 tmpdir（实测不逃逸）。
        # bsp/rockchip 须整段 copy 成可写：其 common/drivers、tests 经 RTT_ROOT 绝对路径
        # 编译，且 rpmsg-lite 的 SConscript 用 GetCurrentDir()+绝对 Glob 逃逸 variant_dir
        # 就地生成 .o —— copy 后落 tmpdir 而非 SDK。bsp/rockchip/tools 仅取 buildutil.py
        # （stdlib-only；其余 32MB 是 Rockchip 刷机工具，与构建无关）。common/hal symlink
        # 复用 HAL SDK：RT-Thread SDK 未随仓 vendor 其 common/hal 子模块（HalSConscript
        # 期望 <common>/hal/lib/ 提供 hal_base.h 等），而 _HAL_ROOT 的 lib/ 布局与之逐一
        # 匹配；HAL 源经 variant_dir='common/hal' 编译、对象落 tmpdir，HAL SDK 只读。
        _ignore = shutil.ignore_patterns(
            "build", ".sconsign.dblite", "*.o", "*.pyc", "__pycache__",
            "rtthread.*", "gcc_arm.ld", "amp*.img")
        sdk_root = Path(_RTT_ROOT)
        staged_root = Path(tempfile.mkdtemp(prefix="flange-amp-rtt-"))

        def _mirror(src_dir: Path, dst_dir: Path, skip: set) -> None:
            """dst_dir 下逐项 symlink 到 src_dir（skip 的项留给调用方 copy）。"""
            dst_dir.mkdir(parents=True, exist_ok=True)
            for entry in os.listdir(src_dir):
                if entry not in skip:
                    os.symlink(os.path.abspath(src_dir / entry),
                               dst_dir / entry)

        # 顶层：除 bsp 外全 symlink（examples/documentation/… 也被部分 SConscript 引用）
        _mirror(sdk_root, staged_root, skip={"bsp"})
        # bsp：除 rockchip 外全 symlink（其它 arch，本构建不用，symlink 无害）
        _mirror(sdk_root / "bsp", staged_root / "bsp", skip={"rockchip"})
        # bsp/rockchip：仅 common + 本板 BSP 须可写（copy），其余（tools/其它板）symlink。
        # tools symlink 即可：SConstruct 以 ../tools 加 sys.path 只读导入 buildutil
        # （PYTHONDONTWRITEBYTECODE=1 兜 __pycache__）。
        bsp_rk = staged_root / "bsp" / "rockchip"
        _mirror(sdk_root / "bsp" / "rockchip", bsp_rk,
                skip={"common", f"{soc}-32"})
        bsp_tmp = bsp_rk / f"{soc}-32"
        shutil.copytree(bsp_src, bsp_tmp, ignore=_ignore)
        shutil.copytree(bsp_src.parent / "common", bsp_rk / "common",
                        ignore=_ignore)
        os.symlink(os.path.abspath(_HAL_ROOT), bsp_rk / "common" / "hal")

        # --- 叠加 app overlay：applications/ + 可选 .config 片段（合并进 BSP .config）---
        app_apps = app_dir / "applications"
        if app_apps.is_dir():
            shutil.copytree(app_apps, bsp_tmp / "applications",
                            dirs_exist_ok=True)
        overlaid_config = (app_dir / ".config").is_file()
        if overlaid_config:
            self._merge_kconfig_fragment(bsp_tmp / ".config",
                                         app_dir / ".config")

        swift_cfg = app_spec.build.swift
        if self._swift_cfg_enabled(swift_cfg):
            self._prepare_rtthread_swift(app_dir, bsp_tmp, swift_cfg)

        # --- scons 环境：只读 SDK 根 + 裸机工具链 + 内存布局（单一事实源）---
        env = {
            "RTT_ROOT": str(staged_root),
            "RTT_EXEC_PATH": _RTT_EXEC_PATH,
            "PYTHONDONTWRITEBYTECODE": "1",
            "RTT_PRMEM_BASE": hex(mem["cpu_base"]),
            "RTT_PRMEM_SIZE": hex(mem["dram_size"]),
            "RTT_SHMEM_BASE": hex(mem["shmem_base"]),
            "RTT_SHMEM_SIZE": hex(mem["shmem_size"]),
            "LINUX_RPMSG_BASE": hex(mem["rpmsg_base"]),
            "LINUX_RPMSG_SIZE": hex(mem["rpmsg_size"]),
            "CUR_CPU": str(cpu),
        }
        self._status(
            f"AMP(scons) 配置 {app_dir.name}（RT-Thread {soc}-32, cpu{cpu}, "
            f"base={hex(mem['cpu_base'])}）...")
        # overlay .config 后必须从 .config 重生成 rtconfig.h（编译实际读 rtconfig.h，
        # .config 仅是 Kconfig 状态；scons --useconfig 调 mk_rtconfig 做文本转换）。
        if overlaid_config:
            self.docker.run(
                ["scons", "--useconfig=.config"],
                cwd=str(bsp_tmp), env=env, extra_mounts=[staged_root],
                label="amp:rtt:config")
        self.docker.run(
            ["scons", f"-j{self._jobs()}"],
            cwd=str(bsp_tmp), env=env, extra_mounts=[staged_root],
            label=f"amp:rtt:build:{app_dir.name}")

        rtt_bin = bsp_tmp / "rtthread.bin"
        if not rtt_bin.is_file():
            raise FileNotFoundError(
                f"RT-Thread 未产出 rtthread.bin（{rtt_bin}）；检查 scons 日志。")
        its_path = bsp_tmp / "Image" / "amp_linux.its"
        return self._mkimage_fit(soc, rtt_bin, cpu, mem,
                                 its_path=its_path,
                                 incbin_name=f"rtt{cpu}.bin")

    # --- collect ---

    def collect(self, src_dir, config: dict) -> dict:
        amp_img = self._amp_img
        if not Path(amp_img).is_file():
            raise FileNotFoundError(f"amp.img 未生成: {amp_img}")
        return {"amp": amp_img}
