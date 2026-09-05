"""四个平台 rootfs 构造序列的 golden 快照。

**为什么需要它**：`compile` / `_build_phase1` / `_build_phase2` / `_install_fstab`
/ `_install_kernel_modules` 在 4 个平台 rootfs builder + recovery builder 里手抄
5 份，AST 归一化对比显示 1281 行中 537 行（42%）是冗余，且 8 组同名函数中 6 组
已经漂移。把它们合并成一份基类编排是 `docs/refactor-roadmap.md` 的 R2，而 rootfs
是唯一直接决定"板子能不能起来"的组件 —— 单测覆盖的是命令序列而非镜像内容，合并
时最容易犯的错是"漏掉某一步""顺序变了""参数变了"。

这个测试把现状的命令序列固化下来：mock 掉 docker 与 source，记录 `compile()`
发出的全部命令，与 golden 逐条比对。它抓不住文件内容层面的回归，但正好覆盖上面
那三类结构性回归。

**合并 rootfs 编排时**：先在重构前跑 `pytest -k golden --update-golden` 确认
golden 是最新的，重构后必须零 diff。真要改变行为时，连同 golden 一起改，并在
提交信息里说明改了哪一步、为什么。
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from tests.builder.context import component_context

GOLDEN_DIR = Path(__file__).parent / "golden"

PLATFORMS = {
    "rockchip": "builder.platforms.rockchip.rootfs:RockchipRootfsBuilder",
    "allwinnera733": (
        "builder.platforms.allwinnera733.rootfs:AllwinnerA733RootfsBuilder"),
    "amlogic": "builder.platforms.amlogic.rootfs:AmlogicRootfsBuilder",
    "qualcommqcs6490": (
        "builder.platforms.qualcommqcs6490.rootfs:Qcs6490RootfsBuilder"),
}


def _load(spec: str):
    import importlib

    module, name = spec.split(":")
    return getattr(importlib.import_module(module), name)


def _config(platform: str, root: Path) -> dict:
    """一份覆盖面尽量宽的配置：账号、overlay、模块、分区都走到。"""
    return {
        "board": "golden-board",
        "product": "default",
        "variant": "release",
        "platform": platform,
        "soc": "golden-soc",
        "architecture": {
            "userspace": "aarch64", "kernel": "arm64", "bootloader": "arm64",
        },
        "kernel": {"device_tree": {"directory": "", "name": "golden"}},
        "rootfs": {
            "url": "https://example.com/ubuntu-base.tar.gz",
            "sha256": "a" * 64,
            "packages": ["systemd", "udev"],
            "install_recommends": False,
            "custom_packages": [],
            "hostname": "golden",
            # 额外 APT 源：ubuntu-base 没有 CA 证书，走 HTTPS 源必须先在
            # chroot 内装 ca-certificates。这条路径此前只有一个平台实现，
            # 其余平台声明了该字段却静默无操作 —— golden 让这种差异可见。
            "extra_apt_sources": [{
                "name": "golden-ppa",
                "key": {"url": "https://example.com/key.asc", "sha256": "b" * 64},
                "source": "deb [arch=arm64] https://example.com/ubuntu noble main",
            }],
            "root_password": "golden",
            "groups": ["sudo"],
            "users": {"dev": {"password": "dev", "shell": "/bin/bash"}},
            "default_user": "dev",
        },
        "storage": {"type": "emmc", "size": "8G"},
        "partitions": {
            "format": "gpt",
            "entries": [
                {"name": "boot", "type": "ext4", "offset": "0x8000",
                 "size": "0x20000"},
                {"name": "rootfs", "type": "ext4", "offset": "0x28000",
                 "size": "remaining", "image_size": "2G"},
            ],
        },
        "recovery": {"enabled": False},
        "amp": {"enabled": False},
    }


class _Recorder:
    """记录 docker 调用，并把易变路径归一化成占位符。"""

    def __init__(self, work_root: Path, project_root: Path):
        self.calls: list[str] = []
        self._subs = [
            (str(project_root), "<PROJECT>"),
            (str(work_root), "<WORK>"),
        ]

    def _norm(self, text: str) -> str:
        for raw, token in self._subs:
            text = text.replace(raw, token)
        # 每次构建新建的临时目录、内容哈希、时间戳都不该进 golden
        text = re.sub(r"/[^ ]*flange-rootfs-[A-Za-z0-9_]+", "<TMP>", text)
        text = re.sub(r"<PROJECT>/.build/work/[^ ]+/rootfs/run-[^ /]+", "<TMP>", text)
        text = re.sub(r"base-[0-9a-f]+", "base-<HASH>", text)
        text = re.sub(r"(base-<HASH>\.tar\.zst)\.[^ /]+\.tmp", r"\1.<TEMP>.tmp", text)
        return text

    def probe(self, name):
        """把「读文件做校验」的方法换成留痕的桩。

        这个 golden 锁的是命令序列，不是文件内容；但校验步骤**是否被调用**
        本身是序列的一部分（合并编排时漏掉一个 verify 是真实风险），所以记录
        调用而不是整个跳过。
        """
        def call(*args, **kwargs):
            self.calls.append(f"verify: {name}")
        return call

    def _record(self, name):
        def call(command, **kwargs):
            rendered = " ".join(str(part) for part in command)
            entry = self._norm(f"{name}: {rendered}")
            if kwargs.get("input"):
                entry += f"  <stdin:{self._norm(str(kwargs['input'])).strip()}>"
            self.calls.append(entry)
            if command and str(command[0]) == "tar" and "-cf" in command:
                Path(command[command.index("-cf") + 1]).write_bytes(b"snapshot")
            # tar 解压是 mock 的，但后续步骤（locale / hostname / fstab）会往
            # 解出来的树里写真实文件；建一个最小骨架让序列能跑完。
            if command and str(command[0]) == "tar" and "-C" in command:
                dest = Path(str(command[command.index("-C") + 1]))
                for sub in ("etc", "etc/default", "etc/ssh/sshd_config.d",
                            "usr/bin", "usr/sbin", "lib/modules"):
                    (dest / sub).mkdir(parents=True, exist_ok=True)
            result = MagicMock()
            # du -sm / du -sb 的返回值参与容量门禁计算
            result.stdout = "512\t<dir>" if "-sm" in command else "512000\t<dir>"
            return result
        return call


def _run_compile(platform: str, tmp_path: Path) -> list[str]:
    tmp_path = tmp_path.resolve()
    """跑一次 compile()，返回归一化后的命令序列。"""
    project_root = tmp_path / "project"
    (project_root / "components/rootfs/overlay").mkdir(parents=True)
    (project_root / "components/rootfs/overlay/hosts").write_text("127.0.0.1\n")

    # 预置上游产物，让序列覆盖 deb 安装与内核模块拷贝两条路径 —— 它们正是
    # target_dir 推导（cwd 相对 vs cache 锚点）的分歧所在。
    target = project_root / ".build/target/golden-board/default/release"
    (target / "app").mkdir(parents=True)
    (target / "app/golden_1.0_arm64.deb").write_bytes(b"deb")
    (target / "kernel/modules/lib/modules/6.1.0").mkdir(parents=True)

    config = _config(platform, project_root)
    config["rootfs"]["custom_packages"] = ["golden"]
    builder_cls = _load(PLATFORMS[platform])

    docker = MagicMock()
    source = MagicMock()
    source.ensure_rootfs_tarball.return_value = Path("<TARBALL>")
    source.ensure_download.side_effect = lambda namespace, *args: Path("<TARBALL>" if namespace == "rootfs" else "<APTKEY>")

    builder = builder_cls(docker, source)
    cache = MagicMock()
    cache.target_dir = project_root / ".build/target/golden-board/default/release"
    cache.compute_phase_hash.return_value = "deadbeef"
    builder.cache = cache
    builder.context = component_context(project_root, {"board": "golden-board"}, target_dir=target)
    builder.output = None
    builder.app_report = MagicMock()
    builder.app_report.validate.return_value = True
    builder.app_report.runtime_debs_for.return_value = tuple((target / "app").glob("*.deb"))

    recorder = _Recorder(tmp_path, project_root)
    docker.run.side_effect = recorder._record("run")
    docker.run_privileged.side_effect = recorder._record("priv")
    # chroot 是 mock 的，/etc/shadow 等不会真的生成；把内容校验换成留痕的桩
    for name in ("_verify_root_password", "_verify_root_locked",
                 "_verify_sshd_no_root"):
        if hasattr(builder, name):
            setattr(builder, name, recorder.probe(name))

    previous = os.getcwd()
    os.chdir(project_root)
    try:
        builder.compile(None, config)
    finally:
        os.chdir(previous)
        work = getattr(builder, "_work_dir", None)
        if work and Path(work).exists():
            import shutil

            shutil.rmtree(work, ignore_errors=True)

    # 临时工作目录是每次新建的，统一成占位符后序列才可比
    return [re.sub(r"/[^ ]*/flange-rootfs-[^/ ]+", "<TMP>", c)
            for c in recorder.calls]


@pytest.mark.parametrize("platform", sorted(PLATFORMS))
def test_rootfs构造序列与golden一致(platform: str, tmp_path: Path, request):
    """重构 rootfs 编排后，各平台发出的命令序列必须逐条不变。"""
    GOLDEN_DIR.mkdir(exist_ok=True)
    golden = GOLDEN_DIR / f"rootfs-{platform}.json"

    actual = _run_compile(platform, tmp_path)

    if request.config.getoption("--update-golden", default=False):
        golden.write_text(
            json.dumps(actual, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")
        pytest.skip(f"已更新 golden: {golden.name}")

    assert golden.is_file(), (
        f"缺少 golden：先跑 pytest {__file__} --update-golden 固化现状")
    expected = json.loads(golden.read_text())

    assert actual == expected, (
        f"{platform} 的 rootfs 构造序列变了。若是有意的行为变更，"
        f"连同 golden 一起更新并在提交信息里说明改了哪一步、为什么。")


def test_golden覆盖全部平台():
    """新增平台时必须一并固化它的序列，否则合并编排时它是盲区。"""
    import builder.platforms as platforms_pkg

    available = {
        entry.name
        for entry in Path(platforms_pkg.__file__).parent.iterdir()
        if entry.is_dir() and entry.name != "__pycache__"
        and (entry / "rootfs.py").is_file()
    }

    assert available == set(PLATFORMS), (
        f"这些平台有 rootfs.py 但没进 golden 覆盖: {available - set(PLATFORMS)}")
