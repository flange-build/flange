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

        新模型：amp app 是自带 CMake 的独立工程，引用 components/amp 的 HAL SDK
        （经 rockchip-hal.cmake），产出从核 firmware.bin。SDK 只读引用、不就地
        构建（不再 stage 进 SDK）。amp.app 必填。
        """
        app_name = self._amp_cfg(config).get("app")
        if not app_name:
            raise ValueError(
                "amp.app 未声明：amp 固件由一个 amp 类型 app（自带 CMake、引用 HAL "
                "SDK）提供。在 board 的 amp 段设 \"app:amp\": \"<name>\"；"
                "新建用 `flange create app --type amp <name>`。")
        app_dir = Path("components/app") / app_name
        if not (app_dir / "CMakeLists.txt").is_file():
            raise FileNotFoundError(
                f"amp.app '{app_name}' 缺 CMakeLists.txt（{app_dir}）；amp app 须是"
                " 引用 rockchip-hal.cmake 的 CMake 工程。")
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
                     mem: dict) -> Path:
        """用 SDK 自带 mkimage 把从核 firmware.bin 打成 FIT amp.img。

        amp_linux.its 的 load 改成 config.cpu_base（单一事实源），与 firmware 的
        链接地址(rockchip-hal.cmake 注入的 FIRMWARE_BASE)一致；渲染到独立 tmpdir
        （不污染 git 跟踪的 SDK Image/amp_linux.its）。firmware.bin 改名为 .its
        incbin 引用的 hal<cpu>.bin（incbin 相对 .its 所在目录解析，故同放 tmpdir）。
        """
        its_txt = (Path(f"{_HAL_ROOT}/project/{soc}")
                   / "Image" / "amp_linux.its").read_text()
        its_txt = re.sub(
            r"(\bload\s*=\s*<\s*)0x[0-9a-fA-F]+(\s*>)",
            lambda m: m.group(1) + hex(mem["cpu_base"]) + m.group(2),
            its_txt)
        work = Path(tempfile.mkdtemp(prefix="flange-amp-"))
        (work / "amp_linux.its").write_text(its_txt)
        shutil.copy2(firmware_bin, work / f"hal{cpu}.bin")
        mkimage = os.path.abspath(f"{_HAL_ROOT}/tools/mkimage")
        self._status(f"AMP 打包 amp.img（FIT, load={hex(mem['cpu_base'])}）...")
        self.docker.run(
            [mkimage, "-f", "amp_linux.its", "-E", "-p", "0xe00", "amp.img"],
            cwd=str(work), label="amp:mkimage")
        return work / "amp.img"

    def _compile_rtthread(self, config: dict) -> Path:
        """RT-Thread 路径：尚未接入新的 CMake-app 模型。

        RT-Thread 自带 scons + Kconfig 构建体系，与 hal 的 CMake-app 模型不同，
        需要单独设计（app 引用 rt-thread SDK、地址 config 驱动、产出 rttN.bin →
        mkimage）。首板 tspi-rk3566 走 mode=hal；rt-thread 留待后续在 rt-thread
        目标板上设计 + 验证。
        """
        raise NotImplementedError(
            "amp.mode='rt-thread' 暂未接入 CMake-app 模型；当前仅支持 mode='hal'"
            "（amp app 经 rockchip-hal.cmake 引用 HAL SDK）。")

    # --- collect ---

    def collect(self, src_dir, config: dict) -> dict:
        amp_img = self._amp_img
        if not Path(amp_img).is_file():
            raise FileNotFoundError(f"amp.img 未生成: {amp_img}")
        return {"amp": amp_img}
