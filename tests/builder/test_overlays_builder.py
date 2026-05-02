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


def _make_overlay_repo(root: Path, vendor: str, stems: list[str]) -> Path:
    """构造一份最小的 radxa-overlays 仓库结构。"""
    overlays_dir = root / "arch" / "arm64" / "boot" / "dts" / vendor / "overlays"
    overlays_dir.mkdir(parents=True)
    for stem in stems:
        (overlays_dir / f"{stem}.dts").write_text(f"// {stem}\n")
    return root


def _make_kernel_src(root: Path) -> Path:
    """构造内核源码 include/ 占位（cpp 用作 -I）。"""
    (root / "include").mkdir(parents=True)
    return root


def _cfg(*, vendor: str | None, vendor_overlays: list[str]) -> dict:
    cfg: dict = {
        "board": "test",
        "boot": {"vendor_overlays": vendor_overlays},
        "device-tree-overlay": {"repo": "x", "branch": "y"},
    }
    if vendor is not None:
        cfg["vendor"] = vendor
    return cfg


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
