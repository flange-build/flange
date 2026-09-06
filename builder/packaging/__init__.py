"""内建包格式注册入口；新增格式实现 PackageBackend 并在此注册。"""

from __future__ import annotations

from builder.packaging.base import PackageBackend


def get_backend(format: str) -> PackageBackend:
    # 延迟导入避免 AppSpec 与默认打包器的类型引用形成初始化环。
    from builder.packaging.deb import DebPackageBackend

    backends = {"deb": DebPackageBackend}
    try:
        return backends[format]()
    except KeyError as error:
        raise ValueError(
            f"不支持的包格式 {format!r}；可用格式：{', '.join(backends)}"
        ) from error
