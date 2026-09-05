"""独立资源构建复用系统构建的终端、日志与失败收尾。"""

from builder.locking import FileLock
from builder.output import BuildOutput, OutputLevel


def run_logged(context, config, resource, level, execute, *, retry_command=None):
    """日志轮转和完整执行共享目标锁，任何退出路径均关闭日志。"""
    with FileLock(context.build_root / "locks" / f"{context.target.key}.lock"):
        output = BuildOutput(context.target_dir, level=OutputLevel(level),
                             retry_command=retry_command)
        success = False
        try:
            output.build_start(resource, config)
            output.plan([resource])
            output.phase_start(resource)
            try:
                result = execute(output)
            except BaseException as exc:
                output.phase_end(resource, success=False, error=exc)
                raise
            output.phase_end(resource)
            success = True
            return result
        finally:
            try:
                output.build_end(success=success)
            finally:
                output.close()
