#!/usr/bin/env python3
"""校验厂商输入并提取用户态文件，由 flange 默认后端生成自有 DEB。"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import urllib.request


UPSTREAM_NAME = "libmali-valhall-g610-g24p0-x11-wayland-gbm"
UPSTREAM_FILE = f"{UPSTREAM_NAME}_1.9-1_arm64.deb"
UPSTREAM_URL = (
    "https://github.com/tsukumijima/libmali-rockchip/releases/download/"
    f"v1.9-1-20260312-bd33ee2/{UPSTREAM_FILE}"
)
UPSTREAM_SHA256 = "9eb1e52298deb7395bcd87ca75abd7bea53ff724ad8be3e72326782568191bbc"


def verify(path: Path) -> None:
    """缓存命中也校验，损坏文件不得进入解包阶段。"""
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    if digest != UPSTREAM_SHA256:
        raise ValueError(f"厂商 libmali SHA-256 不匹配：{path}")


def download(directory: Path) -> Path:
    """只发布摘要正确的完整下载，临时文件在失败时清理。"""
    directory.mkdir(parents=True, exist_ok=True)
    cached = directory / UPSTREAM_FILE
    if cached.exists():
        verify(cached)
        return cached
    with tempfile.NamedTemporaryFile(dir=directory, delete=False) as stream:
        temporary = Path(stream.name)
    try:
        with urllib.request.urlopen(UPSTREAM_URL, timeout=120) as response:
            with temporary.open("wb") as stream:
                shutil.copyfileobj(response, stream)
        verify(temporary)
        temporary.replace(cached)
    finally:
        temporary.unlink(missing_ok=True)
    return cached


def main() -> None:
    """在 Docker 内安装到 DESTDIR，不执行上游包的维护脚本。"""
    if os.environ["FLANGE_TARGET_ARCH"] != "aarch64":
        raise ValueError("厂商 Mali-G610 包仅支持 aarch64")
    archive = download(Path(os.environ["FLANGE_BUILD_ROOT"]) / "sources" / "rockchip-mali")
    destination = Path(os.environ["DESTDIR"])
    subprocess.run(["dpkg-deb", "--extract", str(archive), str(destination)], check=True)
    # BSP 已将同源 CSF firmware 编译注入；不分发另一版本的独立固件。
    (destination / "lib/firmware/mali_csffw.bin").unlink()
    # 不强制提升所有交互进程的 GPU 线程优先级。
    (destination / "etc/profile.d/mali-priority.sh").unlink()
    # 保留版权，并把来源记录放到 flange 自有包名下。
    documents = destination / "usr/share/doc"
    (documents / UPSTREAM_NAME).rename(documents / "flange-mali-g610")
    (documents / "flange-mali-g610/upstream.txt").write_text(
        f"厂商输入：{UPSTREAM_URL}\nSHA-256：{UPSTREAM_SHA256}\n", encoding="utf-8",
    )


if __name__ == "__main__":
    main()
