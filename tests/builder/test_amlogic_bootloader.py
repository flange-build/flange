"""Amlogic bootloader 构建策略测试。

覆盖：
- configure 阶段把 fragment 复制到 u-boot ``configs/``
- compile 调用顺序：u-boot make → build-fip.sh
- collect 返回 fip / sd / usb_bl2 / usb_tpl 四个产物路径
- 命令行参数（fip_board_dir 来自 board config）
"""

from __future__ import annotations

from pathlib import Path

import pytest

from builder.platforms.amlogic.bootloader import AmlogicBootloaderBuilder


class FakeDocker:
    """记录每次 docker.run 调用的命令与 cwd。"""

    def __init__(self):
        self.commands: list[dict] = []

    def run(self, cmd: list, **kwargs):
        self.commands.append({"cmd": [str(c) for c in cmd],
                              "cwd": kwargs.get("cwd")})


class FakeSource:
    """ensure_extra 直接返回固定路径。"""

    def __init__(self, fip_src: Path):
        self.fip_src = fip_src
        self.calls: list[tuple] = []

    def ensure_extra(self, name: str, cfg: dict, config=None):
        self.calls.append((name, cfg, config))
        return self.fip_src


def _make_builder(tmp_path: Path) -> tuple:
    """构造 builder + fake docker/source + 假 u-boot 源码树 + 假 fip 源码树。"""
    src_dir = tmp_path / "u-boot"
    src_dir.mkdir()
    (src_dir / "configs").mkdir()
    fip_src = tmp_path / "amlogic-boot-fip"
    (fip_src / "khadas-vim3l").mkdir(parents=True)
    (fip_src / "build-fip.sh").write_text("#!/bin/bash\n")

    docker = FakeDocker()
    source = FakeSource(fip_src)
    builder = AmlogicBootloaderBuilder(docker=docker, source=source)
    # 屏蔽 base.make —— 测试只关心命令构造与 collect 路径，不实际跑 make
    builder.make = lambda src, targets, **kwargs: docker.commands.append(
        {"cmd": ["make"] + list(targets), "cwd": str(src)})
    return builder, docker, source, src_dir, fip_src


def _config(*, fragment_dir: Path | None = None,
            defconfig=None, board="khadas-vim3l") -> dict:
    """构造典型 amlogic 合并配置。fragment_dir 用于注入 components/ 路径覆盖。"""
    return {
        "platform": "amlogic",
        "soc": "s905d3",
        "board": board,
        "architecture": {
            "userspace": "aarch64", "kernel": "arm64", "bootloader": "arm",
        },
        "sources": {
            "u-boot": {"url": "https://github.com/u-boot/u-boot.git"},
            "amlogic-boot-fip": {
                "url": "https://github.com/LibreELEC/amlogic-boot-fip.git",
                "branch": "master",
            },
        },
        "bootloader": {
            "source": {"name": "u-boot"},
            "defconfig": defconfig
            if defconfig is not None
            else ["khadas-vim3l_defconfig", "flange_fastboot.config"],
            "fip_tool": "aml_encrypt_g12a",
            "fip_board_dir": "khadas-vim3l",
        },
    }


def test_arch_is_arm_not_arm64():
    """u-boot 把 ARM32/ARM64 板都放在 arch/arm/，ARCH 必须传 ``arm`` ——
    误传 ``arm64`` 会让 u-boot Makefile 找不到 arch/arm64/include/asm/arch-...
    目录，create_symlink 阶段 ln 失败。kernel 才用 ARCH=arm64。"""
    from builder.platforms.amlogic.bootloader import AmlogicBootloaderBuilder
    assert AmlogicBootloaderBuilder.ARCH == "arm"
    # CROSS 继承 base ComponentBuilder 全平台默认 gcc-10（见 builder/base.py）
    assert AmlogicBootloaderBuilder.CROSS == "/opt/aarch64-gcc10/bin/aarch64-linux-"


def test_configure_stages_fragment_into_configs(tmp_path, monkeypatch):
    """configure 把 fragment 从 components/.../patches/bootloader/ 复制到
    u-boot ``configs/``，并按序逐个 make defconfig 列表。"""
    builder, docker, _, src_dir, _ = _make_builder(tmp_path)

    # 模拟仓库内 fragment 文件位置；ProjectSpec §9 路径走 COMPONENTS_ROOT
    # 锚点，测试通过 monkeypatch 把锚点改到临时目录。
    fragment_root = tmp_path / "repo"
    components_root = fragment_root / "components"
    fragment_dir = (components_root
                    / "platform/amlogic/s905d3/patches/bootloader")
    fragment_dir.mkdir(parents=True)
    fragment_content = "CONFIG_USB_FUNCTION_FASTBOOT=y\n"
    (fragment_dir / "flange_fastboot.config").write_text(fragment_content)

    monkeypatch.setattr(
        "builder.platforms.amlogic.bootloader.COMPONENTS_ROOT",
        components_root,
    )
    builder.configure(src_dir, _config())

    staged = src_dir / "configs" / "flange_fastboot.config"
    assert staged.is_file()
    assert staged.read_text() == fragment_content

    # defconfig list 顺序：先 base，再 fragment
    make_targets = [c["cmd"][1:] for c in docker.commands
                    if c["cmd"][:1] == ["make"]]
    assert make_targets == [["khadas-vim3l_defconfig"],
                            ["flange_fastboot.config"]]


def test_configure_missing_fragment_raises(tmp_path, monkeypatch):
    """fragment 在三个搜索目录都找不到时，应 fail-fast 报 FileNotFoundError。"""
    builder, _, _, src_dir, _ = _make_builder(tmp_path)
    components_root = tmp_path / "repo-empty" / "components"
    components_root.mkdir(parents=True)
    monkeypatch.setattr(
        "builder.platforms.amlogic.bootloader.COMPONENTS_ROOT",
        components_root,
    )
    with pytest.raises(FileNotFoundError, match="flange_fastboot.config"):
        builder.configure(src_dir, _config())


def test_configure_single_defconfig_no_fragment_staging(tmp_path, monkeypatch):
    """单元素 defconfig 数组不触发 fragment staging 路径。"""
    builder, docker, _, src_dir, _ = _make_builder(tmp_path)
    monkeypatch.chdir(tmp_path)
    cfg = _config(defconfig=["khadas-vim3l_defconfig"])
    builder.configure(src_dir, cfg)
    make_targets = [c["cmd"][1:] for c in docker.commands
                    if c["cmd"][:1] == ["make"]]
    assert make_targets == [["khadas-vim3l_defconfig"]]


def test_configure_applies_canonical_kconfig_after_defconfig(tmp_path):
    builder, docker, _, src_dir, _ = _make_builder(tmp_path)
    cfg = _config(defconfig=["khadas-vim3l_defconfig"])
    cfg["bootloader"]["config"] = {
        "CONFIG_AMP": "y",
        "CONFIG_UNUSED": "n",
    }

    builder.configure(src_dir, cfg)

    assert [command["cmd"] for command in docker.commands] == [
        ["make", "khadas-vim3l_defconfig"],
        [
            "sh", "-c",
            "printf '%s' 'CONFIG_AMP=y\n# CONFIG_UNUSED is not set\n' >> .config",
        ],
        ["make", "olddefconfig"],
    ]


def test_compile_invokes_build_fip_once(tmp_path):
    """build-fip.sh 的 --bootmk 已生成四件产物，不再重复调用加密工具。"""
    builder, docker, source, src_dir, fip_src = _make_builder(tmp_path)
    cfg = _config()

    builder.compile(src_dir, cfg)

    cmds = [c["cmd"] for c in docker.commands]

    # 第一段：u-boot make（无 target）
    assert cmds[0] == ["make"]

    # 第二段：build-fip.sh
    build_fip = next(c for c in cmds if any("build-fip.sh" in x for x in c))
    assert build_fip[:2] == ["bash", str(fip_src / "build-fip.sh")]
    assert build_fip[2] == "khadas-vim3l"  # board_dir 来自 board config
    assert build_fip[3] == str(src_dir / "u-boot.bin")
    assert build_fip[4] == str(src_dir / "fip" / "khadas-vim3l")

    assert len(cmds) == 2

    # ensure_extra 通过 canonical source 引用复用命名仓库
    assert source.calls[0][0] == "amlogic-boot-fip"
    assert source.calls[0][1] == {
        "source": {"name": "amlogic-boot-fip"},
    }


def test_compile_missing_fip_board_dir_raises(tmp_path):
    """board config 未声明 fip_board_dir 时，compile 报含字段名的 KeyError。"""
    builder, _, _, src_dir, _ = _make_builder(tmp_path)
    cfg = _config()
    del cfg["bootloader"]["fip_board_dir"]
    with pytest.raises(KeyError, match="fip_board_dir"):
        builder.compile(src_dir, cfg)


def test_collect_returns_four_artifacts(tmp_path):
    """collect 返回 fip / sd / usb_bl2 / usb_tpl 四个 key：fip 是裸 FIP
    （build-fip.sh 直接产出，pyamlboot 推 MaskROM 用），sd 是 SD/eMMC dd
    格式（build-fip.sh 直接产出，fastboot flash bootloader 用），
    usb_bl2/usb_tpl 是备用的旧式两段 USB 上传产物。"""
    builder, _, _, src_dir, _ = _make_builder(tmp_path)
    cfg = _config()
    builder.compile(src_dir, cfg)

    artifacts = builder.collect(src_dir, cfg)
    assert set(artifacts.keys()) == {"fip", "sd", "usb_bl2", "usb_tpl"}
    out = src_dir / "fip" / "khadas-vim3l"
    assert artifacts["fip"] == out / "u-boot.bin"
    assert artifacts["sd"] == out / "u-boot.bin.sd.bin"
    assert artifacts["usb_bl2"] == out / "u-boot.bin.usb.bl2"
    assert artifacts["usb_tpl"] == out / "u-boot.bin.usb.tpl"
