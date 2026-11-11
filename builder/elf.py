"""按目标 SDK 检查用户态 ELF 的加载器、libc 依赖和 ARM 浮点 ABI。"""

from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass
import mmap
from pathlib import Path, PurePosixPath
import re
import struct


ELF_ARCHITECTURES = {
    "aarch64": (2, 183),
    "armhf": (1, 40),
    "x86_64": (2, 62),
    "i386": (1, 3),
    "riscv64": (2, 243),
}
_LIBC_DEPENDENCY = re.compile(
    r"lib(?:c|m|pthread|dl|rt|resolv|util|anl)\.so\.\d+|libc\.musl-[^/]+\.so\.\d+"
)
_EF_ARM_ABI_FLOAT_SOFT = 0x200


def is_userland_path(destination: str, executable: str = "") -> bool:
    """固件和共享数据不视为 Linux 用户态程序，显式运行入口始终检查。"""
    if destination == executable:
        return True
    if destination.startswith(("/lib/firmware/", "/usr/lib/firmware/")):
        return False
    return destination.startswith((
        "/bin/", "/sbin/", "/usr/bin/", "/usr/sbin/", "/lib/", "/lib64/",
        "/usr/lib/", "/usr/lib64/", "/usr/local/", "/opt/",
    ))


@dataclass(frozen=True)
class ElfABI:
    elf_class: int
    machine: int
    encoding: int
    flags: int
    interpreter: str
    needed: tuple[str, ...]


def _cstring(data: mmap.mmap, offset: int, size: int) -> str:
    if offset < 0 or size <= 0 or offset + size > len(data):
        raise ValueError("字符串表超出 ELF 文件边界")
    end = data.find(b"\0", offset, offset + size)
    if end < 0:
        raise ValueError("ELF 字符串缺少终止符")
    return data[offset:end].decode("utf-8", errors="surrogateescape")


def read_elf_abi(source: Path) -> ElfABI | None:
    """只读 ELF 头与程序段，不执行目标程序，也不依赖宿主 readelf。"""
    with source.open("rb") as stream:
        if stream.read(4) != b"\x7fELF":
            return None
        try:
            with mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as data:
                elf_class, encoding = data[4], data[5]
                if elf_class not in (1, 2) or encoding not in (1, 2):
                    raise ValueError("ELF class 或字节序无效")
                endian = "<" if encoding == 1 else ">"
                header_format = "HHIIIIIHHHHHH" if elf_class == 1 else "HHIQQQIHHHHHH"
                header = struct.unpack_from(endian + header_format, data, 16)
                phoff, flags, phsize, phnum = header[4], header[6], header[8], header[9]
                phformat = endian + ("IIIIIIII" if elf_class == 1 else "IIQQQQQQ")
                if phnum and (phsize < struct.calcsize(phformat) or phnum == 0xffff):
                    raise ValueError("ELF 程序头大小或数量不受支持")
                segments: list[tuple[int, int, int, int]] = []
                interpreter = ""
                for index in range(phnum):
                    entry = struct.unpack_from(phformat, data, phoff + index * phsize)
                    kind = entry[0]
                    offset, address, size = (
                        (entry[1], entry[2], entry[4]) if elf_class == 1
                        else (entry[2], entry[3], entry[5])
                    )
                    if offset + size > len(data):
                        raise ValueError("ELF 程序段超出文件边界")
                    segments.append((kind, offset, address, size))
                    if kind == 3:
                        interpreter = _cstring(data, offset, size)
                needed: list[int] = []
                string_address = string_size = 0
                dynamic_format = endian + ("iI" if elf_class == 1 else "qQ")
                entry_size = struct.calcsize(dynamic_format)
                for kind, offset, _, size in segments:
                    if kind != 2:
                        continue
                    for cursor in range(offset, offset + size, entry_size):
                        if cursor + entry_size > offset + size:
                            raise ValueError("ELF 动态表不完整")
                        tag, value = struct.unpack_from(dynamic_format, data, cursor)
                        if tag == 0:
                            break
                        if tag == 1:
                            needed.append(value)
                        elif tag == 5:
                            string_address = value
                        elif tag == 10:
                            string_size = value
                dependencies: tuple[str, ...] = ()
                if needed:
                    table = next((
                        offset + string_address - address
                        for kind, offset, address, size in segments
                        if kind == 1 and address <= string_address
                        and string_address + string_size <= address + size
                    ), None)
                    if table is None or not string_size:
                        raise ValueError("找不到 ELF 动态字符串表")
                    dependencies = tuple(
                        _cstring(data, table + index, string_size - index) for index in needed
                    )
                return ElfABI(elf_class, header[1], encoding, flags, interpreter, dependencies)
        except (ValueError, IndexError, struct.error) as error:
            raise ValueError(f"无效 ELF 文件 {source}：{error}") from error


def _sdk_file(root: Path, target: str) -> Path | None:
    """按目标根解析符号链接，绝对链接不得跳到宿主文件系统。"""
    pending = deque(PurePosixPath(target).parts)
    parts: list[str] = []
    links = 0
    while pending:
        part = pending.popleft()
        if part in ("/", "", "."):
            continue
        if part == "..":
            if not parts:
                return None
            parts.pop()
            continue
        path = root.joinpath(*parts, part)
        if path.is_symlink():
            links += 1
            if links > 40:
                return None
            link = path.readlink()
            if link.is_absolute():
                parts.clear()
            pending.extendleft(reversed(link.parts))
        else:
            parts.append(part)
    path = root.joinpath(*parts)
    return path if path.is_file() else None


def validate_elf_abi(
    files: Sequence[tuple[Path, str, int]], arch: str, sdk: Path, triple: str,
    *, executable: str = "",
) -> None:
    """SDK 提供加载器和 libc；其他运行库仍由包依赖声明和安装器解析。"""
    if not sdk.is_dir():
        raise ValueError(f"目标 SDK 不存在：{sdk}")
    directories = (
        "/lib", "/usr/lib", f"/lib/{triple}", f"/usr/lib/{triple}", "/lib64", "/usr/lib64",
    )
    for source, destination, _ in files:
        if source.is_symlink() or not is_userland_path(destination, executable):
            continue
        abi = read_elf_abi(source)
        if abi is None:
            continue
        if (abi.elf_class, abi.machine) != ELF_ARCHITECTURES[arch] or abi.encoding != 1:
            raise ValueError(f"ELF 架构或字节序与 {arch} 不符：{destination}")
        if arch == "armhf" and abi.flags & _EF_ARM_ABI_FLOAT_SOFT:
            raise ValueError(f"ELF 使用软浮点 ABI，与 armhf 不符：{destination}")
        if abi.interpreter:
            if not abi.interpreter.startswith("/") or _sdk_file(sdk, abi.interpreter) is None:
                raise ValueError(
                    f"ELF 加载器与目标 SDK 不兼容：{destination} 需要 {abi.interpreter}"
                )
        for name in abi.needed:
            if _LIBC_DEPENDENCY.fullmatch(name) and not any(
                _sdk_file(sdk, f"{directory}/{name}") for directory in directories
            ):
                raise ValueError(f"ELF libc ABI 与目标 SDK 不兼容：{destination} 需要 {name}")
