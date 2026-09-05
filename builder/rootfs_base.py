"""rootfs/recovery 共用的 Phase 1 计划与执行，不依赖 Phase 2 配置。"""

from __future__ import annotations

from pathlib import Path

from builder.chroot import ChrootContext
from builder.config.canonical import userspace_arch
from builder.environment import environment_identity
from builder.graph import InputSpec, TaskPlan
from builder.locking import FileLock
from builder.snapshot import TAR_METADATA_OPTIONS


def emulator_for(config: dict) -> str:
    explicit = (config.get("rootfs") or {}).get("emulator")
    if explicit:
        return explicit
    arch = userspace_arch(config)
    try:
        return {"aarch64": "qemu-aarch64-static", "armhf": "qemu-arm-static"}[arch]
    except KeyError:
        raise ValueError(f"架构 {arch!r} 必须声明 rootfs.emulator") from None


def base_plan(config: dict, component: str, context) -> TaskPlan:
    """两个系统共享同一配方，只把真正消费的 APT 输入纳入计划。"""
    base = config.get("rootfs") or {}
    settings = config.get(component) or {}
    emulator = emulator_for(config)
    inputs = [
        InputSpec.value(
            "tarball", {key: base[key] for key in ("url", "sha256", "filename") if key in base}
        ),
        InputSpec.value(
            "apt",
            {
                "packages": sorted(settings.get("packages") or []),
                "install_recommends": settings.get("install_recommends", False),
                "extra_sources": settings.get("extra_apt_sources") or [],
            },
        ),
        InputSpec.value("architecture", userspace_arch(config)),
        InputSpec.value("emulator", emulator),
        InputSpec.value("environment", environment_identity(emulator=emulator)),
    ]
    for filename in (
        "rootfs_base.py", "rootfs_storage.py", "snapshot.py", "chroot.py", "source.py", "docker.py",
        "environment.py",
    ):
        path = context.tool_root / "builder" / filename
        if path.is_file():
            inputs.append(InputSpec.file(f"recipe:{filename}", path))
    return TaskPlan("rootfs:base", "ubuntu-base-apt-v1", tuple(inputs), ())


def apt_command(apt: dict) -> list[str]:
    command = ["apt-get", "install", "-y"]
    if not apt["install_recommends"]:
        command.append("--no-install-recommends")
    return command + list(apt["packages"])


def install_extra_sources(rootfs_dir: Path, entries: list, source, docker, status) -> None:
    keyrings = rootfs_dir / "etc/apt/keyrings"
    sources = rootfs_dir / "etc/apt/sources.list.d"
    keyrings.mkdir(parents=True, exist_ok=True)
    sources.mkdir(parents=True, exist_ok=True)
    for entry in entries:
        name = entry["name"]
        key_file = source.ensure_download("apt-keys", name, entry["key"])
        status(f"导入 APT key: {name}")
        docker.run(
            [
                "gpg",
                "--batch",
                "--yes",
                "--dearmor",
                "-o",
                str(keyrings / f"{name}.gpg"),
                str(key_file),
            ],
            label=f"导入 APT key: {name}",
        )
        (sources / f"{name}.list").write_text(entry["source"] + "\n")


def build_base(plan: TaskPlan, rootfs_dir: Path, *, context, source, docker, status) -> None:
    """全部可变参数来自计划，不再重新查询完整系统配置。"""
    tarball = source.ensure_download("rootfs", "rootfs", plan.value("tarball"))
    docker.run_privileged(
        ["tar", *TAR_METADATA_OPTIONS, "-xf", str(tarball), "-C", str(rootfs_dir)]
    )
    emulator = plan.value("emulator")
    docker.run_privileged(["cp", f"/usr/bin/{emulator}", str(rootfs_dir / "usr/bin/")])
    apt = plan.value("apt")
    apt_cache = context.build_root / "cache/apt"
    apt_cache.mkdir(parents=True, exist_ok=True)
    with (
        FileLock(context.build_root / "locks/apt-cache.lock"),
        ChrootContext(rootfs_dir, docker) as chroot,
    ):
        chroot.bind_mount(str(apt_cache), rootfs_dir / "var/cache/apt/archives")
        status("apt-get update...")
        chroot.run(["apt-get", "update"], label="apt-get update...")
        if apt["extra_sources"]:
            chroot.run(["apt-get", "install", "-y", "--no-install-recommends", "ca-certificates"])
            chroot.run(["update-ca-certificates"])
            install_extra_sources(rootfs_dir, apt["extra_sources"], source, docker, status)
            chroot.run(["apt-get", "update"], label="apt-get update（含额外源）...")
        if apt["packages"]:
            chroot.run(apt_command(apt), label=f"安装 {len(apt['packages'])} 个包...")
        chroot.run(["apt-get", "clean"])
