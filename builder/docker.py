"""Docker 容器执行封装。"""

import os
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from builder.process import run_logged

if TYPE_CHECKING:
    from builder.workspace import WorkspaceContext


class BuildError(RuntimeError):
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

    def __init__(
        self, project_dir: Path = None, output=None, *, context: "WorkspaceContext | None" = None, config: dict | None = None
    ):
        self.context = context
        self.project_dir = Path(
            context.tool_root if context else (project_dir or Path.cwd())
        ).resolve()
        self.output = output  # BuildOutput | None
        self._in_container = _is_inside_container()
        self._environment_id = None
        from builder.build_environment import environment_name, resolve_environment
        if config is None and context is not None and len(context.layer_stack.layers) > 1:
            from builder.workspace import resolve_config
            config = resolve_config(context)
        self.config = config or {}
        self.environment_name = environment_name(self.config, context)
        self.environment_spec = resolve_environment(self.config, context)
        marker = os.environ.get("FLANGE_ENVIRONMENT_PROVIDER", "")
        if self._in_container:
            if marker != self.environment_name or not os.environ.get("FLANGE_BUILD_ENVIRONMENT"):
                raise BuildError(f"容器环境与请求不一致：{marker or '未标识'} != {self.environment_name}；请从宿主机启动构建")
            self._environment_id = os.environ["FLANGE_BUILD_ENVIRONMENT"]
            for tool, version in (self.environment_spec.required_tools if self.environment_spec else ()):
                result = subprocess.run([tool, "--version"], capture_output=True, text=True, check=True)
                if version not in result.stdout:
                    raise BuildError(f"工具版本不匹配：{tool}，需要 {version}")

    def compose_command(self, *args: str) -> list[str]:
        compose = self.project_dir / "docker-compose.yml"
        if self.environment_spec is not None:
            import json
            from builder.locking import atomic_write
            spec = self.environment_spec
            root = self.context.build_root if self.context else self.project_dir / ".build"
            compose = root / "environments" / spec.name / "compose.json"
            service = {
                "image": "${FLANGE_BUILD_IMAGE:-" + spec.image + "}",
                "platform": spec.platform,
                "privileged": "${FLANGE_BUILD_PRIVILEGED:-false}",
                "working_dir": str(self.project_dir),
            }
            if spec.dockerfile is not None:
                service["build"] = {"context": str(spec.build_context), "dockerfile": str(spec.dockerfile)}
            content = json.dumps({"services": {"build": service}}, indent=2) + "\n"
            if not compose.is_file() or compose.read_text() != content:
                atomic_write(compose, content)
        return [
            "docker",
            "compose",
            "--project-directory",
            str(self.project_dir),
            "-f",
            str(compose),
            *args,
        ]

    def environment_identity(self) -> str:
        """获取本次真正执行的镜像，不能只用 Dockerfile 代替工具环境。"""
        if self._environment_id is None:
            try:
                names = subprocess.run(
                    self.compose_command("config", "--images"),
                    text=True,
                    capture_output=True,
                    check=True,
                    timeout=10,
                )
            except subprocess.CalledProcessError as exc:
                detail = (exc.stderr or exc.stdout or str(exc)).strip()
                raise BuildError(f"无法解析 Docker Compose 构建环境：{detail}") from exc
            image_name = names.stdout.strip().splitlines()[0]
            image = subprocess.run(
                ["docker", "image", "inspect", "--format", "{{.Id}}", image_name],
                text=True,
                capture_output=True,
                timeout=10,
            )
            if image.returncode or not image.stdout.strip():
                daemon = subprocess.run(
                    ["docker", "info", "--format", "{{.ServerVersion}}"],
                    text=True,
                    capture_output=True,
                    timeout=10,
                )
                if daemon.returncode:
                    raise BuildError(
                        "Docker 不可用。请启动 Docker Desktop 或 Docker Engine，再运行 flange doctor"
                    )
                raise BuildError("构建镜像尚未准备好。请运行 flange docker build 后重试")
            self._environment_id = image.stdout.strip()
        return self._environment_id

    def run(
        self,
        cmd: list,
        *,
        cwd: str = None,
        env: dict = None,
        privileged: bool = False,
        check: bool = True,
        capture: bool = False,
        input: str = None,
        label: str = "",
        extra_mounts: list = None,
    ) -> subprocess.CompletedProcess:
        """执行并在失败离开本命令时冻结诊断；后续清理使用独立缓冲。"""
        if self.output is not None:
            self.output.command_start(cmd)
        try:
            return self._execute(
                cmd, cwd=cwd, env=env, privileged=privileged, check=check,
                capture=capture, input=input, label=label, extra_mounts=extra_mounts,
            )
        except BaseException as error:
            if self.output is not None:
                self.output.command_failed(error)
            raise

    def _execute(
        self,
        cmd: list,
        *,
        cwd: str = None,
        env: dict = None,
        privileged: bool = False,
        check: bool = True,
        capture: bool = False,
        input: str = None,
        label: str = "",
        extra_mounts: list = None,
    ) -> subprocess.CompletedProcess:

        # capture 或 input 模式不走输出捕获流
        if self.output and not capture and input is None and self._in_container:
            return self._run_with_capture(
                cmd, cwd=cwd, env=env, check=check, label=label, extra_mounts=extra_mounts
            )

        if self._in_container:
            return self._run_direct(
                cmd,
                cwd=cwd,
                env=env,
                check=check,
                capture=capture,
                input=input,
                extra_mounts=extra_mounts,
            )
        return self._run_docker(
            cmd,
            cwd=cwd,
            env=env,
            privileged=privileged,
            check=check,
            capture=capture,
            input=input,
            extra_mounts=extra_mounts,
            label=label,
        )

    def _run_with_capture(
        self,
        cmd: list,
        *,
        cwd: str = None,
        env: dict = None,
        check: bool = True,
        label: str = "",
        extra_mounts: list = None,
    ) -> subprocess.CompletedProcess:
        """Popen 逐行捕获模式 — 输出写日志 + 过滤显示。"""
        run_env = None
        if env:
            run_env = {**os.environ, **env}

        kwargs = {
            "stdout": subprocess.PIPE,
            "stderr": subprocess.STDOUT,
            "bufsize": 1,
            "text": True,
        }
        if cwd:
            kwargs["cwd"] = cwd
        if run_env:
            kwargs["env"] = run_env

        # 启动 spinner
        if label:
            self.output.spinner_start(label)

        proc = subprocess.Popen([str(c) for c in cmd], **kwargs)
        cancelled = False
        try:
            for line in proc.stdout:
                self.output.feed_line(line)
        except KeyboardInterrupt:
            cancelled = True
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
            raise
        finally:
            proc.wait()
            if label:
                self.output.spinner_stop(success=proc.returncode == 0, cancelled=cancelled)

        if check and proc.returncode != 0:
            raise BuildError(f"命令失败 (exit {proc.returncode}): {' '.join(str(c) for c in cmd)}")

        return subprocess.CompletedProcess(args=cmd, returncode=proc.returncode)

    def _run_direct(
        self,
        cmd: list,
        *,
        cwd: str = None,
        env: dict = None,
        check: bool = True,
        capture: bool = False,
        input: str = None,
        extra_mounts: list = None,
    ) -> subprocess.CompletedProcess:
        """容器内直接执行命令。

        extra_mounts 参数仅为 API 一致性而保留：已在容器内运行时，外部目录
        必须在上层 docker compose 调用时就已挂载好，此处忽略该参数。
        """
        _ = extra_mounts  # 显式忽略，容器内运行无法动态挂载
        run_env = None
        if env:
            run_env = {**os.environ, **env}

        kwargs = {"stdout": sys.stdout}
        if cwd:
            kwargs["cwd"] = cwd
        if run_env:
            kwargs["env"] = run_env
        if capture:
            kwargs.pop("stdout", None)
            kwargs["capture_output"] = True
            kwargs["text"] = True
        if input is not None:
            kwargs.pop("stdout", None)
            kwargs["input"] = input
            kwargs["text"] = True
            # input 模式总是捕获 stderr，便于诊断 chpasswd 等
            # 可能静默失败的命令
            kwargs["capture_output"] = True

        result = subprocess.run([str(c) for c in cmd], **kwargs)
        if self.output and (capture or input is not None):
            for value in (result.stdout, result.stderr):
                for line in (value or "").splitlines(keepends=True):
                    self.output.feed_line(line)
        if check and result.returncode != 0:
            msg = f"命令失败 (exit {result.returncode}): {' '.join(str(c) for c in cmd)}"
            if getattr(result, "stderr", None):
                msg += f"\nstderr: {result.stderr}"
            if getattr(result, "stdout", None):
                msg += f"\nstdout: {result.stdout}"
            raise BuildError(msg)
        return result

    def _run_docker(
        self,
        cmd: list,
        *,
        cwd: str = None,
        env: dict = None,
        privileged: bool = False,
        check: bool = True,
        capture: bool = False,
        input: str = None,
        extra_mounts: list = None,
        label: str = "",
    ) -> subprocess.CompletedProcess:
        """通过 docker compose run 执行命令。

        extra_mounts 用于把宿主机任意目录动态挂入容器，源路径与目标路径相同
        （便于 cwd 在宿主与容器内保持一致）。每条路径都先经 os.path.realpath
        解析以展平 symlink。
        """
        # 仅关闭 Compose 自身的创建进度；工具输出和 Docker 错误继续透传。
        docker_cmd = self.compose_command(
            "--ansi", "never", "--progress", "quiet", "run", "--rm", "--no-deps"
        )
        if self.output or not sys.stdin.isatty() or not sys.stdout.isatty():
            docker_cmd.append("-T")
        mounts = [self.project_dir, *(extra_mounts or [])]
        environment = {
            "PYTHONPATH": str(self.project_dir),
            "PYTHONDONTWRITEBYTECODE": "1",
            "FLANGE_BUILD_ENVIRONMENT": self.environment_identity(),
            "FLANGE_ENVIRONMENT_PROVIDER": self.environment_name,
        }
        if self.context:
            self.context.build_root.mkdir(parents=True, exist_ok=True)
            mounts.extend(
                [
                    self.context.workspace_root,
                    self.context.build_root,
                    *self.context.apps.values(),
                    *self.context.app_dirs,
                    *(layer.root for layer in self.context.layer_stack.layers),
                ]
            )
            environment["CCACHE_DIR"] = str(self.context.build_root / "cache" / "ccache")
        # 同一路径只挂载一次；父目录覆盖子目录，避免 Compose 隐式创建错误目录。
        roots = sorted(
            {Path(m).resolve() for m in mounts if Path(m).exists()}, key=lambda p: len(p.parts)
        )
        selected = []
        for root in roots:
            if not any(root == parent or parent in root.parents for parent in selected):
                selected.append(root)
                docker_cmd.extend(["-v", f"{root}:{root}:rw"])
        docker_cmd.extend(["-w", str(cwd or self.project_dir)])
        environment.update(env or {})
        for key in ("NO_COLOR", "TERM", "FLANGE_NO_INTERACTION"):
            if key in os.environ:
                environment.setdefault(key, os.environ[key])
        for key, value in environment.items():
            docker_cmd.extend(["-e", f"{key}={value}"])
        docker_cmd.append("build")
        docker_cmd.extend([str(c) for c in cmd])

        kwargs = {
            "cwd": self.project_dir,
            "stdout": sys.stdout,
            # Compose run 不接受 --privileged；由服务配置在本次调用时求值。
            # 显式传 false，避免普通 App 构建继承宿主的特权开关。
            "env": {
                **os.environ,
                "FLANGE_BUILD_IMAGE": self.environment_identity(),
                "FLANGE_BUILD_PRIVILEGED": "true" if privileged else "false",
            },
        }
        if capture:
            kwargs.pop("stdout", None)
            kwargs["capture_output"] = True
            kwargs["text"] = True
        if input is not None:
            kwargs["input"] = input
            kwargs["text"] = True
            if self.output:
                kwargs.pop("stdout", None)
                kwargs["capture_output"] = True

        if self.output and not capture and input is None:
            result = None
            cancelled = False
            if label:
                self.output.spinner_start(label)
            try:
                result = run_logged(
                    docker_cmd, self.output, cwd=self.project_dir,
                    env=kwargs["env"], start_command=False,
                )
            except KeyboardInterrupt:
                cancelled = True
                raise
            finally:
                if label:
                    self.output.spinner_stop(
                        success=result is not None and result.returncode == 0,
                        cancelled=cancelled,
                    )
        else:
            result = subprocess.run(docker_cmd, **kwargs)
            if self.output and (capture or input is not None):
                for value in (result.stdout, result.stderr):
                    for line in (value or "").splitlines(keepends=True):
                        self.output.feed_line(line)
        if check and result.returncode != 0:
            message = f"Docker 命令失败 (exit {result.returncode}): {' '.join(str(c) for c in cmd)}"
            if capture:
                details = "\n".join(value.strip() for value in (result.stderr, result.stdout) if value)
                if details:
                    message += "\n" + details
            raise BuildError(message)
        return result

    def run_privileged(self, cmd: list, **kwargs):
        """特权模式执行（rootfs chroot/mount 操作需要）"""
        return self.run(cmd, privileged=True, **kwargs)
