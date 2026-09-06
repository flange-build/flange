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

import ast
import os
import re
import shlex
import shutil
from pathlib import Path
from builder.base import ComponentBuilder
from builder.config.canonical import kernel_arch, kernel_device_tree
from builder.docker import BuildError
from builder.app_spec import AppSpecError, SwiftBuildConfig, load_spec

# AMP 内存布局默认值（单一事实源应由 SoC 配置 config.amp.memory 提供；此处为
# 兜底默认）。cpu_base 不用 SDK 默认 0x2800000——会与 flange ~37MB 内核镜像
# 冲突致固件保留失败；权威值见 rk3566/config.jsonnet 的 amp.memory 注释。
_DEFAULT_MEMORY = {
    "cpu": 3,  # 从核 mpidr index（amp_linux.its 的 amp3）
    "cpu_base": 0x07000000,  # 从核固件 link/load 地址（同时写进 .its 的 load）
    "dram_size": 0x00800000,
    "sram_base": 0xFF000000,
    "sram_size": 0x00100000,
    "shmem_base": 0x07800000,
    "shmem_size": 0x00400000,
    "rpmsg_base": 0x07C00000,
    "rpmsg_size": 0x00500000,
}

# 容器内官方裸机工具链（docker/Dockerfile 安装），供 rt-thread rtconfig.py 的
# os.getenv("RTT_EXEC_PATH") 覆盖其写死的 prebuilts 路径。
_RTT_EXEC_PATH = "/opt/arm-none-eabi-gcc10/bin"
_RTT_READELF = f"{_RTT_EXEC_PATH}/arm-none-eabi-readelf"
_RTT_NM = f"{_RTT_EXEC_PATH}/arm-none-eabi-nm"
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
            raise ValueError("amp.soc_project 未声明；应由 SoC 配置提供（如 rk3566 设为 'rk3568'）")
        return soc

    def _memory(self, config: dict) -> dict:
        mem = dict(_DEFAULT_MEMORY)
        mem.update(self._amp_cfg(config).get("memory") or {})
        return mem

    def _runtime(self, config: dict) -> dict:
        """读取 SoC AMP runtime profile，不在 builder 内按板名/SoC 猜值。"""
        runtime = self._amp_cfg(config).get("runtime") or {}
        required = (
            "amp_mpidr",
            "linux_mpidr",
            "linux_arch",
            "cpu_delete",
            "link_id",
            "mailboxes",
            "mailbox_irq",
            "endpoint_address",
            "endpoint_name",
            "gic_profile",
            "minimum_heap_size",
        )
        missing = [field for field in required if runtime.get(field) is None]
        if missing:
            raise ValueError("amp.runtime 缺少 SoC 通信字段: " + ", ".join(missing))
        minimum_heap_size = runtime["minimum_heap_size"]
        if (
            isinstance(minimum_heap_size, bool)
            or not isinstance(minimum_heap_size, int)
            or minimum_heap_size <= 0
        ):
            raise ValueError("amp.runtime.minimum_heap_size 必须是正整数 byte 数")
        return runtime

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
        """按 kernel arch/DTS include closure 校验 AMP 内存与 runtime profile。"""
        mem = self._memory(config)
        runtime = self._runtime(config)
        if self.source is None:
            self._status("跳过 dts 交叉校验：kernel source manager 不可用")
            return
        kernel_root = self.source.source_path("kernel", config)
        arch = kernel_arch(config)
        dts_root = kernel_root / "arch" / arch / "boot" / "dts"
        dts_dir, dts = kernel_device_tree(config)
        target = dts_root / dts_dir / f"{dts}.dts"
        if not target.is_file():
            self._status(f"跳过 dts 交叉校验：目标 DTS 未就绪（{target}）")
            return
        text = self._read_dts_closure(target, dts_root)
        regions = self._dts_regions(text)
        self._require_region(regions, "shmem", mem["shmem_base"], mem["shmem_size"])
        self._require_contiguous_region(regions, "rpmsg", mem["rpmsg_base"], mem["rpmsg_size"])
        self._require_region(regions, "sram", mem["sram_base"], mem["sram_size"])
        if runtime.get("firmware_reserved_in_dts", True):
            self._require_region(regions, "firmware", mem["cpu_base"], mem["dram_size"])

        cpu_delete = runtime["cpu_delete"]
        if not re.search(rf"/delete-node/\s+{re.escape(cpu_delete)}\s*;", text):
            raise ValueError(f"dts 交叉校验失败：未从 Linux 删除 {cpu_delete}")
        links = re.findall(r"rockchip,link-id\s*=\s*<\s*(0x[0-9a-fA-F]+|\d+)", text)
        actual = int(links[-1], 0) if links else None
        if actual != runtime["link_id"]:
            raise ValueError(
                f"dts 交叉校验失败：link-id={actual!r} != "
                f"amp.runtime.link_id={runtime['link_id']:#x}"
            )
        mailbox_matches = re.findall(r"mboxes\s*=\s*<([^>]+)>", text, re.S)
        mailboxes = re.findall(r"&([A-Za-z0-9_]+)", mailbox_matches[-1] if mailbox_matches else "")
        if mailboxes != list(runtime["mailboxes"]):
            raise ValueError(
                f"dts 交叉校验失败：mailboxes={mailboxes} != "
                f"amp.runtime.mailboxes={runtime['mailboxes']}"
            )
        if not re.search(rf"\b{runtime['mailbox_irq']}\b", text):
            raise ValueError(f"dts 交叉校验失败：缺 mailbox IRQ {runtime['mailbox_irq']}")
        self._status("dts 交叉校验通过（内存/CPU/link-id/mailbox 一致）")

    @classmethod
    def _read_dts_closure(cls, target: Path, dts_root: Path) -> str:
        """递归读取 quoted DTS include；dt-bindings angle include 不参与。"""
        seen: set[Path] = set()

        def visit(path: Path) -> str:
            path = path.resolve()
            if path in seen:
                return ""
            if not path.is_file():
                raise FileNotFoundError(f"DTS include 不存在: {path}")
            seen.add(path)
            content = path.read_text()
            pattern = re.compile(r'#include\s+"([^"]+)"')

            def expand(match: re.Match) -> str:
                include = match.group(1)
                candidate = path.parent / include
                if not candidate.is_file():
                    candidate = dts_root / include
                return visit(candidate)

            expanded = pattern.sub(expand, content)
            return f"\n/* flange-source: {path.name} */\n{expanded}"

        return visit(target)

    @staticmethod
    def _dts_regions(text: str) -> dict[int, int]:
        """收集 2-cell/4-cell address-size reg，按 base 保留最大 region。"""
        regions: dict[int, int] = {}
        for match in re.finditer(r"\breg\s*=\s*<([^>]+)>", text, re.S):
            values = [
                int(token, 0) for token in re.findall(r"0x[0-9a-fA-F]+|\b\d+\b", match.group(1))
            ]
            if len(values) == 2:
                base, size = values
            elif len(values) == 4:
                base = (values[0] << 32) | values[1]
                size = (values[2] << 32) | values[3]
            else:
                continue
            regions[base] = max(regions.get(base, 0), size)
        return regions

    @staticmethod
    def _require_region(
        regions: dict[int, int],
        name: str,
        base: int,
        size: int,
    ) -> None:
        actual = regions.get(base)
        if actual != size:
            raise ValueError(
                f"dts 交叉校验失败：{name} {base:#x}/{actual!r} != config {base:#x}/{size:#x}"
            )

    @staticmethod
    def _require_contiguous_region(
        regions: dict[int, int],
        name: str,
        base: int,
        size: int,
    ) -> None:
        cursor = base
        end = base + size
        while cursor < end:
            region_size = regions.get(cursor)
            if not region_size:
                raise ValueError(f"dts 交叉校验失败：{name} 在 {cursor:#x} 存在空洞")
            cursor += region_size
        if cursor != end:
            raise ValueError(f"dts 交叉校验失败：{name} 末端 {cursor:#x} != {end:#x}")

    def _amp_app_dir(self, config: dict) -> Path:
        """解析 config.amp.app → amp app 工程目录。

        amp app 按 mode 二分：
          - hal：自带 CMake 的独立工程，经 rockchip-hal.cmake 引用 HAL SDK，产
            firmware.bin（要求有 CMakeLists.txt）。
          - rt-thread：叠到 RT-Thread BSP 模板的轻量 overlay（applications/ +
            可选 .config），无 CMakeLists.txt。
        两 mode 均 SDK 只读引用、不就地构建。amp.app 必填，来源统一复用
        SourceManager 的仓内 / external_apps / external_app_dirs 三层解析。
        """
        app_name = self._amp_cfg(config).get("app")
        if not app_name:
            raise ValueError(
                "amp.app 未声明：amp 固件由一个 amp 类型 app 提供。在 board 的 amp "
                '段设 "app:amp": "<name>"；新建用 '
                "`flange create app --type amp --mode <hal|rt-thread> <name>`。"
            )
        if self.source is None:
            # 仅保留给少量直接构造 builder 的单元测试；生产 Engine 始终注入
            # SourceManager。不要在这里重新实现 external app 查找规则。
            app_dir = self.components_root / "app" / app_name
        else:
            from builder.app_resolver import AppResolver

            app_dir = AppResolver(self.context, self.source, config).resolve(app_name)

        try:
            spec = load_spec(app_dir)
        except AppSpecError as exc:
            raise ValueError(f"amp app 描述文件无效（{app_dir}/app.yaml）：{exc}") from exc
        if spec.app.name != app_name:
            raise ValueError(
                f"amp.app 名称不一致：配置为 {app_name!r}，"
                f"{app_dir}/app.yaml 声明为 {spec.app.name!r}"
            )
        if spec.app.type != "amp":
            raise ValueError(
                f"amp.app '{app_name}' 的 app.type 必须是 amp，实际为 {spec.app.type!r}"
            )

        mode = self._mode(config)
        if mode == "hal":
            if spec.build.system != "cmake":
                raise ValueError(
                    f"hal amp app '{app_name}' 的 build.system 必须是 cmake，"
                    f"实际为 {spec.build.system!r}"
                )
            if not (app_dir / "CMakeLists.txt").is_file():
                raise FileNotFoundError(
                    f"amp.app '{app_name}' 缺 CMakeLists.txt（{app_dir}）；hal amp "
                    "app 须是引用 rockchip-hal.cmake 的 CMake 工程。"
                )
        else:  # rt-thread
            if spec.build.system != "scons":
                raise ValueError(
                    f"rt-thread amp app '{app_name}' 的 build.system 必须是 scons，"
                    f"实际为 {spec.build.system!r}"
                )
            if not (app_dir / "applications").is_dir():
                raise FileNotFoundError(
                    f"amp.app '{app_name}' 缺 applications/ 目录（{app_dir}）；"
                    "rt-thread amp app 须是叠到 BSP 模板的 overlay。"
                )
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

        hal_cmake = str(self.components_root / "amp/rockchip/hal/rockchip-hal.cmake")
        build_dir = self.work_dir()
        self._status(
            f"AMP(cmake) 配置 {app_dir.name}（{soc.upper()}, cpu{cpu}, "
            f"base={hex(mem['cpu_base'])}）..."
        )
        self.docker.run(
            [
                "cmake",
                "-S",
                str(app_dir),
                "-B",
                str(build_dir),
                f"-DCMAKE_TOOLCHAIN_FILE={hal_cmake}",
                f"-DROCKCHIP_AMP_SOC={soc.upper()}",
                f"-DROCKCHIP_AMP_CPU={cpu}",
                f"-DROCKCHIP_AMP_FIRMWARE_BASE={hex(mem['cpu_base'])}",
                f"-DROCKCHIP_AMP_DRAM_SIZE={hex(mem['dram_size'])}",
                f"-DROCKCHIP_AMP_SHMEM_BASE={hex(mem['shmem_base'])}",
                f"-DROCKCHIP_AMP_SHMEM_SIZE={hex(mem['shmem_size'])}",
                f"-DROCKCHIP_AMP_LINUX_RPMSG_BASE={hex(mem['rpmsg_base'])}",
                f"-DROCKCHIP_AMP_LINUX_RPMSG_SIZE={hex(mem['rpmsg_size'])}",
            ],
            label="amp:cmake",
        )
        self.docker.run(
            ["cmake", "--build", str(build_dir), f"-j{self._jobs()}"],
            label=f"amp:build:{app_dir.name}",
        )

        firmware_bin = build_dir / "firmware.bin"
        if not firmware_bin.is_file():
            raise FileNotFoundError(
                f"amp app 未产出 firmware.bin（{firmware_bin}）；确认 CMakeLists "
                "的 executable target 名为 'firmware'（见 rockchip-hal.cmake 用法）。"
            )
        return self._mkimage_fit(soc, firmware_bin, cpu, mem, runtime=self._runtime(config))

    def _mkimage_fit(
        self,
        soc: str,
        firmware_bin: Path,
        cpu: int,
        mem: dict,
        its_path=None,
        incbin_name=None,
        runtime=None,
    ) -> Path:
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
            its_path = (
                (self.components_root / "amp/rockchip/hal/project" / soc)
                / "Image"
                / "amp_linux.its"
            )
        if incbin_name is None:
            incbin_name = f"hal{cpu}.bin"
        if runtime is None:
            raise ValueError("AMP FIT 打包缺少 runtime profile")
        firmware_size = firmware_bin.stat().st_size
        if firmware_size > mem["dram_size"]:
            raise BuildError(
                f"AMP firmware {firmware_size} bytes 超过 dram_size {mem['dram_size']} bytes"
            )
        its_txt = Path(its_path).read_text()
        its_txt = self._render_fit_its(its_txt, cpu, mem, runtime, incbin_name)
        work = self.work_dir()
        (work / "amp_linux.its").write_text(its_txt)
        shutil.copy2(firmware_bin, work / incbin_name)
        mkimage = os.path.abspath(str(self.components_root / "amp/rockchip/hal/tools/mkimage"))
        self._status(f"AMP 打包 amp.img（FIT, load={hex(mem['cpu_base'])}）...")
        self.docker.run(
            [mkimage, "-f", "amp_linux.its", "-E", "-p", "0xe00", "amp.img"],
            cwd=str(work),
            extra_mounts=[work],
            label="amp:mkimage",
        )
        return work / "amp.img"

    @staticmethod
    def _fit_node_span(text: str, name: str) -> tuple[int, int]:
        """返回 ITS 中唯一具名 node 的 [start,end)；用 brace matching 定界。"""
        matches = list(re.finditer(rf"(?m)^\s*{re.escape(name)}\s*\{{", text))
        if len(matches) != 1:
            raise ValueError(f"AMP ITS 期望唯一节点 {name!r}，实际 {len(matches)} 个")
        start = matches[0].start()
        brace = text.find("{", matches[0].start(), matches[0].end())
        depth = 0
        for index in range(brace, len(text)):
            if text[index] == "{":
                depth += 1
            elif text[index] == "}":
                depth -= 1
                if depth == 0:
                    semicolon = text.find(";", index)
                    if semicolon < 0:
                        raise ValueError(f"AMP ITS 节点 {name!r} 缺结束分号")
                    return start, semicolon + 1
        raise ValueError(f"AMP ITS 节点 {name!r} 大括号未闭合")

    @staticmethod
    def _replace_fit_property(
        node: str,
        prop: str,
        value: str,
        *,
        insert_after: str | None = None,
    ) -> str:
        """只在给定 node 文本内替换属性；可在缺失时按锚点插入。"""
        pattern = re.compile(rf"(?m)^(?P<indent>\s*){re.escape(prop)}\s*=\s*[^;]+;")
        match = pattern.search(node)
        if match:
            return pattern.sub(
                lambda found: f"{found.group('indent')}{prop} = {value};",
                node,
                count=1,
            )
        if not insert_after:
            raise ValueError(f"AMP ITS 目标节点缺少属性 {prop}")
        anchor = re.compile(rf"(?m)^(?P<indent>\s*){re.escape(insert_after)}\s*=\s*[^;]+;")
        anchor_match = anchor.search(node)
        if not anchor_match:
            raise ValueError(f"AMP ITS 无法插入 {prop}：缺少锚点 {insert_after}")
        insertion = anchor_match.group(0) + f"\n{anchor_match.group('indent')}{prop} = {value};"
        return node[: anchor_match.start()] + insertion + node[anchor_match.end() :]

    @classmethod
    def _render_fit_its(
        cls,
        text: str,
        cpu: int,
        mem: dict,
        runtime: dict,
        incbin_name: str,
    ) -> str:
        """只渲染 ``images/amp<cpu>``，保留 Linux configuration 属性。"""
        node_name = f"amp{cpu}"
        start, end = cls._fit_node_span(text, node_name)
        node = text[start:end]
        node = cls._replace_fit_property(node, "data", f'/incbin/("{incbin_name}")')
        node = cls._replace_fit_property(node, "load", f"<{mem['cpu_base']:#x}>")
        node = cls._replace_fit_property(
            node, "size", f"<{mem['dram_size']:#x}>", insert_after="load"
        )
        if "srambase" in node or runtime.get("fit_requires_sram"):
            node = cls._replace_fit_property(
                node, "srambase", f"<{mem['sram_base']:#x}>", insert_after="size"
            )
            node = cls._replace_fit_property(
                node, "sramsize", f"<{mem['sram_size']:#x}>", insert_after="srambase"
            )
        rendered = text[:start] + node + text[end:]
        cls._assert_fit_its(rendered, node_name, mem, runtime, incbin_name)
        return rendered

    @classmethod
    def _assert_fit_its(
        cls,
        text: str,
        node_name: str,
        mem: dict,
        runtime: dict,
        incbin_name: str,
    ) -> None:
        """校验 AMP/Linux FIT 节点、MPIDR、SRAM 与 loadables。"""
        start, end = cls._fit_node_span(text, node_name)
        amp_node = text[start:end]

        def int_property(node: str, prop: str) -> int | None:
            match = re.search(
                rf"\b{re.escape(prop)}\s*=\s*<\s*"
                rf"(0x[0-9a-fA-F]+|\d+)\s*>",
                node,
            )
            return int(match.group(1), 0) if match else None

        checks = {
            "cpu": (int_property(amp_node, "cpu"), runtime["amp_mpidr"]),
            "load": (int_property(amp_node, "load"), mem["cpu_base"]),
            "size": (int_property(amp_node, "size"), mem["dram_size"]),
        }
        if runtime.get("fit_requires_sram"):
            checks["srambase"] = (int_property(amp_node, "srambase"), mem["sram_base"])
            checks["sramsize"] = (int_property(amp_node, "sramsize"), mem["sram_size"])
        for field, (actual, expected) in checks.items():
            if actual != expected:
                raise ValueError(f"AMP ITS {node_name}.{field}={actual!r} != {expected:#x}")
        arch = re.search(r'\barch\s*=\s*"([^"]+)"', amp_node)
        if not arch or arch.group(1) != "arm":
            raise ValueError(f"AMP ITS {node_name}.arch 必须为 arm")
        if f'/incbin/("{incbin_name}")' not in amp_node:
            raise ValueError(f"AMP ITS {node_name} incbin 未指向 {incbin_name}")

        linux_start, linux_end = cls._fit_node_span(text, "linux")
        linux = text[linux_start:linux_end]
        linux_arch = re.search(r'\barch\s*=\s*"([^"]+)"', linux)
        if not linux_arch or linux_arch.group(1) != runtime["linux_arch"]:
            raise ValueError(f"AMP ITS linux.arch 与 runtime {runtime['linux_arch']} 不一致")
        linux_cpu = int_property(linux, "cpu")
        if linux_cpu != runtime["linux_mpidr"]:
            raise ValueError(f"AMP ITS linux.cpu={linux_cpu!r} != {runtime['linux_mpidr']:#x}")
        if runtime.get("linux_load") is not None:
            linux_load = int_property(linux, "load")
            if linux_load != runtime["linux_load"]:
                raise ValueError(f"AMP ITS linux.load={linux_load!r} != {runtime['linux_load']:#x}")
        loadables = re.search(r'\bloadables\s*=\s*"([^"]+)"', text)
        if not loadables or loadables.group(1) != node_name:
            raise ValueError(f"AMP ITS loadables 必须仅引用 {node_name}")

    def _rtt_bsp_dir(self, soc: str) -> Path:
        """定位 RT-Thread BSP 模板目录：<soc>-32（32 位 Cortex-A profile）。"""
        bsp = (self.components_root / "amp/rockchip/rt-thread") / "bsp" / "rockchip" / f"{soc}-32"
        if not (bsp / "SConstruct").is_file():
            raise FileNotFoundError(f"RT-Thread BSP 模板不存在或不完整: {bsp}（缺 SConstruct）")
        return bsp

    def _rtthread_swift_arch_flags(
        self,
        soc: str,
    ) -> tuple[str, list[str]]:
        """从 BSP 的 DEVICE 声明派生 Swift/C 架构参数。

        RT-Thread 对象与 Embedded Swift archive 最终链接进同一个裸机 ELF，
        因此 BSP ``rtconfig.py`` 是 CPU/ABI 的单一事实源。按板名猜测或保留全局
        Cortex-A55 默认值，会让 RK3506 Cortex-A7 在运行时遇到非法指令。
        """
        rtconfig = self._rtt_bsp_dir(soc) / "rtconfig.py"
        device_value = None
        for line in rtconfig.read_text().splitlines():
            match = re.match(
                r"^\s*DEVICE\s*=\s*(?P<value>['\"].*['\"])\s*$",
                line,
            )
            if match:
                try:
                    device_value = ast.literal_eval(match.group("value"))
                except (SyntaxError, ValueError) as exc:
                    raise ValueError(f"RT-Thread BSP DEVICE 声明非法: {rtconfig}") from exc
                break
        if not isinstance(device_value, str):
            raise ValueError(f"RT-Thread BSP 缺少静态 DEVICE 声明: {rtconfig}")

        accepted_prefixes = ("-mcpu=", "-march=", "-mfpu=", "-mfloat-abi=")
        accepted_exact = {"-marm", "-mthumb", "-mno-unaligned-access"}
        c_flags = [
            flag
            for flag in shlex.split(device_value)
            if flag.startswith(accepted_prefixes) or flag in accepted_exact
        ]
        cpu_flags = [flag for flag in c_flags if flag.startswith("-mcpu=")]
        if len(cpu_flags) != 1:
            raise ValueError(f"RT-Thread BSP DEVICE 必须且只能声明一个 -mcpu: {rtconfig}")
        swift_cpu = cpu_flags[0].split("=", 1)[1].split("+", 1)[0]
        return swift_cpu, c_flags

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

    def _assert_hard_float_abi(
        self,
        artifact: Path,
        *,
        extra_mounts: list[Path] | None = None,
    ) -> None:
        """确认 ARM 产物使用 AAPCS-VFP hard-float 调用约定。"""
        if not artifact.is_file():
            raise FileNotFoundError(f"hard-float ABI 门禁找不到待检查产物: {artifact}")
        result = self.docker.run(
            [_RTT_READELF, "-A", str(artifact)],
            env={"LC_ALL": "C"},
            capture=True,
            extra_mounts=extra_mounts,
        )
        attributes = "\n".join(
            output
            for output in (
                getattr(result, "stdout", "") or "",
                getattr(result, "stderr", "") or "",
            )
            if output
        )
        if "Tag_ABI_VFP_args: VFP registers" not in attributes:
            raise BuildError(
                "hard-float ABI 门禁失败："
                f"{artifact} 未声明 Tag_ABI_VFP_args: VFP registers；"
                "不能与 RT-Thread 的 -mfloat-abi=hard 对象安全链接。"
            )
        if "Tag_ABI_enum_size: small" not in attributes or "Tag_ABI_enum_size: int" in attributes:
            raise BuildError(
                "ARM enum ABI 门禁失败："
                f"{artifact} 未统一为 Tag_ABI_enum_size: small；"
                "Embedded Swift 必须匹配 BSP/newlib 的 variable-size enum ABI。"
            )

    def _assert_rtthread_heap_capacity(
        self,
        artifact: Path,
        runtime: dict,
        memory: dict,
        *,
        extra_mounts: list[Path] | None = None,
    ) -> int:
        """用固定裸机工具链交叉确认最终 ELF 的可用 heap 及保留区边界。"""
        if not artifact.is_file():
            raise FileNotFoundError(f"RT-Thread heap 门禁找不到最终 ELF: {artifact}")

        minimum = runtime.get("minimum_heap_size")
        if isinstance(minimum, bool) or not isinstance(minimum, int) or minimum <= 0:
            raise ValueError("amp.runtime.minimum_heap_size 必须是正整数 byte 数")

        nm_result = self.docker.run(
            [_RTT_NM, "-n", "--defined-only", str(artifact)],
            env={"LC_ALL": "C"},
            capture=True,
            extra_mounts=extra_mounts,
        )
        nm_output = "\n".join(
            output
            for output in (
                getattr(nm_result, "stdout", "") or "",
                getattr(nm_result, "stderr", "") or "",
            )
            if output
        )
        symbols = {
            match.group("name"): int(match.group("address"), 16)
            for match in re.finditer(
                r"(?m)^\s*(?P<address>[0-9a-fA-F]+)\s+\S\s+"
                r"(?P<name>__heap_begin|__heap_end)\s*$",
                nm_output,
            )
        }
        missing = [name for name in ("__heap_begin", "__heap_end") if name not in symbols]
        if missing:
            raise BuildError(
                "RT-Thread heap 门禁失败：最终 ELF 缺少链接器符号 " + ", ".join(missing)
            )

        readelf_result = self.docker.run(
            [_RTT_READELF, "-SW", str(artifact)],
            env={"LC_ALL": "C"},
            capture=True,
            extra_mounts=extra_mounts,
        )
        section_output = "\n".join(
            output
            for output in (
                getattr(readelf_result, "stdout", "") or "",
                getattr(readelf_result, "stderr", "") or "",
            )
            if output
        )
        heap_section = re.search(
            r"(?m)^\s*\[\s*\d+\]\s+\.heap\s+\S+\s+"
            r"(?P<address>[0-9a-fA-F]+)\s+[0-9a-fA-F]+\s+"
            r"(?P<size>[0-9a-fA-F]+)\b",
            section_output,
        )
        if heap_section is None:
            raise BuildError("RT-Thread heap 门禁失败：最终 ELF 缺少 .heap section")

        begin = symbols["__heap_begin"]
        end = symbols["__heap_end"]
        section_address = int(heap_section.group("address"), 16)
        section_size = int(heap_section.group("size"), 16)
        if end <= begin:
            raise BuildError(
                f"RT-Thread heap 门禁失败：__heap_begin={begin:#x}, __heap_end={end:#x}"
            )
        available = end - begin
        if section_address != begin or section_size != available:
            raise BuildError(
                "RT-Thread heap 门禁失败：.heap section 与链接器符号不一致："
                f"section={section_address:#x}/{section_size:#x}, "
                f"symbols={begin:#x}/{available:#x}"
            )

        firmware_begin = memory["cpu_base"]
        firmware_end = firmware_begin + memory["dram_size"]
        if begin < firmware_begin or end > firmware_end:
            raise BuildError(
                "RT-Thread heap 门禁失败：heap 越出 CPU firmware carveout："
                f"heap={begin:#x}..{end:#x}, "
                f"carveout={firmware_begin:#x}..{firmware_end:#x}"
            )
        if available < minimum:
            raise BuildError(
                "RT-Thread heap 门禁失败："
                f"可用 {available} bytes，小于 "
                f"amp.runtime.minimum_heap_size={minimum} bytes"
            )

        self._status(
            "RT-Thread heap 门禁通过："
            f"可用 {available // 1024} KiB，最低 {minimum // 1024} KiB，"
            f"余量 {(available - minimum) // 1024} KiB"
        )
        return available

    def _build_swift_package(
        self,
        app_dir: Path,
        bsp_tmp: Path,
        swift_cfg: SwiftBuildConfig,
        swift_target_cpu: str,
        c_arch_flags: list[str],
    ) -> Path:
        """用 SwiftPM 构建 Embedded Swift static archive 并复制进 staged BSP。"""
        package_dir = app_dir / swift_cfg.package_path
        if not package_dir.is_dir():
            raise FileNotFoundError(f"build.swift.package_path 不存在或不是目录: {package_dir}")
        if not (package_dir / "Package.swift").is_file():
            raise FileNotFoundError(f"SwiftPM package 缺 Package.swift: {package_dir}")

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
            f"AMP(scons) 构建 Embedded Swift package {package_dir.name}:{swift_cfg.product}..."
        )
        try:
            self.docker.run(["swift", "--version"], capture=True)
        except Exception as exc:
            raise BuildError(
                "build.swift.enabled=true 但 Docker build 容器内不可调用 swift；"
                "请先在 docker/Dockerfile 固定安装 Embedded Swift 工具链。"
            ) from exc

        cmd = [
            "swift",
            "build",
            "-c",
            "release",
            "--package-path",
            str(package_dir),
            "--scratch-path",
            str(scratch_dir),
            "--product",
            swift_cfg.product,
            "--triple",
            swift_cfg.target_triple,
            "-Xswiftc",
            "-target",
            "-Xswiftc",
            swift_cfg.target_triple,
            "-Xswiftc",
            "-enable-experimental-feature",
            "-Xswiftc",
            "Embedded",
            "-Xswiftc",
            "-wmo",
            "-Xswiftc",
            "-parse-as-library",
            "-Xswiftc",
            "-Osize",
            "-Xswiftc",
            "-no-allocations",
            "-Xswiftc",
            "-Xfrontend",
            "-Xswiftc",
            "-disable-stack-protector",
            "-Xswiftc",
            "-Xfrontend",
            "-Xswiftc",
            "-function-sections",
            "-Xswiftc",
            "-Xfrontend",
            "-Xswiftc",
            "-enable-single-module-llvm-emission",
            "-Xswiftc",
            "-pch-output-dir",
            "-Xswiftc",
            str(pch_dir),
            "-Xswiftc",
            "-target-cpu",
            "-Xswiftc",
            swift_target_cpu,
            "-Xcc",
            "-fno-pic",
            "-Xcc",
            "-fno-pie",
            # GNU Arm Embedded 的 BSP/newlib/libgcc 使用 variable-size enum
            # ABI；Swift/Clang 对象必须显式匹配，否则最终 ld 会报告 enum-size
            # 混用。只作用于 Swift package，不改变无 Swift 的救援 BSP。
            "-Xcc",
            "-fshort-enums",
            "-Xcc",
            f"-I{app_dir / 'include'}",
            "-Xcc",
            f"-I{bsp_tmp}",
        ]
        for flag in c_arch_flags:
            cmd.extend(["-Xcc", flag])
        cmd.extend(swift_cfg.extra_flags)
        self.docker.run(
            cmd,
            env={"FLUXION_EMBEDDED_PACKAGE_ONLY": "1"},
            extra_mounts=[bsp_tmp.parent],
            label=f"amp:rtt:swift:{swift_cfg.product}",
        )

        candidates = sorted(scratch_dir.rglob(archive_name))
        if not candidates:
            raise FileNotFoundError(f"SwiftPM 未产出 {archive_name}（scratch={scratch_dir}）")
        shutil.copy2(candidates[-1], staged_archive)
        if "-mfloat-abi=hard" in c_arch_flags:
            self._assert_hard_float_abi(
                staged_archive,
                extra_mounts=[bsp_tmp.parent],
            )
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
            raise FileNotFoundError(f"build.swift.c_header 不存在: {header_src}")

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
            include_exprs.append(f"os.path.abspath(os.path.join(cwd, {rel_dir!r}))")
        include_exprs.append(f"os.path.abspath(os.path.join(cwd, {_SWIFT_ARCHIVE_SUBDIR!r}))")
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
        swift_target_cpu: str,
        c_arch_flags: list[str],
    ) -> Path:
        """准备 RT-Thread staged BSP 的 SwiftPM archive、头文件与 SConscript。"""
        app_sconscript = app_dir / "applications" / "SConscript"
        if app_sconscript.exists():
            raise ValueError(
                "启用 build.swift 时暂不支持 app 自带 applications/SConscript；"
                f"请删除或改由 builder 生成（{app_sconscript}）。"
            )

        applications_dir = bsp_tmp / "applications"
        archive = self._build_swift_package(
            app_dir,
            bsp_tmp,
            swift_cfg,
            swift_target_cpu,
            c_arch_flags,
        )
        include_dirs = self._stage_swift_bridge_header(app_dir, applications_dir, swift_cfg)
        self._write_swift_sconscript(applications_dir, swift_cfg, include_dirs)
        return archive

    @staticmethod
    def _write_runtime_header(applications_dir: Path, runtime: dict) -> Path:
        """把 SoC runtime profile 渲染为 app 可消费的只读 C header。"""
        applications_dir.mkdir(parents=True, exist_ok=True)
        header = applications_dir / "flange_amp_runtime.h"
        header.write_text(
            "/* 由 flange AMP builder 从 FINAL_CONFIG 生成，请勿手改。 */\n"
            "#pragma once\n"
            f"#define FLANGE_AMP_LINK_ID {runtime['link_id']:#x}U\n"
            f"#define FLANGE_AMP_EPT_ADDR {runtime['endpoint_address']:#x}U\n"
            f'#define FLANGE_AMP_EPT_NAME "{runtime["endpoint_name"]}"\n'
        )
        return header

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
            "build",
            ".sconsign.dblite",
            "*.o",
            "*.pyc",
            "__pycache__",
            "rtthread.*",
            "gcc_arm.ld",
            "amp*.img",
        )
        # common/hal 由下方统一链接到 flange 的 HAL SDK；源 SDK 中的同名链接
        # 可能指向带断链 .git 的 vendor repo，不能在 staging 时跟随复制。
        _ignore_common = shutil.ignore_patterns(
            "build",
            ".sconsign.dblite",
            "*.o",
            "*.pyc",
            "__pycache__",
            "rtthread.*",
            "gcc_arm.ld",
            "amp*.img",
            "hal",
        )
        sdk_root = self.components_root / "amp/rockchip/rt-thread"
        staged_root = self.work_dir()

        def _mirror(src_dir: Path, dst_dir: Path, skip: set) -> None:
            """dst_dir 下逐项 symlink 到 src_dir（skip 的项留给调用方 copy）。"""
            dst_dir.mkdir(parents=True, exist_ok=True)
            for entry in os.listdir(src_dir):
                if entry not in skip:
                    os.symlink(os.path.abspath(src_dir / entry), dst_dir / entry)

        # 顶层：除 bsp 外全 symlink（examples/documentation/… 也被部分 SConscript 引用）
        _mirror(sdk_root, staged_root, skip={"bsp"})
        # bsp：除 rockchip 外全 symlink（其它 arch，本构建不用，symlink 无害）
        _mirror(sdk_root / "bsp", staged_root / "bsp", skip={"rockchip"})
        # bsp/rockchip：仅 common + 本板 BSP 须可写（copy），其余（tools/其它板）symlink。
        # tools symlink 即可：SConstruct 以 ../tools 加 sys.path 只读导入 buildutil
        # （PYTHONDONTWRITEBYTECODE=1 兜 __pycache__）。
        bsp_rk = staged_root / "bsp" / "rockchip"
        _mirror(sdk_root / "bsp" / "rockchip", bsp_rk, skip={"common", f"{soc}-32"})
        bsp_tmp = bsp_rk / f"{soc}-32"
        shutil.copytree(bsp_src, bsp_tmp, ignore=_ignore, ignore_dangling_symlinks=True)
        shutil.copytree(
            bsp_src.parent / "common",
            bsp_rk / "common",
            ignore=_ignore_common,
            ignore_dangling_symlinks=True,
        )
        os.symlink(self.components_root / "amp/rockchip/hal", bsp_rk / "common" / "hal")

        # --- 配置叠加：BSP 默认 → flange AMP 基线 → app 差异配置 ---
        base_config = self.components_root / "platform/rockchip/amp/rt-thread.config"
        if not base_config.is_file():
            raise FileNotFoundError(f"RT-Thread AMP 基线配置不存在: {base_config}")
        self._merge_kconfig_fragment(bsp_tmp / ".config", base_config)

        # app overlay：applications/ + 可选 .config 差异配置。
        app_apps = app_dir / "applications"
        if app_apps.is_dir():
            shutil.copytree(app_apps, bsp_tmp / "applications", dirs_exist_ok=True)
        runtime = self._runtime(config)
        self._write_runtime_header(bsp_tmp / "applications", runtime)
        app_config = app_dir / ".config"
        if app_config.is_file():
            self._merge_kconfig_fragment(bsp_tmp / ".config", app_config)

        swift_cfg = app_spec.build.swift
        swift_uses_hard_float = False
        if self._swift_cfg_enabled(swift_cfg):
            swift_target_cpu, c_arch_flags = self._rtthread_swift_arch_flags(soc)
            swift_uses_hard_float = "-mfloat-abi=hard" in c_arch_flags
            self._prepare_rtthread_swift(
                app_dir,
                bsp_tmp,
                swift_cfg,
                swift_target_cpu,
                c_arch_flags,
            )

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
            f"base={hex(mem['cpu_base'])}）..."
        )
        # 合并基线/app 配置后必须从 .config 重生成 rtconfig.h（编译实际读
        # rtconfig.h，.config 仅是 Kconfig 状态）。
        self.docker.run(
            ["scons", "--useconfig=.config"],
            cwd=str(bsp_tmp),
            env=env,
            extra_mounts=[staged_root],
            label="amp:rtt:config",
        )
        self.docker.run(
            ["scons", f"-j{self._jobs()}"],
            cwd=str(bsp_tmp),
            env=env,
            extra_mounts=[staged_root],
            label=f"amp:rtt:build:{app_dir.name}",
        )

        final_elf = bsp_tmp / "rtthread.elf"
        self._assert_rtthread_heap_capacity(
            final_elf,
            runtime,
            mem,
            extra_mounts=[staged_root],
        )

        if swift_uses_hard_float:
            self._assert_hard_float_abi(
                final_elf,
                extra_mounts=[staged_root],
            )

        rtt_bin = bsp_tmp / "rtthread.bin"
        if not rtt_bin.is_file():
            raise FileNotFoundError(
                f"RT-Thread 未产出 rtthread.bin（{rtt_bin}）；检查 scons 日志。"
            )
        its_path = bsp_tmp / "Image" / "amp_linux.its"
        return self._mkimage_fit(
            soc,
            rtt_bin,
            cpu,
            mem,
            its_path=its_path,
            incbin_name=f"rtt{cpu}.bin",
            runtime=self._runtime(config),
        )

    # --- collect ---

    def collect(self, src_dir, config: dict) -> dict:
        amp_img = self._amp_img
        if not Path(amp_img).is_file():
            raise FileNotFoundError(f"amp.img 未生成: {amp_img}")
        return {"amp": amp_img}
