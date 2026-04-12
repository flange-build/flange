"""Docker 容器执行封装。"""

import os
import subprocess
from pathlib import Path


class BuildError(Exception):
    """构建过程中的错误"""
    pass


def _is_inside_container() -> bool:
    """检测当前进程是否已在 Docker 容器内运行。"""
    return os.path.exists("/.dockerenv")


class DockerRunner:
    """在 Docker 容器内执行命令。

    如果当前已在容器内运行（由 flange build 通过 docker compose run 启动），
    则直接 subprocess.run 执行命令，不再嵌套 docker。

    当 output (BuildOutput) 已注入时，使用 Popen 逐行捕获输出，
    实现日志持久化 + 过滤显示。
    """

    def __init__(self, project_dir: Path = None, output=None):
        self.project_dir = project_dir or Path.cwd()
        self.output = output  # BuildOutput | None
        self._in_container = _is_inside_container()

    def run(self, cmd: list, *, cwd: str = None, env: dict = None,
            privileged: bool = False, check: bool = True,
            capture: bool = False,
            input: str = None,
            label: str = "") -> subprocess.CompletedProcess:

        # capture 或 input 模式不走输出捕获流
        if (self.output and not capture and not input
                and self._in_container):
            return self._run_with_capture(
                cmd, cwd=cwd, env=env, check=check, label=label)

        if self._in_container:
            return self._run_direct(cmd, cwd=cwd, env=env,
                                    check=check, capture=capture,
                                    input=input)
        return self._run_docker(cmd, cwd=cwd, env=env,
                                privileged=privileged, check=check,
                                capture=capture, input=input)

    def _run_with_capture(self, cmd: list, *, cwd: str = None,
                          env: dict = None, check: bool = True,
                          label: str = "") -> subprocess.CompletedProcess:
        """Popen 逐行捕获模式 — 输出写日志 + 过滤显示。"""
        run_env = None
        if env:
            run_env = {**os.environ, **env}

        kwargs = {"stdout": subprocess.PIPE, "stderr": subprocess.STDOUT,
                  "bufsize": 1, "text": True}
        if cwd:
            kwargs["cwd"] = cwd
        if run_env:
            kwargs["env"] = run_env

        # 启动 spinner
        if label:
            self.output.spinner_start(label)

        proc = subprocess.Popen([str(c) for c in cmd], **kwargs)
        try:
            for line in proc.stdout:
                self.output.feed_line(line)
        finally:
            proc.wait()
            if label:
                self.output.spinner_stop()

        if check and proc.returncode != 0:
            raise BuildError(
                f"命令失败 (exit {proc.returncode}): {' '.join(str(c) for c in cmd)}")

        return subprocess.CompletedProcess(
            args=cmd, returncode=proc.returncode)

    def _run_direct(self, cmd: list, *, cwd: str = None, env: dict = None,
                    check: bool = True, capture: bool = False,
                    input: str = None
                    ) -> subprocess.CompletedProcess:
        """容器内直接执行命令。"""
        run_env = None
        if env:
            run_env = {**os.environ, **env}

        kwargs = {}
        if cwd:
            kwargs["cwd"] = cwd
        if run_env:
            kwargs["env"] = run_env
        if capture:
            kwargs["capture_output"] = True
            kwargs["text"] = True
        if input is not None:
            kwargs["input"] = input
            kwargs["text"] = True
            # input 模式总是捕获 stderr，便于诊断 chpasswd 等
            # 可能静默失败的命令
            kwargs["capture_output"] = True

        result = subprocess.run([str(c) for c in cmd], **kwargs)
        if check and result.returncode != 0:
            msg = (f"命令失败 (exit {result.returncode}): "
                   f"{' '.join(str(c) for c in cmd)}")
            if getattr(result, "stderr", None):
                msg += f"\nstderr: {result.stderr}"
            if getattr(result, "stdout", None):
                msg += f"\nstdout: {result.stdout}"
            raise BuildError(msg)
        return result

    def _run_docker(self, cmd: list, *, cwd: str = None, env: dict = None,
                    privileged: bool = False, check: bool = True,
                    capture: bool = False,
                    input: str = None) -> subprocess.CompletedProcess:
        """通过 docker compose run 执行命令。"""
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
        if input is not None:
            kwargs["input"] = input
            kwargs["text"] = True

        result = subprocess.run(docker_cmd, **kwargs)
        if check and result.returncode != 0:
            raise BuildError(
                f"Docker 命令失败 (exit {result.returncode}): {' '.join(str(c) for c in cmd)}")
        return result

    def run_privileged(self, cmd: list, **kwargs):
        """特权模式执行（rootfs chroot/mount 操作需要）"""
        return self.run(cmd, privileged=True, **kwargs)
