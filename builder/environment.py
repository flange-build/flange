"""构建环境身份：容器镜像身份与实际可执行文件共同决定环境。"""

from __future__ import annotations

import os
from pathlib import Path

from builder.digest import file_sha256


def environment_identity(*, emulator: str | None = None) -> dict:
    """只读查询，无 Docker 启动或下载；宿主查询可由 CLI 注入镜像 ID。"""
    image = os.environ.get("FLANGE_BUILD_ENVIRONMENT", "")
    result: dict = {"image": image or None}
    if image:
        return result
    if Path("/.dockerenv").exists():
        files = [Path("/var/lib/dpkg/status"), Path("/usr/bin/tar"), Path("/usr/bin/apt-get")]
        if emulator:
            files.append(Path("/usr/bin") / emulator)
        result["tools"] = {str(path): file_sha256(path) for path in files if path.is_file()}
    elif not image:
        result["unresolved"] = "容器环境身份尚未解析"
    return result
