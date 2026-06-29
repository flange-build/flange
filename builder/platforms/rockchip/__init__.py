"""Rockchip 平台构建策略工厂。"""

from builder.docker import DockerRunner
from builder.source import SourceManager

# 产物名映射：(组件, collect key) → target 目录下的文件名/目录名
ARTIFACT_NAMES = {
    ("kernel",     "dtbos"):      "overlay",
    ("kernel",     "modules"):    "modules",
    ("bootloader", "bootloader"): "u-boot.itb",
    ("bootloader", "idbloader"):  "idbloader.img",
    ("bootloader", "miniloader"): "miniloader.bin",
    ("boot",       "boot"):       "boot.img",
    ("rootfs",     "rootfs"):     "rootfs.img",
    ("recovery",   "recovery"):   "recovery.img",
    ("amp",        "amp"):        "amp.img",
    ("image",      "image"):      "raw.img",
}


def amp_source_dirs(config: dict) -> list:
    """返回 amp 增量哈希应覆盖的源码目录。

    由 cache._mix_amp_sources 委托调用（cache 本身平台无关）。新模型下 amp 固件
    由 amp app（components/app/<amp.app>，自带 CMake 引用 HAL SDK）产出——固件
    内容主要随 app 源变化，故哈希 app 目录 + rockchip-hal.cmake 接口文件。HAL SDK
    本体（lib/middleware，vendored 稳定）改动罕见，不纳入哈希以省时；SDK 或 .cmake
    变更时用 `flange build -f amp` 强制重建。别的平台各自导出同名函数。
    """
    amp = config.get("amp") or {}
    app = amp.get("app", "")
    dirs = []
    if app:
        dirs.append(f"components/app/{app}")
    # rockchip-hal.cmake 是 amp app 的构建接口，改动须触发重建（虽是单文件，
    # _hash_directory 接受目录——故指其所在 hal 根的该文件不便单列；改放 app
    # 目录哈希为主，.cmake 变更走 -f）。
    return dirs


def create_builder(component: str, docker: DockerRunner, source: SourceManager):
    """根据组件名创建对应的 Rockchip 构建器。"""
    if component == "kernel":
        from builder.platforms.rockchip.kernel import RockchipKernelBuilder
        return RockchipKernelBuilder(docker, source)
    elif component == "bootloader":
        from builder.platforms.rockchip.bootloader import RockchipBootloaderBuilder
        return RockchipBootloaderBuilder(docker, source)
    elif component == "rootfs":
        from builder.platforms.rockchip.rootfs import RockchipRootfsBuilder
        return RockchipRootfsBuilder(docker, source)
    elif component == "boot":
        from builder.platforms.rockchip.boot import RockchipBootBuilder
        return RockchipBootBuilder(docker, source)
    elif component == "recovery":
        from builder.platforms.rockchip.recovery import RockchipRecoveryBuilder
        return RockchipRecoveryBuilder(docker, source)
    elif component == "image":
        from builder.platforms.rockchip.image import RockchipImageBuilder
        return RockchipImageBuilder(docker, source)
    elif component == "amp":
        from builder.platforms.rockchip.amp import RockchipAmpBuilder
        return RockchipAmpBuilder(docker, source)
    else:
        raise ValueError(f"未知组件: {component}")
