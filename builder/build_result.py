"""系统构建进程之间的单次失败回执，避免重复呈现同一个错误。"""

import json
import os
import secrets
import tempfile
from pathlib import Path

from builder.locking import atomic_write


class BuildFailure(RuntimeError):
    """携带容器已确认的错误分类与呈现状态。"""

    def __init__(self, message, *, code, kind, reported):
        super().__init__(message)
        self.code = code
        self.kind = kind
        self._flange_reported = reported


def write_failure(message: str, *, code: int, kind: str) -> None:
    """仅在已呈现失败后写回宿主提供的专用回执文件。"""
    destination = os.environ.get("FLANGE_BUILD_RESULT_FILE")
    request_id = os.environ.get("FLANGE_BUILD_REQUEST_ID")
    if not destination or not request_id:
        return
    payload = {
        "schema_version": 1,
        "request_id": request_id,
        "message": message,
        "exit_code": code,
        "kind": kind,
        "reported": True,
    }
    try:
        atomic_write(Path(destination), json.dumps(payload, ensure_ascii=False))
    except OSError:
        # 回执不可写时，宿主仍按 Docker 非零退出报告，不静默失败。
        pass


def read_failure(path: Path, *, request_id: str, code: int) -> BuildFailure | None:
    """版本、调用身份和退出码必须同时匹配；无有效回执时保留 Docker 错误。"""
    try:
        value = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    if (
        not isinstance(value, dict)
        or value.get("schema_version") != 1
        or value.get("request_id") != request_id
        or value.get("exit_code") != code
        or code not in {1, 2, 130}
        or value.get("kind") not in {"operation", "configuration", "internal", "cancelled"}
        or not isinstance(value.get("message"), str)
        or not value["message"]
        or value.get("reported") is not True
    ):
        return None
    return BuildFailure(value["message"], code=code, kind=value["kind"], reported=True)


def run_build_container(runner, command, *, env=None, **kwargs):
    """系统、App 和 Package 构建共用一次容器执行及失败回执。"""
    from builder.docker import BuildError

    runner.context.build_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=".build-result-", dir=runner.context.build_root
    ) as directory:
        receipt = Path(directory) / "failure.json"
        request_id = secrets.token_hex(16)
        result = runner.run(
            command,
            env={
                **(env or {}),
                "FLANGE_BUILD_RESULT_FILE": str(receipt),
                "FLANGE_BUILD_REQUEST_ID": request_id,
            },
            check=False,
            **kwargs,
        )
        if result.returncode:
            failure = read_failure(receipt, request_id=request_id, code=result.returncode)
            if failure:
                raise failure
            raise BuildError(
                f"构建容器执行失败（退出码 {result.returncode}），请检查上方 Docker 诊断"
            )
        return result
