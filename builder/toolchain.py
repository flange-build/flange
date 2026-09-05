"""目标用户态工具链与各原生构建系统的独立目录适配。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from builder.app_spec import AppSpec


@dataclass(frozen=True)
class Toolchain:
    arch: str
    triple: str
    processor: str
    cpu_family: str

    @classmethod
    def for_arch(cls, arch: str) -> Toolchain:
        targets = {
            "aarch64": ("aarch64-linux-gnu", "aarch64", "aarch64"),
            "armhf": ("arm-linux-gnueabihf", "armv7", "arm"),
            "x86_64": ("x86_64-linux-gnu", "x86_64", "x86_64"),
            "i386": ("i686-linux-gnu", "i686", "x86"),
            "riscv64": ("riscv64-linux-gnu", "riscv64", "riscv64"),
        }
        if arch not in targets:
            raise ValueError(f"未声明用户态工具链：{arch}")
        return cls(arch, *targets[arch])

    @property
    def tools(self) -> dict[str, str]:
        return {
            name: f"{self.triple}-{program}"
            for name, program in {
                "CC": "gcc",
                "CXX": "g++",
                "AR": "ar",
                "RANLIB": "ranlib",
                "STRIP": "strip",
                "OBJCOPY": "objcopy",
            }.items()
        }

    def environment(self, dependency_root: Path) -> dict[str, str]:
        return {
            **self.tools,
            "PKG_CONFIG_SYSROOT_DIR": "",
            "PKG_CONFIG_LIBDIR": ":".join(
                [
                    str(dependency_root / "usr/lib/pkgconfig"),
                    str(dependency_root / "usr/lib" / self.triple / "pkgconfig"),
                    str(dependency_root / "usr/share/pkgconfig"),
                    f"/usr/lib/{self.triple}/pkgconfig",
                    "/usr/share/pkgconfig",
                ]
            ),
        }

    def meson_file(self, path: Path, dependency_root: Path) -> None:
        """把实际架构与依赖前缀写入本节点的 cross-file。"""
        flags = [f"-I{dependency_root}/usr/include"]
        links = [f"-L{dependency_root}/usr/lib", f"-Wl,-rpath-link,{dependency_root}/usr/lib"]
        text = (
            "# flange 生成的目标工具链；修改目标后重新生成。\n"
            "[binaries]\n"
            f"c = {self.tools['CC']!r}\ncpp = {self.tools['CXX']!r}\n"
            f"ar = {self.tools['AR']!r}\nstrip = {self.tools['STRIP']!r}\n"
            "pkg-config = 'pkg-config'\n"
            "[host_machine]\nsystem = 'linux'\n"
            f"cpu_family = {self.cpu_family!r}\ncpu = {self.processor!r}\nendian = 'little'\n"
            "[built-in options]\n"
            f"c_args = {flags!r}\ncpp_args = {flags!r}\n"
            f"c_link_args = {links!r}\ncpp_link_args = {links!r}\n"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def commands(
        self,
        spec: AppSpec,
        *,
        source: Path,
        build: Path,
        install: Path,
        dependency_root: Path,
        variant: str,
    ) -> tuple[list[list[str]], list[str] | None]:
        """返回编译步骤与安装步骤；Make/custom 的 source 已由调用者隔离。"""
        system = spec.build.system
        options = spec.build.options
        debug = variant == "debug"
        jobs = str(os.cpu_count() or 1)
        if system == "none":
            return [], None
        if system == "custom":
            return [list(command) for command in spec.build.commands], None
        if system == "cmake":
            configure = [
                "cmake",
                "-S",
                str(source),
                "-B",
                str(build),
                "-DCMAKE_SYSTEM_NAME=Linux",
                f"-DCMAKE_SYSTEM_PROCESSOR={self.processor}",
                f"-DCMAKE_C_COMPILER={self.tools['CC']}",
                f"-DCMAKE_CXX_COMPILER={self.tools['CXX']}",
                "-DCMAKE_EXPORT_COMPILE_COMMANDS=ON",
                "-DCMAKE_INSTALL_PREFIX=/usr",
                f"-DCMAKE_BUILD_TYPE={'Debug' if debug else 'Release'}",
                f"-DCMAKE_PREFIX_PATH={dependency_root}/usr",
            ]
            configure.extend(f"-D{key}={value}" for key, value in options.items())
            return [configure, ["cmake", "--build", str(build), "--parallel", jobs]], [
                "cmake",
                "--install",
                str(build),
            ]
        if system == "meson":
            cross = build.parent / "meson-cross.ini"
            self.meson_file(cross, dependency_root)
            setup = ["meson", "setup", str(build), str(source), "--cross-file", str(cross)]
            if (build / "meson-private/coredata.dat").is_file():
                setup.append("--reconfigure")
            setup.extend([f"--buildtype={'debug' if debug else 'release'}", "--prefix=/usr"])
            setup.extend(f"-D{key}={value}" for key, value in options.items())
            return [setup, ["meson", "compile", "-C", str(build), "-j", jobs]], [
                "meson",
                "install",
                "-C",
                str(build),
            ]
        if system == "make":
            flags = "-Wall -O0 -g" if debug else "-Wall -O2"
            variables = {
                **self.tools,
                "ARCH": self.cpu_family,
                "CROSS_COMPILE": f"{self.triple}-",
                "CFLAGS": flags,
                "CXXFLAGS": flags,
                "CPPFLAGS": f"-I{dependency_root}/usr/include",
                "LDFLAGS": f"-L{dependency_root}/usr/lib -Wl,-rpath-link,{dependency_root}/usr/lib",
                "BUILD_DIR": str(build),
                **options,
            }
            argv = [f"{key}={value}" for key, value in variables.items()]
            return [["make", f"-j{jobs}", *argv]], [
                "make",
                "install",
                *argv,
                f"DESTDIR={install}",
            ]
        if system == "swift":
            configuration = options.get("configuration", "debug" if debug else "release")
            triple = {
                "aarch64": "aarch64-unknown-linux-gnu",
                "armhf": "armv7-unknown-linux-gnueabihf",
            }.get(self.arch, f"{self.arch}-unknown-linux-gnu")
            command = [
                "swift",
                "build",
                "--package-path",
                str(source),
                "--scratch-path",
                str(build),
                "-c",
                configuration,
                "--triple",
                triple,
            ]
            for key, value in options.items():
                if key == "configuration":
                    continue
                command.append(f"--{key}")
                if value:
                    command.append(value)
            executable = build / triple / configuration / spec.app.name
            return [command], [
                "install",
                "-Dm755",
                str(executable),
                str(install / "usr/bin" / spec.app.name),
            ]
        raise ValueError(f"{system!r} 必须通过对应系统组件构建，不能独立构建 App")
