"""recovery 并入 RootfsBuilder 之后的行为契约。

**为什么需要它**：合并前 `RecoveryBuilder` 与 `RootfsBuilder` 有 13 个同名
方法，逐方法对比后 10 个只差参数名与 status 文案，剩下 3 个是**抄件漂移**：

  - 硬编码 `qemu-aarch64-static` —— armhf 板的 recovery 会拿错 emulator
  - `_partition_size_mb` 自己算 `int(size,0)*512`，忽略 `image_size`
  - 没有容量门禁 —— 装不下时报的是 mke2fs 的晦涩错误

抄件漂移的代价不是重复，而是**基类新增的能力接不上抄件**。这组测试锁住的
就是"两者共用同一份编排"这件事本身：任何一条失败，都说明 recovery 又开始
走自己的路了。
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from builder.recovery import RecoveryBuilder, build_recovery_config
from builder.rootfs import RootfsBuilder


def _builder(tmp_path: Path) -> RecoveryBuilder:
    builder = RecoveryBuilder(MagicMock(), MagicMock())
    cache = MagicMock()
    cache.target_dir = tmp_path / "target"
    builder.cache = cache
    builder.output = None
    return builder


# ---------------------------------------------------------------------------
# 结构：确实是同一份编排
# ---------------------------------------------------------------------------

def test_recovery继承rootfs编排():
    assert issubclass(RecoveryBuilder, RootfsBuilder)


def test_没有重新实现基类编排方法():
    """守住合并本身：任何一个方法被重新覆写，都要有明确理由。

    允许覆写的只有声明位与 recovery 独有的步骤；其余同名方法一旦出现在
    RecoveryBuilder 的 __dict__ 里，就是又抄了一份。
    """
    allowed = {"_selected_debs", "_build_phase2", "_post_customize"}
    overridden = {
        name for name, value in vars(RecoveryBuilder).items()
        if callable(value) and hasattr(RootfsBuilder, name)
    }
    assert overridden <= allowed, (
        f"RecoveryBuilder 重新实现了基类方法 {overridden - allowed}；"
        f"平台差异应走声明位（FSTAB_MOUNTS / OVERLAY_SUBDIR / component）")


@pytest.mark.parametrize("slot,expected", [
    ("component", "recovery"),
    ("OVERLAY_SUBDIR", "recovery-overlay"),
    ("fs_label", "recovery"),
])
def test_声明位取值(slot: str, expected: str):
    assert getattr(RecoveryBuilder, slot) == expected


# ---------------------------------------------------------------------------
# 漂移 1：emulator 按 arch 推导
# ---------------------------------------------------------------------------

def test_emulator按arch推导而不是硬编码aarch64():
    """合并前 recovery 写死 qemu-aarch64-static，armhf 板会拿错 emulator。"""
    builder = RecoveryBuilder(MagicMock(), MagicMock())
    armhf = {"architecture": {"userspace": "armhf"}, "rootfs": {}}
    assert builder._rootfs_emulator(armhf) == "qemu-arm-static"

    aarch64 = {"architecture": {"userspace": "aarch64"}, "rootfs": {}}
    assert builder._rootfs_emulator(aarch64) == "qemu-aarch64-static"


# ---------------------------------------------------------------------------
# 漂移 2：image_size 生效
# ---------------------------------------------------------------------------

def test_recovery分区的image_size生效():
    """合并前 recovery 自己算 int(size,0)*512，声明 image_size 被静默忽略。"""
    builder = RecoveryBuilder(MagicMock(), MagicMock())
    config = {"partitions": {"entries": [
        # 分区 256MB，但只想做 96MB 的镜像（留给首启动扩容）
        {"name": "recovery", "type": "ext4", "size": "0x80000",
         "image_size": "96M"},
    ]}}
    assert builder._partition_size_mb(config, "recovery") == 96


# ---------------------------------------------------------------------------
# 漂移 3：容量门禁
# ---------------------------------------------------------------------------

def test_容量门禁的保留下限随镜像缩放(tmp_path: Path):
    """固定 128MiB 下限对 64MB 的 recovery 分区数学上永远不可能通过。

    这正是 recovery 此前绕开门禁所掩盖的问题 —— 直接照搬会让 recovery
    永远构建失败。
    """
    builder = _builder(tmp_path)
    builder.docker.run.return_value = MagicMock(stdout="24\t/x")

    # 24MB 内容 + 保留(max(20%, min(128, 64//4))=16) = 40MB ≤ 64MB
    builder._ensure_rootfs_fits_image(tmp_path, 64)

    # 大镜像的下限维持 128MB 不变
    builder.docker.run.return_value = MagicMock(stdout="512\t/x")
    builder._ensure_rootfs_fits_image(tmp_path, 2048)


def test_装不下时报的是flange的话而不是mke2fs的话(tmp_path: Path):
    from builder.docker import BuildError

    builder = _builder(tmp_path)
    builder.docker.run.return_value = MagicMock(stdout="60\t/x")
    with pytest.raises(BuildError) as exc:
        builder._ensure_rootfs_fits_image(tmp_path, 64)
    assert "recovery" in str(exc.value), "报错要说清是哪个组件装不下"


# ---------------------------------------------------------------------------
# recovery 独有的行为必须保留
# ---------------------------------------------------------------------------

def test_只装声明的custom_packages(tmp_path: Path):
    """recovery 是几十 MB 的救援系统，全装既放不下也不该依赖无关 App。"""
    builder = _builder(tmp_path)
    config = {"recovery": {"custom_packages": ["recoveryctl", "flangectl"]}}
    assert builder._selected_debs(config) == {"recoveryctl", "flangectl"}
    # normal rootfs 相反：App 与 deb 一对多，按名挑必然漏
    assert RootfsBuilder(MagicMock(), MagicMock())._selected_debs(config) is None


def test_recovery配置json写进镜像固定路径(tmp_path: Path):
    builder = _builder(tmp_path)
    root = tmp_path / "recovery"
    root.mkdir()
    config = {
        "board": "b", "product": "default", "variant": "release",
        "recovery": {"transport": "adb", "protected_partitions": ["uboot"]},
        "partitions": {"entries": [
            {"name": "uboot", "type": "raw", "offset": "0x4000", "size": "0x4000"},
            {"name": "rootfs", "type": "ext4", "offset": "0x8000", "size": "0x100000"},
        ]},
    }
    builder._post_customize(root, config)

    written = json.loads(
        (root / "etc/flange/recovery-config.json").read_text())
    assert written == build_recovery_config(config)
    protection = {p["name"]: p["protected"] for p in written["partitions"]}
    assert protection == {"uboot": True, "rootfs": False}


def test_overlay走独立目录不与normal_rootfs混用(tmp_path: Path, monkeypatch):
    """同一块板要能给救援系统和正常系统不同的配置。"""
    monkeypatch.chdir(tmp_path)
    for relative in ("components/recovery/overlay",
                     "components/platform/rockchip/recovery-overlay",
                     "components/board/b/recovery-overlay",
                     "components/rootfs/overlay",
                     "components/board/b/overlay"):
        path = tmp_path / relative
        path.mkdir(parents=True)
        (path / "marker").write_text("x")

    builder = _builder(tmp_path)
    builder.apply_overlays(tmp_path / "recovery",
                           {"platform": "rockchip", "board": "b"})

    copied = [str(call.args[0]) for call in
              builder.docker.run_privileged.call_args_list]
    joined = " ".join(copied)
    assert "components/recovery/overlay" in joined
    assert "components/platform/rockchip/recovery-overlay" in joined
    assert "components/board/b/recovery-overlay" in joined
    assert "components/rootfs/overlay" not in joined, "不该混用 normal overlay"
    assert "components/board/b/overlay/." not in joined


def test_不配置账号也不装locale():
    """recovery 只走 adb 通道，账号体系与 locale 都没有意义且占空间。"""
    import inspect

    source = inspect.getsource(RecoveryBuilder._build_phase2)
    for skipped in ("_configure_users", "_configure_default_locale",
                    "_install_extra_firmware", "_install_hostname"):
        assert skipped not in source, f"recovery 不应执行 {skipped}"


def test_快照与rootfs分开存放():
    """两者共用 .cache 目录，靠文件名前缀区分 —— 混用会让包集合互相污染。"""
    builder = RecoveryBuilder(MagicMock(), MagicMock())
    cache = MagicMock()
    cache.target_dir = Path("/x/.build/target/b/default/release")
    builder.cache = cache
    builder.docker = MagicMock()
    store = builder._base_snapshot_store()
    assert store.prefix == "recovery-base-"
