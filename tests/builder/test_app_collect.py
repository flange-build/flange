"""builder.app.collect_files 单元测试。

覆盖场景：
- 各子目录约定映射（bin/lib/conf/scripts/systemd/udev/res/include）
- 显式 install 段覆盖
- 混合模式（部分文件约定、部分显式覆盖）
- 架构后缀匹配与剥离（aarch64 ↔ -arm64/-aarch64）
- 不匹配架构的文件被排除
- 文件权限：bin/ 和 scripts/ 为 0o755，其余为 0o644
- 空目录（无可收集文件）
- adbd 集成测试
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pytest

from builder.app import collect_files
from builder.app_spec import (
    AppInfo,
    AppSpec,
    BuildConfig,
    MaintainerInfo,
    SystemdConfig,
)


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def _make_spec(
    name: str = "myapp",
    app_type: str = "exec",
    arch: List[str] = None,
    install: Dict[str, str] = None,
    systemd_unit: str = "",
) -> AppSpec:
    """构造测试用 AppSpec 的辅助函数。"""
    systemd = None
    if systemd_unit:
        systemd = SystemdConfig(unit=systemd_unit, auto_start=False)
    return AppSpec(
        app=AppInfo(
            name=name,
            version="1.0.0",
            description="测试 App",
            type=app_type,
            arch=arch or ["aarch64"],
        ),
        maintainer=MaintainerInfo(name="flange", email="flange@localhost"),
        install=install or {},
        systemd=systemd,
        build=BuildConfig(),
    )


def _touch(path: Path, content: bytes = b"dummy") -> None:
    """创建一个包含占位内容的文件（自动创建父目录）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _result_map(
    files: List[Tuple[Path, str, int]],
) -> Dict[str, Tuple[Path, int]]:
    """将文件列表转换为 install_path → (src_path, mode) 字典，便于断言。"""
    return {install_path: (src, mode) for src, install_path, mode in files}


# ---------------------------------------------------------------------------
# 基础约定映射测试
# ---------------------------------------------------------------------------

class TestConventionMapping:
    """约定目录 → 安装路径映射的基础测试。"""

    def test_bin_convention(self, tmp_path: Path):
        """bin/ 下的普通文件映射到 /usr/bin/，权限 0o755。"""
        _touch(tmp_path / "bin" / "myprog")
        spec = _make_spec(name="myapp")
        files = collect_files(tmp_path, spec, "aarch64")
        m = _result_map(files)
        assert "/usr/bin/myprog" in m
        assert m["/usr/bin/myprog"][1] == 0o755

    def test_lib_convention(self, tmp_path: Path):
        """lib/ 下的文件映射到 /usr/lib/，权限 0o644。"""
        _touch(tmp_path / "lib" / "libfoo.so.1")
        spec = _make_spec(name="myapp")
        files = collect_files(tmp_path, spec, "aarch64")
        m = _result_map(files)
        assert "/usr/lib/libfoo.so.1" in m
        assert m["/usr/lib/libfoo.so.1"][1] == 0o644

    def test_conf_convention(self, tmp_path: Path):
        """conf/ 下的文件映射到 /etc/<name>/，权限 0o644。"""
        _touch(tmp_path / "conf" / "app.conf")
        spec = _make_spec(name="myapp")
        files = collect_files(tmp_path, spec, "aarch64")
        m = _result_map(files)
        assert "/etc/myapp/app.conf" in m
        assert m["/etc/myapp/app.conf"][1] == 0o644

    def test_scripts_convention(self, tmp_path: Path):
        """scripts/ 下的文件映射到 /usr/lib/<name>/，权限 0o755。"""
        _touch(tmp_path / "scripts" / "helper.sh")
        spec = _make_spec(name="myapp")
        files = collect_files(tmp_path, spec, "aarch64")
        m = _result_map(files)
        assert "/usr/lib/myapp/helper.sh" in m
        assert m["/usr/lib/myapp/helper.sh"][1] == 0o755

    def test_systemd_convention(self, tmp_path: Path):
        """systemd/ 下的文件映射到 /lib/systemd/system/，权限 0o644。"""
        _touch(tmp_path / "systemd" / "myapp.service")
        spec = _make_spec(name="myapp")
        files = collect_files(tmp_path, spec, "aarch64")
        m = _result_map(files)
        assert "/lib/systemd/system/myapp.service" in m
        assert m["/lib/systemd/system/myapp.service"][1] == 0o644

    def test_udev_convention(self, tmp_path: Path):
        """udev/ 下的文件映射到 /lib/udev/rules.d/，权限 0o644。"""
        _touch(tmp_path / "udev" / "99-myapp.rules")
        spec = _make_spec(name="myapp")
        files = collect_files(tmp_path, spec, "aarch64")
        m = _result_map(files)
        assert "/lib/udev/rules.d/99-myapp.rules" in m
        assert m["/lib/udev/rules.d/99-myapp.rules"][1] == 0o644

    def test_res_convention(self, tmp_path: Path):
        """res/ 下的文件映射到 /usr/share/<name>/，权限 0o644。"""
        _touch(tmp_path / "res" / "icon.png")
        spec = _make_spec(name="myapp")
        files = collect_files(tmp_path, spec, "aarch64")
        m = _result_map(files)
        assert "/usr/share/myapp/icon.png" in m
        assert m["/usr/share/myapp/icon.png"][1] == 0o644

    def test_include_convention(self, tmp_path: Path):
        """include/ 下的文件映射到 /usr/include/<name>/，权限 0o644。"""
        _touch(tmp_path / "include" / "myapp.h")
        spec = _make_spec(name="myapp")
        files = collect_files(tmp_path, spec, "aarch64")
        m = _result_map(files)
        assert "/usr/include/myapp/myapp.h" in m
        assert m["/usr/include/myapp/myapp.h"][1] == 0o644

    def test_app_name_in_path(self, tmp_path: Path):
        """conf/ 路径模板中 {name} 被替换为实际 app 名称。"""
        _touch(tmp_path / "conf" / "config.yaml")
        spec = _make_spec(name="my-daemon")
        files = collect_files(tmp_path, spec, "aarch64")
        m = _result_map(files)
        assert "/etc/my-daemon/config.yaml" in m
        # 不应包含未替换的模板
        assert all("{name}" not in p for p in m)

    def test_app_yaml_excluded(self, tmp_path: Path):
        """app.yaml 不在任何约定子目录中，不应被收集。"""
        _touch(tmp_path / "app.yaml", b"app:\n  name: x\n")
        _touch(tmp_path / "bin" / "prog")
        spec = _make_spec(name="myapp")
        files = collect_files(tmp_path, spec, "aarch64")
        install_paths = [p for _, p, _ in files]
        assert all("app.yaml" not in p for p in install_paths)

    def test_subdirectory_skipped(self, tmp_path: Path):
        """bin/ 下的子目录不被收集（仅收集文件）。"""
        (tmp_path / "bin" / "subdir").mkdir(parents=True)
        _touch(tmp_path / "bin" / "prog")
        spec = _make_spec(name="myapp")
        files = collect_files(tmp_path, spec, "aarch64")
        install_paths = [p for _, p, _ in files]
        # 只有 prog，没有 subdir 本身
        assert "/usr/bin/prog" in install_paths
        assert "/usr/bin/subdir" not in install_paths


# ---------------------------------------------------------------------------
# 架构后缀匹配测试
# ---------------------------------------------------------------------------

class TestArchSuffix:
    """预编译二进制架构后缀选择与剥离测试。"""

    def test_arm64_suffix_matches_aarch64(self, tmp_path: Path):
        """arch=aarch64 时，-arm64 后缀文件被选中并剥离后缀。"""
        _touch(tmp_path / "bin" / "adbd-arm64")
        spec = _make_spec(name="adbd")
        files = collect_files(tmp_path, spec, "aarch64")
        m = _result_map(files)
        assert "/usr/bin/adbd" in m

    def test_aarch64_suffix_matches_aarch64(self, tmp_path: Path):
        """-aarch64 后缀也能匹配 aarch64 目标架构。"""
        _touch(tmp_path / "bin" / "prog-aarch64")
        spec = _make_spec(name="myapp")
        files = collect_files(tmp_path, spec, "aarch64")
        m = _result_map(files)
        assert "/usr/bin/prog" in m

    def test_armhf_suffix_matches_armhf(self, tmp_path: Path):
        """-armhf 后缀匹配 armhf 目标架构。"""
        _touch(tmp_path / "bin" / "adbd-armhf")
        spec = _make_spec(name="adbd", arch=["armhf"])
        files = collect_files(tmp_path, spec, "armhf")
        m = _result_map(files)
        assert "/usr/bin/adbd" in m

    def test_arm32_suffix_matches_armhf(self, tmp_path: Path):
        """-arm32 后缀也能匹配 armhf 目标架构。"""
        _touch(tmp_path / "bin" / "prog-arm32")
        spec = _make_spec(name="myapp", arch=["armhf"])
        files = collect_files(tmp_path, spec, "armhf")
        m = _result_map(files)
        assert "/usr/bin/prog" in m

    def test_wrong_arch_excluded(self, tmp_path: Path):
        """架构不匹配的文件被排除：arch=aarch64 时 -armhf 文件不应出现。"""
        _touch(tmp_path / "bin" / "adbd-armhf")
        spec = _make_spec(name="adbd")
        files = collect_files(tmp_path, spec, "aarch64")
        m = _result_map(files)
        # 不应有 /usr/bin/adbd（来自 armhf），也不应有带原始文件名的路径
        assert "/usr/bin/adbd" not in m
        assert "/usr/bin/adbd-armhf" not in m

    def test_both_arch_only_target_selected(self, tmp_path: Path):
        """同时存在 -arm64 和 -armhf 时，只选择目标架构对应的文件。"""
        _touch(tmp_path / "bin" / "adbd-arm64")
        _touch(tmp_path / "bin" / "adbd-armhf")
        spec = _make_spec(name="adbd")
        files = collect_files(tmp_path, spec, "aarch64")
        m = _result_map(files)
        # 只选择 arm64（aarch64），结果安装路径为 /usr/bin/adbd
        assert "/usr/bin/adbd" in m
        assert len([p for p in m if "adbd" in p]) == 1
        # 确认来源文件是 arm64 版本
        src = m["/usr/bin/adbd"][0]
        assert src.name == "adbd-arm64"

    def test_plain_file_no_arch_suffix_always_included(self, tmp_path: Path):
        """不带任何架构后缀的普通文件始终被包含，不受架构过滤影响。"""
        _touch(tmp_path / "bin" / "myprog")
        spec = _make_spec(name="myapp")
        files = collect_files(tmp_path, spec, "aarch64")
        m = _result_map(files)
        assert "/usr/bin/myprog" in m

    def test_suffix_stripped_mode_still_755(self, tmp_path: Path):
        """剥离架构后缀后，bin/ 文件权限仍为 0o755。"""
        _touch(tmp_path / "bin" / "prog-arm64")
        spec = _make_spec(name="myapp")
        files = collect_files(tmp_path, spec, "aarch64")
        m = _result_map(files)
        assert "/usr/bin/prog" in m
        assert m["/usr/bin/prog"][1] == 0o755


# ---------------------------------------------------------------------------
# 显式 install 覆盖测试
# ---------------------------------------------------------------------------

class TestInstallOverride:
    """spec.install 显式映射覆盖约定路径的测试。"""

    def test_explicit_install_overrides_convention(self, tmp_path: Path):
        """install 段中声明的文件使用显式路径，而非约定路径。"""
        _touch(tmp_path / "conf" / "app.conf")
        spec = _make_spec(
            name="myapp",
            install={"conf/app.conf": "/etc/app.conf"},  # 显式：不带 /myapp/ 子目录
        )
        files = collect_files(tmp_path, spec, "aarch64")
        m = _result_map(files)
        # 显式路径存在
        assert "/etc/app.conf" in m
        # 约定路径不存在（已被覆盖）
        assert "/etc/myapp/app.conf" not in m

    def test_explicit_install_non_convention_dir(self, tmp_path: Path):
        """install 段可以引用任意路径（不限于约定子目录），文件被正确添加。"""
        _touch(tmp_path / "conf" / "usbdevice.conf")
        spec = _make_spec(
            name="myapp",
            install={"conf/usbdevice.conf": "/etc/usbdevice.conf"},
        )
        files = collect_files(tmp_path, spec, "aarch64")
        m = _result_map(files)
        assert "/etc/usbdevice.conf" in m

    def test_install_mode_inferred_for_bin_dest(self, tmp_path: Path):
        """install 段中安装到 /usr/bin/ 的文件推断权限为 0o755。"""
        _touch(tmp_path / "scripts" / "helper")
        spec = _make_spec(
            name="myapp",
            install={"scripts/helper": "/usr/bin/helper"},
        )
        files = collect_files(tmp_path, spec, "aarch64")
        m = _result_map(files)
        assert "/usr/bin/helper" in m
        assert m["/usr/bin/helper"][1] == 0o755

    def test_install_mode_inferred_for_sbin_dest(self, tmp_path: Path):
        """install 段中安装到 /usr/sbin/ 的文件推断权限为 0o755。"""
        _touch(tmp_path / "scripts" / "usbdevice")
        spec = _make_spec(
            name="myapp",
            install={"scripts/usbdevice": "/usr/sbin/usbdevice"},
        )
        files = collect_files(tmp_path, spec, "aarch64")
        m = _result_map(files)
        assert "/usr/sbin/usbdevice" in m
        assert m["/usr/sbin/usbdevice"][1] == 0o755

    def test_install_mode_inferred_for_etc_dest(self, tmp_path: Path):
        """install 段中安装到 /etc/ 的文件推断权限为 0o644。"""
        _touch(tmp_path / "conf" / "app.conf")
        spec = _make_spec(
            name="myapp",
            install={"conf/app.conf": "/etc/app.conf"},
        )
        files = collect_files(tmp_path, spec, "aarch64")
        m = _result_map(files)
        assert "/etc/app.conf" in m
        assert m["/etc/app.conf"][1] == 0o644


# ---------------------------------------------------------------------------
# 混合模式测试：部分约定 + 部分显式
# ---------------------------------------------------------------------------

class TestMixedMode:
    """install 段与约定映射混合使用时的行为测试。"""

    def test_convention_for_unlisted_files(self, tmp_path: Path):
        """install 段未覆盖的文件仍使用约定路径映射。"""
        _touch(tmp_path / "bin" / "prog-arm64")
        _touch(tmp_path / "conf" / "app.conf")
        # install 段只覆盖 conf，不覆盖 bin
        spec = _make_spec(
            name="myapp",
            install={"conf/app.conf": "/etc/app.conf"},
        )
        files = collect_files(tmp_path, spec, "aarch64")
        m = _result_map(files)
        # bin/prog-arm64 → 约定 + 架构选择
        assert "/usr/bin/prog" in m
        # conf 使用显式路径
        assert "/etc/app.conf" in m
        # conf 约定路径不存在
        assert "/etc/myapp/app.conf" not in m

    def test_install_override_does_not_duplicate(self, tmp_path: Path):
        """install 覆盖后约定路径不重复出现。"""
        _touch(tmp_path / "udev" / "99-foo.rules")
        spec = _make_spec(
            name="myapp",
            install={"udev/99-foo.rules": "/etc/udev/rules.d/99-foo.rules"},
        )
        files = collect_files(tmp_path, spec, "aarch64")
        # 同一文件不应出现两次
        install_paths = [p for _, p, _ in files]
        # 显式路径存在
        assert "/etc/udev/rules.d/99-foo.rules" in install_paths
        # 约定路径不存在
        assert "/lib/udev/rules.d/99-foo.rules" not in install_paths

    def test_multiple_install_overrides(self, tmp_path: Path):
        """多个 install 覆盖同时生效。"""
        _touch(tmp_path / "conf" / "a.conf")
        _touch(tmp_path / "conf" / "b.conf")
        spec = _make_spec(
            name="myapp",
            install={
                "conf/a.conf": "/etc/a.conf",
                "conf/b.conf": "/etc/b.conf",
            },
        )
        files = collect_files(tmp_path, spec, "aarch64")
        m = _result_map(files)
        assert "/etc/a.conf" in m
        assert "/etc/b.conf" in m
        # 约定路径不存在
        assert "/etc/myapp/a.conf" not in m
        assert "/etc/myapp/b.conf" not in m


# ---------------------------------------------------------------------------
# 空目录测试
# ---------------------------------------------------------------------------

class TestEmptyApp:
    """空目录边界情况测试。"""

    def test_empty_app_dir(self, tmp_path: Path):
        """App 目录下没有任何约定子目录时，返回空列表。"""
        spec = _make_spec(name="myapp")
        files = collect_files(tmp_path, spec, "aarch64")
        assert files == []

    def test_all_wrong_arch_returns_empty(self, tmp_path: Path):
        """所有 bin/ 文件均为错误架构后缀时，返回空列表。"""
        _touch(tmp_path / "bin" / "prog-armhf")
        spec = _make_spec(name="myapp")
        files = collect_files(tmp_path, spec, "aarch64")
        assert files == []

    def test_missing_subdirs_ignored(self, tmp_path: Path):
        """约定子目录不存在时静默跳过，只收集存在的子目录。"""
        _touch(tmp_path / "bin" / "prog")
        # 没有 conf/ lib/ 等目录
        spec = _make_spec(name="myapp")
        files = collect_files(tmp_path, spec, "aarch64")
        install_paths = [p for _, p, _ in files]
        assert "/usr/bin/prog" in install_paths
        assert len(files) == 1


# ---------------------------------------------------------------------------
# adbd 集成测试
# ---------------------------------------------------------------------------

class TestAdbdIntegration:
    """基于真实 adbd App 目录的集成测试。"""

    @pytest.fixture
    def adbd_dir(self) -> Path:
        """返回 adbd App 目录路径（相对工作树根目录）。"""
        # 从测试文件位置推算项目根目录
        here = Path(__file__).parent
        root = here.parent.parent
        adbd = root / "app" / "adbd"
        if not adbd.exists():
            pytest.skip(f"adbd 目录不存在：{adbd}")
        return adbd

    @pytest.fixture
    def adbd_spec(self, adbd_dir: Path) -> AppSpec:
        """加载 adbd 的 AppSpec。"""
        from builder.app_spec import load_spec
        return load_spec(adbd_dir)

    def test_adbd_aarch64_bin_selected(self, adbd_dir: Path, adbd_spec: AppSpec):
        """arch=aarch64 时，bin/adbd-arm64 被选中并安装为 /usr/bin/adbd。"""
        files = collect_files(adbd_dir, adbd_spec, "aarch64")
        m = _result_map(files)
        assert "/usr/bin/adbd" in m
        src = m["/usr/bin/adbd"][0]
        assert src.name == "adbd-arm64"

    def test_adbd_armhf_bin_selected(self, adbd_dir: Path, adbd_spec: AppSpec):
        """arch=armhf 时，bin/adbd-armhf 被选中并安装为 /usr/bin/adbd。"""
        files = collect_files(adbd_dir, adbd_spec, "armhf")
        m = _result_map(files)
        assert "/usr/bin/adbd" in m
        src = m["/usr/bin/adbd"][0]
        assert src.name == "adbd-armhf"

    def test_adbd_wrong_arch_excluded(self, adbd_dir: Path, adbd_spec: AppSpec):
        """arch=aarch64 时，bin/adbd-armhf 被排除，安装列表中只有一个 adbd。"""
        files = collect_files(adbd_dir, adbd_spec, "aarch64")
        adbd_entries = [p for _, p, _ in files if "adbd" in p.split("/")[-1]]
        assert len(adbd_entries) == 1
        assert adbd_entries[0] == "/usr/bin/adbd"

    def test_adbd_explicit_install_overrides(self, adbd_dir: Path, adbd_spec: AppSpec):
        """adbd install 段显式映射生效：conf、scripts、udev 使用显式路径。"""
        files = collect_files(adbd_dir, adbd_spec, "aarch64")
        m = _result_map(files)
        # 显式路径存在
        assert "/etc/usbdevice.conf" in m
        assert "/usr/sbin/usbdevice" in m
        assert "/etc/udev/rules.d/61-usbdevice.rules" in m

    def test_adbd_convention_paths_not_present(self, adbd_dir: Path, adbd_spec: AppSpec):
        """adbd 的 install 覆盖后，约定路径不应出现在安装列表中。"""
        files = collect_files(adbd_dir, adbd_spec, "aarch64")
        m = _result_map(files)
        # 约定路径（被 install 覆盖）
        assert "/etc/adbd/usbdevice.conf" not in m
        assert "/usr/lib/adbd/usbdevice" not in m
        assert "/lib/udev/rules.d/61-usbdevice.rules" not in m

    def test_adbd_systemd_convention(self, adbd_dir: Path, adbd_spec: AppSpec):
        """systemd/usbdevice.service 未在 install 段中，使用约定映射。"""
        files = collect_files(adbd_dir, adbd_spec, "aarch64")
        m = _result_map(files)
        assert "/lib/systemd/system/usbdevice.service" in m

    def test_adbd_modes(self, adbd_dir: Path, adbd_spec: AppSpec):
        """验证 adbd 各文件的权限设置是否符合预期。"""
        files = collect_files(adbd_dir, adbd_spec, "aarch64")
        m = _result_map(files)
        # bin 文件应为 0o755
        assert m["/usr/bin/adbd"][1] == 0o755
        # sbin 脚本应为 0o755
        assert m["/usr/sbin/usbdevice"][1] == 0o755
        # conf 文件应为 0o644
        assert m["/etc/usbdevice.conf"][1] == 0o644
        # udev rules 应为 0o644
        assert m["/etc/udev/rules.d/61-usbdevice.rules"][1] == 0o644
        # systemd unit 应为 0o644
        assert m["/lib/systemd/system/usbdevice.service"][1] == 0o644

    def test_adbd_total_files_count(self, adbd_dir: Path, adbd_spec: AppSpec):
        """adbd aarch64 安装文件总数应为 5（adbd + conf + scripts + udev + systemd）。"""
        files = collect_files(adbd_dir, adbd_spec, "aarch64")
        assert len(files) == 5

    def test_adbd_src_paths_exist(self, adbd_dir: Path, adbd_spec: AppSpec):
        """所有收集到的源文件路径在磁盘上实际存在。"""
        files = collect_files(adbd_dir, adbd_spec, "aarch64")
        for src, install_path, mode in files:
            assert src.exists(), f"源文件不存在：{src}（安装到 {install_path}）"
