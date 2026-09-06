"""按工作区声明挂载外部源码；宿主机和容器保持同一绝对路径。"""

from pathlib import Path
import subprocess

from builder.workspace import WorkspaceContext


def _mount_root(source: Path) -> Path:
    """保留同一 Git 仓库内兄弟目录引用，无 Git 时只挂载声明目录。"""
    try:
        result = subprocess.run(
            ["git", "-C", str(source), "rev-parse", "--show-toplevel"],
            check=True,
            capture_output=True,
            text=True,
        )
        return Path(result.stdout.strip()).resolve()
    except (OSError, subprocess.CalledProcessError):
        return source.resolve()


def workspace_mounts(context: WorkspaceContext, config: dict) -> list[Path]:
    """在进入容器前枚举所有声明的本地输入；不下载远程仓库。"""
    declared = [*context.apps.values()]
    optional = [*context.app_dirs]
    for item in (config.get("external_apps") or {}).values():
        if item.get("local_path"):
            declared.append(Path(item["local_path"]))
    optional += [Path(path) for path in config.get("external_app_dirs", [])]
    for item in (config.get("sources") or {}).values():
        if item.get("local_path"):
            path = Path(item["local_path"]).expanduser()
            declared.append(path if path.is_absolute() else context.tool_root / path)
    roots = {context.tool_root, context.workspace_root}
    for path in declared:
        if not path.is_dir():
            raise FileNotFoundError(f"已声明的本地源码目录不存在：{path}；请修正工作区或来源配置")
        roots.add(_mount_root(path))
    for path in optional:
        if path.is_dir():
            roots.add(_mount_root(path))
    return sorted(roots, key=str)
