"""外部（OOT）App 目录到构建容器的挂载映射。

`external_apps[*].local_path` 指向 flange 仓库之外的 App 源码目录。构建容器只
默认挂载 flange 自身（`.:/workspace`），因此这些目录必须在 `docker compose run`
的那一层就用 `--volume` 挂进去：容器内部无法再动态挂载（见 `DockerRunner` 在
容器内分支对 `extra_mounts` 的显式忽略），而 App 目录在**解析阶段**就要可见，
比编译阶段更早。

`flange build` 与 `flange push` 是两条独立的容器调用路径，都需要这份映射。此前
只有 build 路径（envsetup.sh 的 `_flange_docker_run`）计算了挂载，push 路径
（builder/deploy.py）没有，导致 `flange push app <OOT App>` 在容器内解析 App
目录时报“local_path 不存在”。两条路径共用本模块以杜绝再次漏挂。

挂载点选取：以 App 所在 git 仓库根为挂载单元（而非 App 子目录），使仓库内的相对
引用（如 Swift 包对上级目录的依赖）在容器内保持同样的相对布局；容器内路径按该
仓库相对 flange 项目根的相对路径映射到 /workspace 之下，从而让宿主机与容器里的
相对路径完全一致。
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from builder.paths import PROJECT_ROOT

CONTAINER_PROJECT_ROOT = Path("/workspace")


def _mount_root(source: Path) -> Path:
    """返回 source 所属的 git 仓库根；非 git 目录则回退为 source 自身。"""
    try:
        result = subprocess.run(
            ["git", "-C", str(source), "rev-parse", "--show-toplevel"],
            check=True,
            capture_output=True,
            text=True,
        )
        return Path(result.stdout.strip()).resolve()
    except (OSError, subprocess.CalledProcessError):
        return source


def oot_mount_pairs(config: dict) -> dict[str, str]:
    """计算 {宿主机路径: 容器内路径} 映射。

    已位于 flange 项目根之内的目录由默认的 `.:/workspace` 覆盖，跳过。
    路径不存在时抛 FileNotFoundError——静默跳过会让后续报错发生在容器内、
    表现为难以理解的“local_path 不存在”。
    """
    paths: list[Path] = []
    for entry in (config.get("external_apps") or {}).values():
        local_path = entry.get("local_path")
        if local_path:
            paths.append(Path(local_path))
    for directory in config.get("external_app_dirs") or []:
        paths.append(Path(directory))

    project_root = Path(PROJECT_ROOT).resolve()
    mounts: dict[str, str] = {}
    for path in paths:
        source = path.expanduser().resolve()
        if not source.exists():
            raise FileNotFoundError(
                f"OOT App 路径不存在，无法挂载到构建容器：{source}"
            )
        mount_root = _mount_root(source)
        if mount_root.is_relative_to(project_root):
            continue
        relative = os.path.relpath(mount_root, project_root)
        container_root = (CONTAINER_PROJECT_ROOT / relative).resolve()
        mounts[str(mount_root)] = str(container_root)
    return mounts


def oot_volume_arguments(config: dict) -> list[str]:
    """把映射展开为 `docker compose run` 的 --volume 参数序列。"""
    arguments: list[str] = []
    for source, target in sorted(oot_mount_pairs(config).items()):
        arguments.extend(["--volume", f"{source}:{target}:rw"])
    return arguments


def print_mount_pairs() -> None:
    """供 envsetup.sh 消费：每行一个 `宿主机路径\\t容器内路径`。"""
    from builder.config.loader import STATE_FILE, load_current_config

    if not STATE_FILE.is_file():
        return
    for source, target in sorted(oot_mount_pairs(load_current_config()).items()):
        print(f"{source}\t{target}")
