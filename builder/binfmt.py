"""在 Docker 所用内核中检查并补齐跨架构执行支持。"""

import json
import subprocess

from builder.docker import BuildError


# 固定多架构镜像摘要，避免特权工具随 latest 漂移。
BINFMT_IMAGE = (
    "tonistiigi/binfmt@sha256:"
    "400a4873b838d1b89194d982c45e5fb3cda4593fbfd7e08a02e76b03b21166f0"
)


def _invoke(*args: str) -> dict:
    command = ["docker", "run", "--privileged", "--rm", BINFMT_IMAGE, *args]
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, check=True, timeout=180,
        )
    except (OSError, subprocess.SubprocessError) as error:
        detail = getattr(error, "stderr", None) or str(error)
        raise BuildError(
            f"Docker binfmt 检查/注册失败：{detail}；"
            "请确认 Docker 可运行特权容器且能获取 binfmt 镜像，再重试原构建命令"
        ) from error
    try:
        value = json.loads(result.stdout)
        supported = value["supported"]
        if not isinstance(supported, list) or not all(isinstance(x, str) for x in supported):
            raise ValueError("supported 必须为架构列表")
    except (ValueError, KeyError, TypeError) as error:
        raise BuildError(f"Docker binfmt 返回无效的架构检测结果：{result.stdout}") from error
    return value


def ensure_binfmt(userspace: str, platform: str = "linux/amd64") -> None:
    """每次构建重新检测；已支持的架构不注册，注册后再次验证真实执行能力。"""
    architecture = {"armhf": "arm/v7", "aarch64": "arm64", "x86_64": "amd64"}.get(
        userspace, userspace,
    )
    required = {platform, f"linux/{architecture}"}
    missing = required - set(_invoke()["supported"])
    if not missing:
        return
    # 安装器以 arm 统称 ARM32，其他架构使用 OCI 名称。
    installers = sorted({item.split("/")[1] for item in missing})
    _invoke("--install", ",".join(installers))
    missing = required - set(_invoke()["supported"])
    if missing:
        raise BuildError(
            f"binfmt 注册后仍无法执行 {', '.join(sorted(missing))}；"
            "请检查 Docker 内核的 binfmt_misc 与特权容器支持，再重试原构建命令"
        )
