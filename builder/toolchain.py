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
    profile: str = "ubuntu"
    prefix: str = ""
    target_sysroot: str = ""
    sdk_identity: str = ""
    sdk_source: str = "environment"

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
            name: f"{self.prefix or self.triple + '-'}{program}"
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
        if self.target_sysroot:
            directories = [
                dependency_root / "usr/lib" / self.triple / "pkgconfig",
                dependency_root / "usr/lib/pkgconfig",
                dependency_root / "usr/share/pkgconfig",
            ]
            flag = f"--sysroot={dependency_root}"
            return {
                **self.tools,
                "PKG_CONFIG_SYSROOT_DIR": str(dependency_root),
                "PKG_CONFIG_LIBDIR": ":".join(map(str, directories)),
                "PKG_CONFIG_PATH": "",
                "CFLAGS": flag,
                "CXXFLAGS": flag,
                "CPPFLAGS": flag,
                "LDFLAGS": flag,
            }
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
        links = [
            f"-L{dependency_root}/usr/lib",
            f"-Wl,-rpath-link,{dependency_root}/usr/lib",
        ]
        if self.target_sysroot:
            flags = [f"--sysroot={dependency_root}"]
            links = flags + [f"-Wl,-rpath-link,{dependency_root}/usr/lib/{self.triple}"]
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
        if self.target_sysroot:
            text += (
                "[properties]\n"
                + f"sys_root = {str(dependency_root)!r}\n"
                + f"pkg_config_libdir = {self.environment(dependency_root)['PKG_CONFIG_LIBDIR'].split(':')!r}\n"
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
            if self.target_sysroot:
                toolchain_file = build.parent / "flange-toolchain.cmake"
                self.cmake_file(toolchain_file, dependency_root)
                configure.append(f"-DCMAKE_TOOLCHAIN_FILE={toolchain_file}")
                configure.append("-DCMAKE_PREFIX_PATH=/usr")
            configure.extend(f"-D{key}={value}" for key, value in options.items())
            return [configure, ["cmake", "--build", str(build), "--parallel", jobs]], [
                "cmake",
                "--install",
                str(build),
            ]
        if system == "meson":
            cross = build.parent / "meson-cross.ini"
            self.meson_file(cross, dependency_root)
            setup = [
                "meson",
                "setup",
                str(build),
                str(source),
                "--cross-file",
                str(cross),
            ]
            if (build / "meson-private/coredata.dat").is_file():
                setup.append("--reconfigure")
            setup.extend(
                [f"--buildtype={'debug' if debug else 'release'}", "--prefix=/usr"]
            )
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
            if self.target_sysroot:
                sdk_flags = self.environment(dependency_root)
                variables.update(
                    {key: sdk_flags[key] for key in ("CPPFLAGS", "LDFLAGS")}
                )
                variables["CFLAGS"] = flags + " " + sdk_flags["CFLAGS"]
                variables["CXXFLAGS"] = flags + " " + sdk_flags["CXXFLAGS"]
                variables["CROSS_COMPILE"] = self.prefix or f"{self.triple}-"
            argv = [f"{key}={value}" for key, value in variables.items()]
            return [["make", f"-j{jobs}", *argv]], [
                "make",
                "install",
                *argv,
                f"DESTDIR={install}",
            ]
        if system == "swift" and self.target_sysroot:
            raise ValueError("该用户态 SDK 尚未声明 Swift 适配，请提供支持的构建方式")
        if system == "swift":
            configuration = options.get(
                "configuration", "debug" if debug else "release"
            )
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

    def cmake_file(self, path: Path, sysroot: Path) -> None:
        """CMake 必须在 toolchain file 中设置 sysroot 与目标查找范围。"""
        import json

        values = {
            "CMAKE_SYSTEM_NAME": "Linux",
            "CMAKE_SYSTEM_PROCESSOR": self.processor,
            "CMAKE_C_COMPILER": self.tools["CC"],
            "CMAKE_CXX_COMPILER": self.tools["CXX"],
            "CMAKE_SYSROOT": str(sysroot),
            "CMAKE_FIND_ROOT_PATH": str(sysroot),
            "CMAKE_FIND_ROOT_PATH_MODE_PROGRAM": "NEVER",
            "CMAKE_FIND_ROOT_PATH_MODE_LIBRARY": "ONLY",
            "CMAKE_FIND_ROOT_PATH_MODE_INCLUDE": "ONLY",
            "CMAKE_FIND_ROOT_PATH_MODE_PACKAGE": "ONLY",
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "# flange 生成的目标工具链。\n"
            + "".join(
                f"set({key} {json.dumps(value)})\n" for key, value in values.items()
            )
        )


def resolve_toolchain(config, context):
    from builder.build_environment import resolve_environment
    from builder.config.canonical import userspace_arch
    from builder.layers import stack_for

    arch = userspace_arch(config)
    environment = resolve_environment(config, context)
    name = config.get("userland_toolchain") or (
        environment.toolchain if environment else ""
    )
    if not name:
        if config.get("distro", "ubuntu") != "ubuntu":
            raise ValueError("非 Ubuntu 发行版必须声明用户态工具链")
        return Toolchain.for_arch(arch)
    module = stack_for(config, context).provider("toolchain", name)
    if module is None:
        raise ValueError(f"未注册用户态工具链：{name}")
    toolchain = module.create_toolchain(config, context)
    if not isinstance(toolchain, Toolchain) or toolchain.arch != arch:
        raise ValueError("工具链必须返回与目标架构一致的 Toolchain")
    if (
        not toolchain.profile
        or not toolchain.sdk_identity
        or not Path(toolchain.target_sysroot).is_absolute()
    ):
        raise ValueError(
            "外部工具链必须声明 profile、sdk_identity 和绝对 target_sysroot"
        )
    if toolchain.sdk_source not in {"environment", "directory"}:
        raise ValueError("SDK 来源必须是 environment 或 directory")
    return toolchain


def userland_identity(config, context):
    toolchain = resolve_toolchain(config, context)
    result = {
        "distro": config.get("distro", "ubuntu"),
        "profile": toolchain.profile,
        "sdk": toolchain.sdk_identity,
        "architecture": toolchain.arch,
        "triple": toolchain.triple,
    }
    if toolchain.target_sysroot:
        from builder.digest import hash_path
        from builder.environment import environment_identity
        from builder.layers import stack_for
        from builder.build_environment import resolve_environment

        environment = resolve_environment(config, context)
        name = config.get("userland_toolchain") or (
            environment.toolchain if environment else ""
        )
        result["toolchain_inputs"] = {
            ref.identity: hash_path(ref.path)
            for ref in stack_for(config, context).provider_inputs("toolchain", name)
        }
        if toolchain.sdk_source == "directory":
            sdk = Path(toolchain.target_sysroot)
            if not sdk.is_dir():
                raise ValueError(f"SDK 目录不存在：{sdk}")
            result["sdk_digest"] = hash_path(sdk)
        else:
            result["sdk_environment"] = environment_identity(
                config=config, context=context
            )
    return result
