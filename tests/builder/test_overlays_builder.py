"""device-tree-overlay 组件构建测试 — mock docker / source。"""

from __future__ import annotations

from pathlib import Path

import pytest

from builder.overlays import OverlaysBuilder


class FakeDocker:
    """记录调用，避免实际执行 cpp / dtc。"""

    def __init__(self):
        self.calls: list[list[str]] = []

    def run(self, cmd: list, **kwargs):
        # 模拟 dtc 命令产出空文件，让后续 collect 路径通顺
        self.calls.append([str(c) for c in cmd])
        if cmd and str(cmd[0]) == "dtc":
            # -o <out> 在 cmd 中
            try:
                idx = cmd.index("-o")
                Path(str(cmd[idx + 1])).write_bytes(b"FAKE_DTBO")
            except (ValueError, IndexError):
                pass


class FakeSource:
    """返回提前准备好的 src_dir。"""

    def __init__(self, kernel_src: Path, overlay_src: Path):
        self._map = {"kernel": kernel_src, "device-tree-overlay": overlay_src}

    def ensure(self, component: str, config: dict) -> Path:
        return self._map[component]


def _make_overlay_repo(root: Path, vendor: str, stems: list[str], *,
                        ext: str = ".dts") -> Path:
    """构造一份最小的 radxa-overlays 仓库结构。

    ext: 源文件后缀，默认 ".dts"（rockchip 用），可传 ".dtso"（allwinner 用）
    """
    overlays_dir = root / "arch" / "arm64" / "boot" / "dts" / vendor / "overlays"
    overlays_dir.mkdir(parents=True)
    for stem in stems:
        (overlays_dir / f"{stem}{ext}").write_text(f"// {stem}\n")
    return root


def _make_kernel_src(root: Path) -> Path:
    """构造内核源码 include/ 占位（cpp 用作 -I）。"""
    (root / "include").mkdir(parents=True)
    return root


def _cfg(*, vendor: str | None, vendor_overlays: list[str],
         board: str = "test",
         board_overlays: list[str] | None = None) -> dict:
    cfg: dict = {
        "board": board,
        "boot": {
            "vendor_overlays": vendor_overlays,
            "board_overlays": board_overlays or [],
        },
        "device-tree-overlay": {"repo": "x", "branch": "y"},
    }
    if vendor is not None:
        cfg["vendor"] = vendor
    return cfg


def _make_board_overlays_dir(root: Path, stems: list[str], *,
                              ext: str = ".dts") -> Path:
    """构造仓库内板私有 overlay 目录 components/board/<board>/overlays/。"""
    overlays_dir = root / "overlays"
    overlays_dir.mkdir(parents=True)
    for stem in stems:
        (overlays_dir / f"{stem}{ext}").write_text(f"// {stem}\n")
    return overlays_dir


def _builder(tmp_path: Path, *, kernel_src: Path, overlay_src: Path) -> OverlaysBuilder:
    docker = FakeDocker()
    source = FakeSource(kernel_src=kernel_src, overlay_src=overlay_src)
    b = OverlaysBuilder(docker, source)
    return b


def test_empty_vendor_overlays_short_circuits(tmp_path):
    overlay_src = _make_overlay_repo(tmp_path / "ov", "rockchip", [])
    kernel_src = _make_kernel_src(tmp_path / "k")
    b = _builder(tmp_path, kernel_src=kernel_src, overlay_src=overlay_src)

    cfg = _cfg(vendor="rockchip", vendor_overlays=[])
    out = b.build(cfg)

    assert b.docker.calls == []        # 无任何 cpp / dtc
    assert out["overlays"].exists()    # 工作目录已建好
    assert list(out["overlays"].iterdir()) == []   # 但为空


def test_compile_invokes_cpp_then_dtc_with_correct_includes(tmp_path):
    overlay_src = _make_overlay_repo(
        tmp_path / "ov", "rockchip", ["rk3568-i2c1"])
    kernel_src = _make_kernel_src(tmp_path / "k")
    b = _builder(tmp_path, kernel_src=kernel_src, overlay_src=overlay_src)

    cfg = _cfg(vendor="rockchip", vendor_overlays=["rk3568-i2c1.dtbo"])
    out = b.build(cfg)

    assert len(b.docker.calls) == 2
    cpp_cmd, dtc_cmd = b.docker.calls

    assert cpp_cmd[0] == "cpp"
    assert "-nostdinc" in cpp_cmd
    assert "-undef" in cpp_cmd
    assert "-x" in cpp_cmd and "assembler-with-cpp" in cpp_cmd
    # 两个 -I 都在
    i_idxs = [i for i, x in enumerate(cpp_cmd) if x == "-I"]
    i_paths = [cpp_cmd[i + 1] for i in i_idxs]
    assert str(kernel_src / "include") in i_paths
    assert (
        str(overlay_src / "arch/arm64/boot/dts/rockchip/overlays")
        in i_paths
    )
    # dts 输入与 .tmp 输出
    assert any(p.endswith("rk3568-i2c1.dts") for p in cpp_cmd)
    assert any(p.endswith("rk3568-i2c1.dtbo.tmp") for p in cpp_cmd)

    assert dtc_cmd[0] == "dtc"
    assert "-@" in dtc_cmd                 # overlay 必备
    assert "-I" in dtc_cmd and "dts" in dtc_cmd
    assert "-O" in dtc_cmd and "dtb" in dtc_cmd
    # 产物文件就是 collect 返回目录里的
    out_idx = dtc_cmd.index("-o")
    out_path = Path(dtc_cmd[out_idx + 1])
    assert out_path.parent == out["overlays"]
    assert out_path.name == "rk3568-i2c1.dtbo"
    assert out_path.read_bytes() == b"FAKE_DTBO"


def test_compile_unknown_stem_lists_candidates(tmp_path):
    overlay_src = _make_overlay_repo(
        tmp_path / "ov", "rockchip",
        ["rk3568-i2c1", "rk3568-i2c2", "radxa-zero3-x"],
    )
    kernel_src = _make_kernel_src(tmp_path / "k")
    b = _builder(tmp_path, kernel_src=kernel_src, overlay_src=overlay_src)

    cfg = _cfg(vendor="rockchip", vendor_overlays=["nonexistent.dtbo"])

    with pytest.raises(FileNotFoundError) as excinfo:
        b.build(cfg)
    msg = str(excinfo.value)
    assert "nonexistent" in msg
    assert "rk3568-i2c1" in msg
    assert "共 3 个" in msg


def test_compile_missing_vendor_raises(tmp_path):
    overlay_src = _make_overlay_repo(
        tmp_path / "ov", "rockchip", ["rk3568-i2c1"])
    kernel_src = _make_kernel_src(tmp_path / "k")
    b = _builder(tmp_path, kernel_src=kernel_src, overlay_src=overlay_src)

    cfg = _cfg(vendor=None, vendor_overlays=["rk3568-i2c1.dtbo"])
    with pytest.raises(ValueError, match="vendor 字段"):
        b.build(cfg)


def test_compile_missing_vendor_subdir_raises(tmp_path):
    # 仓库只有 rockchip，但 config vendor=allwinner
    overlay_src = _make_overlay_repo(
        tmp_path / "ov", "rockchip", ["rk3568-i2c1"])
    kernel_src = _make_kernel_src(tmp_path / "k")
    b = _builder(tmp_path, kernel_src=kernel_src, overlay_src=overlay_src)

    cfg = _cfg(vendor="allwinner", vendor_overlays=["x.dtbo"])
    with pytest.raises(FileNotFoundError, match="vendor 子目录"):
        b.build(cfg)


def test_compile_accepts_dtso_extension(tmp_path):
    """allwinner 子目录用 .dtso 后缀（kernel >= 6.2 新格式），需要支持。"""
    overlay_src = _make_overlay_repo(
        tmp_path / "ov", "allwinner",
        ["sun60iw2p1-uart2", "cubie-a7z-reroute-audio-from-hdmi-to-typec-dp"],
        ext=".dtso",
    )
    kernel_src = _make_kernel_src(tmp_path / "k")
    b = _builder(tmp_path, kernel_src=kernel_src, overlay_src=overlay_src)

    cfg = _cfg(
        vendor="allwinner",
        vendor_overlays=[
            "sun60iw2p1-uart2.dtbo",
            "cubie-a7z-reroute-audio-from-hdmi-to-typec-dp.dtbo",
        ],
    )
    out = b.build(cfg)

    dtbos = sorted(p.name for p in out["overlays"].glob("*.dtbo"))
    assert dtbos == [
        "cubie-a7z-reroute-audio-from-hdmi-to-typec-dp.dtbo",
        "sun60iw2p1-uart2.dtbo",
    ]
    # cpp 输入应是 .dtso 文件
    cpp_calls = [c for c in b.docker.calls if c[0] == "cpp"]
    for call in cpp_calls:
        assert any(p.endswith(".dtso") for p in call)


# --- board_overlays（板私有源）---


def test_compile_board_overlays_from_components_dir(tmp_path, monkeypatch):
    """板私有 overlay 从 components/board/<board>/overlays/ 取 dts，与
    vendor 共用 cpp+dtc 流水线 + 同一产物目录。"""
    # 构造仓库根：components/board/myboard/overlays/foo.dts
    repo_root = tmp_path / "repo"
    board_dir = repo_root / "components" / "board" / "myboard"
    overlays_dir = _make_board_overlays_dir(board_dir, ["foo"])
    monkeypatch.chdir(repo_root)

    # vendor 仓库可以为空；只验证 board 路径
    overlay_src = _make_overlay_repo(tmp_path / "ov", "rockchip", [])
    kernel_src = _make_kernel_src(tmp_path / "k")
    b = _builder(tmp_path, kernel_src=kernel_src, overlay_src=overlay_src)

    cfg = _cfg(
        vendor="rockchip",
        vendor_overlays=[],
        board="myboard",
        board_overlays=["foo.dtbo"],
    )
    out = b.build(cfg)

    # 应该有 cpp + dtc 各一次
    assert len(b.docker.calls) == 2
    cpp_cmd, dtc_cmd = b.docker.calls
    assert cpp_cmd[0] == "cpp"
    # cpp -I 用了 board overlays_dir
    i_paths = [cpp_cmd[i + 1] for i, x in enumerate(cpp_cmd) if x == "-I"]
    assert str(overlays_dir) in i_paths
    # 输入 dts 是 board 私有目录里的
    assert any(p.endswith("foo.dts") for p in cpp_cmd)
    assert any(str(overlays_dir) in p for p in cpp_cmd)
    # dtbo 写到产物目录
    dtbos = sorted(p.name for p in out["overlays"].glob("*.dtbo"))
    assert dtbos == ["foo.dtbo"]


def test_compile_board_and_vendor_overlays_share_output_dir(tmp_path,
                                                              monkeypatch):
    """vendor 与 board 各自一个 overlay，产物落同一目录。"""
    repo_root = tmp_path / "repo"
    board_dir = repo_root / "components" / "board" / "myboard"
    _make_board_overlays_dir(board_dir, ["board-only"])
    monkeypatch.chdir(repo_root)

    overlay_src = _make_overlay_repo(
        tmp_path / "ov", "rockchip", ["vendor-only"])
    kernel_src = _make_kernel_src(tmp_path / "k")
    b = _builder(tmp_path, kernel_src=kernel_src, overlay_src=overlay_src)

    cfg = _cfg(
        vendor="rockchip",
        vendor_overlays=["vendor-only.dtbo"],
        board="myboard",
        board_overlays=["board-only.dtbo"],
    )
    out = b.build(cfg)

    dtbos = sorted(p.name for p in out["overlays"].glob("*.dtbo"))
    assert dtbos == ["board-only.dtbo", "vendor-only.dtbo"]
    # cpp + dtc 各两次（vendor + board 各一对）
    cpp_calls = [c for c in b.docker.calls if c[0] == "cpp"]
    assert len(cpp_calls) == 2


def test_compile_board_overlays_short_circuits_when_empty(tmp_path,
                                                           monkeypatch):
    """vendor 与 board 都空时 short-circuit，docker 不被调用。"""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    monkeypatch.chdir(repo_root)
    overlay_src = _make_overlay_repo(tmp_path / "ov", "rockchip", [])
    kernel_src = _make_kernel_src(tmp_path / "k")
    b = _builder(tmp_path, kernel_src=kernel_src, overlay_src=overlay_src)

    cfg = _cfg(vendor="rockchip", vendor_overlays=[],
                board="myboard", board_overlays=[])
    b.build(cfg)
    assert b.docker.calls == []


def test_compile_board_overlays_missing_dir_raises(tmp_path, monkeypatch):
    """声明了 board_overlays 但目录不存在 → FileNotFoundError。"""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    monkeypatch.chdir(repo_root)

    overlay_src = _make_overlay_repo(tmp_path / "ov", "rockchip", [])
    kernel_src = _make_kernel_src(tmp_path / "k")
    b = _builder(tmp_path, kernel_src=kernel_src, overlay_src=overlay_src)

    cfg = _cfg(vendor="rockchip", vendor_overlays=[],
                board="myboard", board_overlays=["x.dtbo"])
    with pytest.raises(FileNotFoundError, match="board overlay 源目录不存在"):
        b.build(cfg)


def test_compile_board_overlays_missing_stem_lists_candidates(tmp_path,
                                                               monkeypatch):
    repo_root = tmp_path / "repo"
    board_dir = repo_root / "components" / "board" / "myboard"
    _make_board_overlays_dir(board_dir, ["alpha", "beta"])
    monkeypatch.chdir(repo_root)

    overlay_src = _make_overlay_repo(tmp_path / "ov", "rockchip", [])
    kernel_src = _make_kernel_src(tmp_path / "k")
    b = _builder(tmp_path, kernel_src=kernel_src, overlay_src=overlay_src)

    cfg = _cfg(vendor="rockchip", vendor_overlays=[],
                board="myboard", board_overlays=["nonexistent.dtbo"])
    with pytest.raises(FileNotFoundError) as excinfo:
        b.build(cfg)
    msg = str(excinfo.value)
    assert "nonexistent" in msg
    assert "alpha" in msg
    assert "beta" in msg


def test_compile_board_overlays_accepts_dtso_extension(tmp_path, monkeypatch):
    """与 vendor 同样支持 .dtso 后缀。"""
    repo_root = tmp_path / "repo"
    board_dir = repo_root / "components" / "board" / "myboard"
    _make_board_overlays_dir(board_dir, ["foo"], ext=".dtso")
    monkeypatch.chdir(repo_root)

    overlay_src = _make_overlay_repo(tmp_path / "ov", "allwinner", [])
    kernel_src = _make_kernel_src(tmp_path / "k")
    b = _builder(tmp_path, kernel_src=kernel_src, overlay_src=overlay_src)

    cfg = _cfg(vendor="allwinner", vendor_overlays=[],
                board="myboard", board_overlays=["foo.dtbo"])
    out = b.build(cfg)
    assert (out["overlays"] / "foo.dtbo").exists()


def test_collect_outputs_to_overlays_dir(tmp_path):
    overlay_src = _make_overlay_repo(
        tmp_path / "ov", "rockchip", ["a", "b"])
    kernel_src = _make_kernel_src(tmp_path / "k")
    b = _builder(tmp_path, kernel_src=kernel_src, overlay_src=overlay_src)

    cfg = _cfg(vendor="rockchip", vendor_overlays=["a.dtbo", "b.dtbo"])
    out = b.build(cfg)

    # FakeDocker 只为 dtc 调用写产物，所以只剩 .dtbo（实际 cpp 也会写 .tmp，
    # 但本测试不考察 .tmp 的存在性，只考察最终 .dtbo 都生成在 overlays/ 下）
    dtbos = sorted(p.name for p in out["overlays"].glob("*.dtbo"))
    assert dtbos == ["a.dtbo", "b.dtbo"]
