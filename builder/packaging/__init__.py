"""内建包格式注册入口；新增格式实现 PackageBackend 并在此注册。"""

from __future__ import annotations

from builder.packaging.base import PackageBackend


def get_backend(format: str, layer_stack=None) -> PackageBackend:
    # 延迟导入避免 AppSpec 与默认打包器的类型引用形成初始化环。
    from builder.packaging.deb import DebPackageBackend

    if layer_stack is not None:
        module = layer_stack.provider("packaging", format)
        if module is not None:
            backend = module.create_backend()
            if not isinstance(backend, PackageBackend):
                raise ValueError(f"包策略 {format} 必须返回 PackageBackend")
            return backend
    backends = {"deb": DebPackageBackend}
    try:
        return backends[format]()
    except KeyError as error:
        raise ValueError(
            f"不支持的包格式 {format!r}；可用格式：{', '.join(backends)}"
        ) from error
