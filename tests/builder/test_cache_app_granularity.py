"""per-App 缓存粒度与哈希覆盖面回归。

覆盖本轮引入的两类契约：
  1. 哈希覆盖面：App 目录名为 ``build``、位于 ``.build/`` 之下、以及位于 App
     目录之外的包级附加输入（如 rockchip-multimedia 的 ``patches/``）都必须
     进入哈希 —— 历史上这三处都被静默排除，改了源码却复用陈旧 deb。
  2. per-App 粒度：单个 App 的哈希、产物清单与命中判定彼此独立，改一个 App
     不得让其他 App 失效；``build.deps`` 沿 Merkle 级联。
"""

from __future__ import annotations

from pathlib import Path

from builder.cache import BuildCache


def _config(custom_packages: list[str] | None = None) -> dict:
    return {
        "board": "cache-test",
        "product": "default",
        "variant": "release",
        "architecture": {
            "userspace": "aarch64", "kernel": "arm64", "bootloader": "arm",
        },
        "platform": "rockchip",
        "soc": "rk3568",
        "kernel": {"device_tree": {"directory": "", "name": "cache-test"}},
        "rootfs": {
            "url": "https://example.com/ubuntu-base.tar.gz",
            "sha256": "a" * 64,
            "packages": [],
            "custom_packages": list(custom_packages or []),
        },
        "recovery": {"enabled": False},
        "amp": {"enabled": False},
        "partitions": {"format": "gpt", "entries": []},
    }


def _cache(project: Path, config: dict) -> BuildCache:
    return BuildCache(
        config, target_base=project / "target", project_root=project)


def _make_app(directory: Path, name: str, *, deps: list[str] | None = None):
    """写出一个最小可解析的 app.yaml。"""
    directory.mkdir(parents=True, exist_ok=True)
    lines = [
        "app:",
        f"  name: {name}",
        "  version: 1.0.0",
        "  description: demo",
        "  type: exec",
        "  arch: [aarch64]",
        "maintainer:",
        "  name: flange",
        "  email: flange@localhost",
        "build:",
        "  system: none",
    ]
    if deps:
        lines.append("  deps:")
        lines.extend(f"    - {dep}" for dep in deps)
    (directory / "app.yaml").write_text("\n".join(lines) + "\n")


# ---------------------------------------------------------------------------
# 哈希覆盖面
# ---------------------------------------------------------------------------

def test_app目录名为build时内容仍进入哈希(tmp_path: Path):
    """package 的 vendor App 目录就叫 build/，不能被当成构建产物排除。"""
    project = tmp_path / "project"
    app_dir = project / "components/packages/demo/build"
    _make_app(app_dir, "demo-build")
    script = app_dir / "build.py"
    script.write_text("VERSION = 1\n")

    config = _config(["demo-build"])
    config["external_apps"] = {"demo-build": {"local_path": str(app_dir)}}
    before = _cache(project, config).compute_app_hash("demo-build")

    script.write_text("VERSION = 2\n")

    assert before != _cache(project, config).compute_app_hash("demo-build")


def test_app目录位于dot_build之下时内容仍进入哈希(tmp_path: Path):
    """git 来源 App 的源码落在 .build/sources/apps/<name>/。"""
    project = tmp_path / "project"
    app_dir = project / ".build/sources/apps/demo"
    _make_app(app_dir, "demo")
    (app_dir / "main.c").write_text("int main(){return 0;}\n")

    config = _config(["demo"])
    config["external_apps"] = {"demo": {"git": "https://example.com/demo.git"}}
    before = _cache(project, config).compute_app_hash("demo")

    (app_dir / "main.c").write_text("int main(){return 1;}\n")

    assert before != _cache(project, config).compute_app_hash("demo")


def test_app目录内部的build子目录仍被排除(tmp_path: Path):
    """真正的 in-source 构建产物目录不应进哈希。"""
    project = tmp_path / "project"
    app_dir = project / "components/app/demo"
    _make_app(app_dir, "demo")

    config = _config(["demo"])
    before = _cache(project, config).compute_app_hash("demo")

    output = app_dir / "build"
    output.mkdir()
    (output / "demo.o").write_bytes(b"\x7fELF")

    assert before == _cache(project, config).compute_app_hash("demo")


def test_DS_Store不进入哈希(tmp_path: Path):
    """宿主机噪声文件不得让同一 commit 在不同机器上算出不同哈希。"""
    project = tmp_path / "project"
    app_dir = project / "components/app/demo"
    _make_app(app_dir, "demo")

    config = _config(["demo"])
    before = _cache(project, config).compute_app_hash("demo")

    (app_dir / ".DS_Store").write_bytes(b"\x00\x01")

    assert before == _cache(project, config).compute_app_hash("demo")


def test_包级附加输入进入app哈希(tmp_path: Path):
    """位于 App 目录之外、但参与构建的包内容（补丁）必须进哈希。"""
    project = tmp_path / "project"
    app_dir = project / "components/packages/demo/build"
    _make_app(app_dir, "demo-build")
    patches = project / "components/packages/demo/patches"
    patches.mkdir(parents=True)
    patch = patches / "0001-fix.patch"
    patch.write_text("--- a\n+++ b\n")

    config = _config(["demo-build"])
    config["external_apps"] = {"demo-build": {"local_path": str(app_dir)}}
    config["packages_meta"] = {
        "app_src_paths": {
            "demo-build": ["components/packages/demo/patches"],
        }
    }
    before = _cache(project, config).compute_app_hash("demo-build")

    patch.write_text("--- a\n+++ b\n+changed\n")

    assert before != _cache(project, config).compute_app_hash("demo-build")


def test_local_path差异不因项目根路径而漂移(tmp_path: Path):
    """宿主机 /Volumes/... 与容器 /workspace 下必须算出同一 App 哈希。"""
    hashes = []
    for root_name in ("hostA", "hostB"):
        project = tmp_path / root_name
        app_dir = project / "components/packages/demo/build"
        _make_app(app_dir, "demo-build")
        config = _config(["demo-build"])
        config["external_apps"] = {"demo-build": {"local_path": str(app_dir)}}
        hashes.append(_cache(project, config).compute_app_hash("demo-build"))

    assert hashes[0] == hashes[1]


# ---------------------------------------------------------------------------
# per-App 粒度
# ---------------------------------------------------------------------------

def test_改一个app不影响其他app哈希(tmp_path: Path):
    project = tmp_path / "project"
    for name in ("alpha", "beta"):
        _make_app(project / "components/app" / name, name)
    config = _config(["alpha", "beta"])
    cache = _cache(project, config)
    before = {name: cache.compute_app_hash(name) for name in ("alpha", "beta")}

    (project / "components/app/alpha/extra.sh").write_text("echo hi\n")

    after_cache = _cache(project, config)
    assert after_cache.compute_app_hash("alpha") != before["alpha"]
    assert after_cache.compute_app_hash("beta") == before["beta"]


def test_build_deps沿Merkle级联(tmp_path: Path):
    project = tmp_path / "project"
    _make_app(project / "components/app/base", "base")
    _make_app(project / "components/app/leaf", "leaf", deps=["base"])
    config = _config(["base", "leaf"])
    cache = _cache(project, config)
    before_leaf = cache.compute_app_hash("leaf")
    before_base = cache.compute_app_hash("base")

    (project / "components/app/base/lib.c").write_text("void f(){}\n")

    after = _cache(project, config)
    assert after.compute_app_hash("base") != before_base
    assert after.compute_app_hash("leaf") != before_leaf


def test_组件级app哈希汇总各app哈希(tmp_path: Path):
    project = tmp_path / "project"
    _make_app(project / "components/app/alpha", "alpha")
    config = _config(["alpha"])
    before = _cache(project, config).compute_hash("app")

    (project / "components/app/alpha/extra.sh").write_text("echo hi\n")

    assert before != _cache(project, config).compute_hash("app")


# ---------------------------------------------------------------------------
# 清单与命中判定
# ---------------------------------------------------------------------------

def test_store_app后命中且产物缺失时失效(tmp_path: Path):
    project = tmp_path / "project"
    _make_app(project / "components/app/demo", "demo")
    config = _config(["demo"])
    cache = _cache(project, config)

    assert not cache.is_app_up_to_date("demo")

    deb = cache.target_dir / "app" / "demo_1.0.0_arm64.deb"
    deb.parent.mkdir(parents=True)
    deb.write_bytes(b"deb")
    cache.store_app("demo", [deb])

    assert _cache(project, config).is_app_up_to_date("demo")

    deb.unlink()
    assert not _cache(project, config).is_app_up_to_date("demo")


def test_源码变化使单个app命中失效(tmp_path: Path):
    project = tmp_path / "project"
    app_dir = project / "components/app/demo"
    _make_app(app_dir, "demo")
    config = _config(["demo"])
    cache = _cache(project, config)
    deb = cache.target_dir / "app" / "demo_1.0.0_arm64.deb"
    deb.parent.mkdir(parents=True)
    deb.write_bytes(b"deb")
    cache.store_app("demo", [deb])
    assert _cache(project, config).is_app_up_to_date("demo")

    (app_dir / "extra.sh").write_text("echo hi\n")

    assert not _cache(project, config).is_app_up_to_date("demo")


def test_外部本地源码不命中per_app缓存(tmp_path: Path):
    """项目根之外的 local_path 是开发态源码，放弃缓存决策。"""
    project = tmp_path / "project"
    outside = tmp_path / "outside/demo"
    _make_app(outside, "demo")
    config = _config(["demo"])
    config["external_apps"] = {"demo": {"local_path": str(outside)}}
    cache = _cache(project, config)
    deb = cache.target_dir / "app" / "demo_1.0.0_arm64.deb"
    deb.parent.mkdir(parents=True)
    deb.write_bytes(b"deb")
    cache.store_app("demo", [deb])

    assert not _cache(project, config).is_app_up_to_date("demo")


def test_多deb清单逐项校验(tmp_path: Path):
    """多 deb App 少一个产物就不算齐全（旧的计数门禁发现不了）。"""
    project = tmp_path / "project"
    _make_app(project / "components/app/demo", "demo")
    config = _config(["demo"])
    cache = _cache(project, config)
    deb_dir = cache.target_dir / "app"
    deb_dir.mkdir(parents=True)
    debs = []
    for name in ("one", "two", "three"):
        path = deb_dir / f"{name}_1.0_arm64.deb"
        path.write_bytes(b"deb")
        debs.append(path)
    cache.store_app("demo", debs)
    assert cache._required_artifacts_present("app")

    debs[1].unlink()

    assert not _cache(project, config)._required_artifacts_present("app")
