"""Amlogic bootloader 构建策略测试。

覆盖：
- configure 阶段把 fragment 复制到 u-boot ``configs/``
- compile 调用顺序：u-boot make → build-fip.sh → aml_encrypt_g12a --bootsd / --bootusb
- collect 返回 fip / usb_bl2 / usb_tpl 三个产物路径
- 命令行参数（fip_board_dir 来自 board config，fip_tool 来自 SoC config）
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
        "repos": {
            "amlogic-boot-fip": {
                "repo": "https://github.com/LibreELEC/amlogic-boot-fip.git",
                "branch": "master",
            },
        },
        "bootloader": {
            "from_repo": "u-boot",
            "defconfig": defconfig
            if defconfig is not None
            else ["khadas-vim3l_defconfig", "flange_fastboot.config"],
            "fip_tool": "aml_encrypt_g12a",
            "fip_family_inc": "g12a.inc",
            "fip_board_dir": "khadas-vim3l",
        },
    }


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


def test_configure_string_defconfig_no_fragment_staging(tmp_path, monkeypatch):
    """单字符串 defconfig 形态向后兼容，不触发 fragment staging 路径。"""
    builder, docker, _, src_dir, _ = _make_builder(tmp_path)
    monkeypatch.chdir(tmp_path)
    cfg = _config(defconfig="khadas-vim3l_defconfig")
    builder.configure(src_dir, cfg)
    make_targets = [c["cmd"][1:] for c in docker.commands
                    if c["cmd"][:1] == ["make"]]
    assert make_targets == [["khadas-vim3l_defconfig"]]


def test_compile_invokes_build_fip_then_aml_encrypt(tmp_path):
    """compile 三段式：u-boot make → build-fip.sh → aml_encrypt_g12a 两次。"""
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

    # 第三段：aml_encrypt_g12a --bootsd（来自 SoC config 的 fip_tool）
    encrypt_tool = str(fip_src / "khadas-vim3l" / "aml_encrypt_g12a")
    bootsd = next(c for c in cmds if c[:1] == [encrypt_tool]
                  and "--bootsd" in c)
    assert bootsd[1] == "--bootsd"
    assert bootsd[2:4] == ["--infile",
                           str(src_dir / "fip" / "khadas-vim3l" / "u-boot.bin")]
    assert bootsd[4] == "--output"
    assert bootsd[5].endswith("u-boot.bin.sd.bin")

    # 第四段：aml_encrypt_g12a --bootusb（派生 USB BL2/TPL）
    bootusb = next(c for c in cmds if c[:1] == [encrypt_tool]
                   and "--bootusb" in c)
    assert bootusb[1] == "--bootusb"
    assert bootusb[5].endswith("u-boot.bin.usb")

    # ensure_extra 通过 from_repo 路由复用命名仓库
    assert source.calls[0][0] == "amlogic-boot-fip"
    assert source.calls[0][1] == {"from_repo": "amlogic-boot-fip"}


def test_compile_missing_fip_board_dir_raises(tmp_path):
    """board config 未声明 fip_board_dir 时，compile 报含字段名的 KeyError。"""
    builder, _, _, src_dir, _ = _make_builder(tmp_path)
    cfg = _config()
    del cfg["bootloader"]["fip_board_dir"]
    with pytest.raises(KeyError, match="fip_board_dir"):
        builder.compile(src_dir, cfg)


def test_compile_uses_custom_fip_tool(tmp_path):
    """SoC 层 fip_tool 被尊重（如未来若有 aml_encrypt_sc2 则用之）。"""
    builder, docker, _, src_dir, fip_src = _make_builder(tmp_path)
    cfg = _config()
    cfg["bootloader"]["fip_tool"] = "aml_encrypt_custom"
    (fip_src / "khadas-vim3l" / "aml_encrypt_custom").write_text("")
    builder.compile(src_dir, cfg)

    cmds = [c["cmd"] for c in docker.commands]
    custom = str(fip_src / "khadas-vim3l" / "aml_encrypt_custom")
    assert any(c[:1] == [custom] and "--bootsd" in c for c in cmds)


def test_collect_returns_three_artifacts(tmp_path):
    """collect 返回 fip / usb_bl2 / usb_tpl 三个 key，路径相对 fip_image。"""
    builder, _, _, src_dir, _ = _make_builder(tmp_path)
    cfg = _config()
    builder.compile(src_dir, cfg)

    artifacts = builder.collect(src_dir, cfg)
    assert set(artifacts.keys()) == {"fip", "usb_bl2", "usb_tpl"}
    out = src_dir / "fip" / "khadas-vim3l"
    assert artifacts["fip"] == out / "u-boot.bin.sd.bin"
    assert artifacts["usb_bl2"] == out / "u-boot.bin.usb.bl2"
    assert artifacts["usb_tpl"] == out / "u-boot.bin.usb.tpl"
