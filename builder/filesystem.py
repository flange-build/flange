"""构建存储能力门禁：文件系统差异不得静默改变目标系统功能。"""

from pathlib import Path
import tempfile

from builder.docker import BuildError


def require_case_sensitive(directory: Path) -> None:
    """在构建输出存储中探测大小写语义，失败时给出可操作错误。"""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".flange-fs-", dir=directory) as temporary:
        probe = Path(temporary) / "UPPER"
        probe.write_bytes(b"")
        if (probe.parent / "upper").exists():
            raise BuildError(
                f"Linux 内核构建需要大小写敏感的文件系统：{directory}。"
                "请将 flange.toml 的 build_dir 指向大小写敏感卷（例如 APFS Case-sensitive 或 Linux ext4），"
                "然后重新构建；flange 不会通过关闭内核功能绕过文件名冲突。"
            )
