"""APT 并发测试的轻量子进程入口，避免 spawn 重导入 pytest 与 App 构建链。"""

from pathlib import Path
from time import monotonic_ns

from builder.build_dependencies import UbuntuBuildDependencies


def install(tool, tag, events, release):
    """记录事务内实际发生时间，避免异步队列跨进程重排影响断言。"""
    class Runner:
        def run(self, command):
            events.put((tag, command[1], monotonic_ns()))
            if command[1] == "update" and not release.wait(10):
                raise TimeoutError("测试未释放 APT 事务")

    events.put((tag, "ready", monotonic_ns()))
    UbuntuBuildDependencies(Runner(), Path(tool)).install(["example:{arch}"], "aarch64")
