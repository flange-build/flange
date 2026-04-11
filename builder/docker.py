"""Docker 容器执行封装。"""

import subprocess
from pathlib import Path


class BuildError(Exception):
    """构建过程中的错误"""
    pass


class DockerRunner:
    """在 Docker 容器内执行命令。"""

    def __init__(self, project_dir: Path = None):
        self.project_dir = project_dir or Path.cwd()

    def run(self, cmd: list, *, cwd: str = None, env: dict = None,
            privileged: bool = False, check: bool = True,
            capture: bool = False) -> subprocess.CompletedProcess:
        docker_cmd = ["docker", "compose", "run", "--rm"]
        if privileged:
            docker_cmd.append("--privileged")
        if cwd:
            docker_cmd.extend(["-w", str(cwd)])
        if env:
            for k, v in env.items():
                docker_cmd.extend(["-e", f"{k}={v}"])
        docker_cmd.append("build")
        docker_cmd.extend([str(c) for c in cmd])

        kwargs = {"cwd": self.project_dir}
        if capture:
            kwargs["capture_output"] = True
            kwargs["text"] = True

        result = subprocess.run(docker_cmd, **kwargs)
        if check and result.returncode != 0:
            raise BuildError(
                f"Docker 命令失败 (exit {result.returncode}): {' '.join(str(c) for c in cmd)}")
        return result

    def run_privileged(self, cmd: list, **kwargs):
        """特权模式执行（rootfs chroot/mount 操作需要）"""
        return self.run(cmd, privileged=True, **kwargs)
