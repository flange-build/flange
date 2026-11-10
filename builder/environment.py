"""构建环境身份：容器镜像身份与实际可执行文件共同决定环境。"""

from __future__ import annotations

import os
from pathlib import Path

from builder.digest import file_sha256


def environment_identity(
    *, emulator: str | None = None, config=None, context=None
) -> dict:
    """只读查询，无 Docker 启动或下载；宿主查询可由 CLI 注入镜像 ID。"""
    from builder.build_environment import environment_name

    name = environment_name(config or {}, context)
    marker = os.environ.get("FLANGE_ENVIRONMENT_PROVIDER", "")
    image = os.environ.get("FLANGE_BUILD_ENVIRONMENT", "") if marker == name else ""
    if context is not None and not Path("/.dockerenv").exists():
        image = getattr(context, "environment_ids", {}).get(name, image)
    result: dict = {"image": image or None}
    if image:
        return result
    if Path("/.dockerenv").exists():
        files = [
            Path("/var/lib/dpkg/status"),
            Path("/usr/bin/tar"),
            Path("/usr/bin/apt-get"),
        ]
        if emulator:
            files.append(Path("/usr/bin") / emulator)
        result["tools"] = {
            str(path): file_sha256(path) for path in files if path.is_file()
        }
    elif not image:
        result["unresolved"] = "容器环境身份尚未解析"
    return result
