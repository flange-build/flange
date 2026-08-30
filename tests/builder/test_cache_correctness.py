"""缓存正确性回归：源码身份、输入矩阵与动态产物门禁。"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from builder.cache import BuildCache
from builder.docker import BuildError
from builder.engine import BuildEngine
from builder.source import SourceManager


def _config() -> dict:
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
        "kernel_device": {"board_dts_path": "board-a.dts"},
        "bootloader": {},
        "rkbin": {"ini_prefix": "RK3568"},
        "boot": {},
        "rootfs": {
            "url": "https://example.com/ubuntu-base.tar.gz",
            "sha256": "a" * 64,
            "packages": [],
            "custom_packages": [],
            "hostname": "flange",
        },
        "storage": {"type": "emmc", "size": "8G"},
        "partitions": {"format": "gpt", "entries": []},
        "recovery": {"enabled": False},
        "amp": {"enabled": False},
        "image": {},
    }


def _cache(project: Path, config: dict | None = None) -> BuildCache:
    return BuildCache(
        config or _config(),
        target_base=project / "target",
        project_root=project,
    )


def _kernel_artifacts(cache: BuildCache) -> None:
    output = cache.target_dir / "kernel"
    output.mkdir(parents=True, exist_ok=True)
    (output / "Image").write_bytes(b"kernel")
    (output / "cache-test.dtb").write_bytes(b"dtb")


def test_branch_head未变化时允许命中(tmp_path: Path, monkeypatch):
    config = _config()
    config["sources"] = {
        "kernel": {"url": "https://example.com/kernel.git", "branch": "main"}
    }
    config["kernel"]["source"] = {"name": "kernel"}
    identity = SourceManager.source_identity(config["sources"]["kernel"])
    (tmp_path / ".build/sources/repos" / identity).mkdir(parents=True)
    cache = _cache(tmp_path, config)
    monkeypatch.setattr(cache, "_git_head", lambda _path: "stable-head")
    _kernel_artifacts(cache)

    cache.store("kernel")

    assert cache.is_up_to_date("kernel")


def test_store重新计算构建后head(tmp_path: Path, monkeypatch):
    config = _config()
    config["sources"] = {
        "kernel": {"url": "https://example.com/kernel.git"},
    }
    config["kernel"]["source"] = {"name": "kernel"}
    identity = SourceManager.source_identity(config["sources"]["kernel"])
    repo = tmp_path / ".build/sources/repos" / identity
    repo.mkdir(parents=True)
    state = {"head": "before"}
    cache = _cache(tmp_path, config)
    monkeypatch.setattr(cache, "_git_head", lambda _path: state["head"])
    cache.compute_hash("kernel")

    state["head"] = "after"
    cache.store("kernel")
    fresh = _cache(tmp_path, config)
    monkeypatch.setattr(fresh, "_git_head", lambda _path: state["head"])

    hash_file = cache.target_dir / "kernel/.build_hash"
    assert hash_file.read_text() == fresh.compute_hash("kernel")


def test_同一组件预同步与构建只fetch一次(tmp_path: Path, monkeypatch):
    manager = SourceManager(
        tmp_path / ".build/sources", project_root=tmp_path)
    descriptor = {
        "url": "https://example.com/kernel.git", "branch": "main",
    }
    repo = manager.sources_dir / "repos" / manager.source_identity(descriptor)
    repo.mkdir(parents=True)
    calls = []
    monkeypatch.setattr(
        manager, "_fetch_reset_branch",
        lambda path, branch: calls.append((path, branch)),
    )
    config = _config()
    config["sources"] = {"kernel": descriptor}
    config["kernel"]["source"] = {"name": "kernel"}

    manager.prepare_cache_inputs("kernel", config)
    manager.ensure("kernel", config)

    assert calls == [(repo, "main")]


def test_external_git_app已存在时仍同步branch(tmp_path: Path, monkeypatch):
    manager = SourceManager(
        tmp_path / ".build/sources", project_root=tmp_path)
    app_dir = manager.sources_dir / "apps/demo"
    app_dir.mkdir(parents=True)
    calls = []
    monkeypatch.setattr(
        manager, "_fetch_reset_branch",
        lambda path, branch: calls.append((path, branch)),
    )
    config = {
        "external_apps": {
            "demo": {"git": "https://example.com/demo.git", "branch": "main"}
        }
    }

    assert manager.ensure_app("demo", config) == app_dir
    assert calls == [(app_dir, "main")]


def test_engine先准备源码再查询缓存(tmp_path: Path, monkeypatch):
    engine = BuildEngine(_config(), project_dir=tmp_path)
    calls = []
    monkeypatch.setattr(
        engine.source, "prepare_cache_inputs",
        lambda component, config: calls.append(("prepare", component)),
    )
    monkeypatch.setattr(
        engine.cache, "is_up_to_date",
        lambda component: calls.append(("cache", component)) or True,
    )

    engine._build_components("app")

    assert calls == [("prepare", "app"), ("cache", "app")]


def test_仓库内vendor_app可命中而仓库外local_path强制重建(tmp_path: Path):
    project = tmp_path / "project"
    inside = project / "components/vendor/demo"
    outside = tmp_path / "outside/demo"
    for source in (inside, outside):
        source.mkdir(parents=True)
        (source / "app.yaml").write_text("name: demo")

    inside_config = _config()
    inside_config["rootfs"]["custom_packages"] = ["demo"]
    inside_config["external_apps"] = {"demo": {"local_path": str(inside)}}
    inside_cache = _cache(project, inside_config)
    deb = inside_cache.target_dir / "app/demo.deb"
    deb.parent.mkdir(parents=True)
    deb.write_bytes(b"deb")
    inside_cache.store_app("demo", [deb])
    inside_cache.store("app")
    assert inside_cache.is_up_to_date("app")

    outside_config = copy.deepcopy(inside_config)
    outside_config["external_apps"]["demo"]["local_path"] = str(outside)
    outside_cache = _cache(project, outside_config)
    outside_cache.store("app")

    assert not outside_cache.is_up_to_date("app")


def test_so载荷变化使app哈希失效(tmp_path: Path):
    app = tmp_path / "components/app/demo"
    app.mkdir(parents=True)
    (app / "app.yaml").write_text("name: demo")
    library = app / "libdemo.so"
    library.write_bytes(b"v1")
    config = _config()
    config["rootfs"]["custom_packages"] = ["demo"]
    before = _cache(tmp_path, config).compute_hash("app")

    library.write_bytes(b"v2")

    assert before != _cache(tmp_path, config).compute_hash("app")


@pytest.mark.parametrize(
    ("component", "path", "value"),
    [
        ("rootfs", ("rootfs", "hostname"), "changed"),
        ("rootfs", ("rootfs", "extra_apt_sources"), [{"source": "deb x"}]),
        ("rootfs", ("rootfs", "panel_firmware"),
         [{"src": "firmware/panel/demo.txt", "dest": "demo.bin"}]),
        ("rootfs", ("storage", "size"), "16G"),
        ("image", ("storage", "size"), "16G"),
        ("boot", ("recovery", "enabled"), True),
        ("bootloader", ("rkbin", "ini_prefix"), "RK3576"),
        ("kernel", ("kernel_device", "board_dts_path"), "board-b.dts"),
    ],
)
def test_实际消费配置变化会改变组件哈希(
        tmp_path: Path, component: str, path: tuple[str, str], value):
    before_config = _config()
    after_config = copy.deepcopy(before_config)
    after_config[path[0]][path[1]] = value

    before = _cache(tmp_path, before_config).compute_hash(component)
    after = _cache(tmp_path, after_config).compute_hash(component)

    assert before != after


def test_builder逻辑变化使组件哈希失效(tmp_path: Path):
    logic = tmp_path / "builder/example.py"
    logic.parent.mkdir(parents=True)
    logic.write_text("VALUE = 1\n")
    before = _cache(tmp_path).compute_hash("kernel")

    logic.write_text("VALUE = 2\n")

    assert before != _cache(tmp_path).compute_hash("kernel")


def test_rootfs_phase_hash覆盖extra_apt_sources(tmp_path: Path):
    before_config = _config()
    after_config = copy.deepcopy(before_config)
    after_config["rootfs"]["extra_apt_sources"] = [{"source": "deb x"}]

    assert (_cache(tmp_path, before_config).compute_phase_hash("rootfs", "base")
            != _cache(tmp_path, after_config).compute_phase_hash(
                "rootfs", "base"))


def test_dynamic_artifact_gates(tmp_path: Path):
    app_config = _config()
    app_config["rootfs"]["custom_packages"] = ["demo", "helper"]
    app_cache = _cache(tmp_path / "app", app_config)
    assert not app_cache._required_artifacts_present("app")
    deb = app_cache.target_dir / "app/demo.deb"
    deb.parent.mkdir(parents=True)
    deb.write_bytes(b"deb")
    app_cache.store_app("demo", [deb])
    # 门禁按每个 App 的产物清单逐项校验：helper 还没有清单就不算齐全，
    # 光凭 *.deb 总数够不算数。
    assert not app_cache._required_artifacts_present("app")
    helper = deb.parent / "helper.deb"
    helper.write_bytes(b"deb")
    app_cache.store_app("helper", [helper])
    assert app_cache._required_artifacts_present("app")
    helper.unlink()
    assert not app_cache._required_artifacts_present("app")

    overlay_config = _config()
    overlay_config["boot"]["overlays"] = {
        "intree": [], "vendor": ["demo.dtbo"], "board": [],
        "package": [], "enabled": [],
    }
    overlay_cache = _cache(tmp_path / "overlay", overlay_config)
    assert not overlay_cache._required_artifacts_present(
        "device-tree-overlay")
    dtbo = overlay_cache.target_dir / "device-tree-overlay/overlays/demo.dtbo"
    dtbo.parent.mkdir(parents=True)
    dtbo.write_bytes(b"dtbo")
    assert overlay_cache._required_artifacts_present("device-tree-overlay")


def test_qualcomm_bootloader要求所有刷写输入(tmp_path: Path):
    config = _config()
    config["platform"] = "qualcommsc8280xp"
    config["bootloader"] = {
        "edk2_firmware": {
            "url": "https://example.com/edk2.zip",
            "sha256": "a" * 64,
        },
        "firehose_loader": "prog_firehose_ddr.elf",
        "spi_rawprogram": "rawprogram0.xml",
        "spi_patch": "patch0.xml",
        "ufs_firehose": {
            "url": "https://example.com/ufs.elf",
            "filename": "prog_firehose_ufs.elf",
        },
        "ufs_provisions": {
            "default": {
                "url": "https://example.com/provision.xml",
                "filename": "provision.xml",
            }
        },
    }
    cache = _cache(tmp_path, config)
    firmware = cache.target_dir / "bootloader/edk2-spi-firmware"
    firmware.mkdir(parents=True)
    required = cache._required_artifacts("bootloader")
    for relative in required[:-1]:
        (cache.target_dir / "bootloader" / relative).write_bytes(b"asset")
    assert not cache._required_artifacts_present("bootloader")

    (cache.target_dir / "bootloader" / required[-1]).write_bytes(b"asset")

    assert cache._required_artifacts_present("bootloader")


def test_collect拒绝不存在的声明产物(tmp_path: Path):
    engine = BuildEngine(_config(), project_dir=tmp_path)

    with pytest.raises(BuildError, match="构建产物不存在"):
        engine._collect_artifacts("app", {"demo": tmp_path / "missing.deb"})


def test_collect保留已在target中的app产物(tmp_path: Path):
    engine = BuildEngine(_config(), project_dir=tmp_path)
    deb = engine.cache.target_dir / "app/demo.deb"
    deb.parent.mkdir(parents=True)
    deb.write_bytes(b"deb")

    engine._collect_artifacts("app", {"demo": deb})

    assert deb.read_bytes() == b"deb"


def test_无关builder模块变化不使组件哈希失效(tmp_path: Path):
    """刷写 / 部署 / 脚手架代码不参与构建，改动不该触发重编。

    历史上 _build_logic_hash 哈希整棵 builder/，改 builder/flash.py 一行就会
    让 kernel(222s)、app(644s)、rootfs(571s) 全部重建。

    flash 现已拆包，宿主机那一半按路径登记（见
    `test_flash的宿主机一半不进构建逻辑指纹`），这里覆盖其余顶层模块。
    """
    builder_dir = tmp_path / "builder"
    builder_dir.mkdir(parents=True)
    (builder_dir / "cache.py").write_text("VALUE = 1\n")
    for name in ("recovery_host.py", "deploy.py", "scaffold.py",
                 "app_list.py", "oot_mounts.py"):
        (builder_dir / name).write_text("VALUE = 1\n")
    templates = builder_dir / "templates"
    templates.mkdir()
    (templates / "app.yaml.tpl").write_text("name: {{name}}\n")

    before = _cache(tmp_path).compute_hash("kernel")

    for name in ("recovery_host.py", "deploy.py", "scaffold.py",
                 "app_list.py", "oot_mounts.py"):
        (builder_dir / name).write_text("VALUE = 2\n")
    (templates / "app.yaml.tpl").write_text("name: {{other}}\n")

    assert before == _cache(tmp_path).compute_hash("kernel")


def test_其他平台构建规则变化不使组件哈希失效(tmp_path: Path):
    """config.platform=rockchip 时，改 allwinner 的 kernel.py 不该重编。"""
    platforms = tmp_path / "builder/platforms"
    (platforms / "rockchip").mkdir(parents=True)
    (platforms / "allwinnera733").mkdir(parents=True)
    (platforms / "__init__.py").write_text("VALUE = 1\n")
    (platforms / "rockchip/kernel.py").write_text("VALUE = 1\n")
    (platforms / "allwinnera733/kernel.py").write_text("VALUE = 1\n")

    before = _cache(tmp_path).compute_hash("kernel")

    (platforms / "allwinnera733/kernel.py").write_text("VALUE = 2\n")
    assert before == _cache(tmp_path).compute_hash("kernel")

    (platforms / "rockchip/kernel.py").write_text("VALUE = 2\n")
    assert before != _cache(tmp_path).compute_hash("kernel")


def test_平台分派入口变化仍使组件哈希失效(tmp_path: Path):
    """platforms/__init__.py 是 create_builder 的分派点，必须保留在指纹内。"""
    platforms = tmp_path / "builder/platforms"
    (platforms / "rockchip").mkdir(parents=True)
    (platforms / "__init__.py").write_text("VALUE = 1\n")

    before = _cache(tmp_path).compute_hash("kernel")

    (platforms / "__init__.py").write_text("VALUE = 2\n")

    assert before != _cache(tmp_path).compute_hash("kernel")


# ---------------------------------------------------------------------------
# 按组件的配置切片：既要剔干净（不再全量重建），也不能剔漏（漏失效）
# ---------------------------------------------------------------------------

# 少数顶层键是标量（如 vendor 是字符串），探针要按类型构造。
_SCALAR_KEYS = {"vendor", "platform", "soc", "board"}


def _seed(config: dict, key: str) -> None:
    """确保被测键存在，且类型与真实配置一致。"""
    if key in config:
        return
    config[key] = "seed" if key in _SCALAR_KEYS else {}


def _mutate(config: dict, key: str) -> dict:
    """给顶层键塞一个探针值，模拟"这一段配置变了"。"""
    changed = copy.deepcopy(config)
    value = changed.get(key)
    if isinstance(value, dict):
        value["__probe__"] = "x"
    elif isinstance(value, list):
        value.append("__probe__")
    else:
        changed[key] = "__probe__"
    return changed


# 每个组件必须**保持敏感**的顶层键：改了就得重建。
# kernel 经 builder/dtb_overlay.py 读 boot.overlays.intree；rockchip
# bootloader 读 amp.enabled 校验 U-Boot AMP 选项 —— 这两条跨子树消费是
# 剔除表里最容易踩空的地方，单独钉住。
_SENSITIVE = {
    "kernel": ["kernel", "architecture", "sources", "boot"],
    "bootloader": ["bootloader", "rkbin", "architecture", "amp", "sources"],
    "boot": ["boot", "kernel", "partitions", "recovery"],
    "device-tree-overlay": ["boot", "kernel", "vendor"],
    "rootfs": ["rootfs", "partitions", "storage", "architecture"],
    "recovery": ["recovery", "rootfs", "partitions"],
    "image": ["partitions", "storage", "rkbin", "rootfs", "recovery", "amp"],
    "app": ["rootfs", "recovery", "architecture", "external_apps"],
    "amp": ["amp"],
}

# 每个组件应当**不再敏感**的顶层键：这正是本次切片要拿到的收益。
_INSENSITIVE = {
    "kernel": ["rootfs", "recovery", "storage", "amp", "partitions"],
    "bootloader": ["rootfs", "recovery", "kernel", "kernel_device",
                   "partitions"],
    "boot": ["rootfs"],
    # dto 依赖 kernel，只在 kernel 也剔除的键上才真正不敏感
    "device-tree-overlay": ["rootfs", "recovery", "storage", "partitions"],
    "app": ["kernel", "bootloader", "boot", "partitions", "storage", "rkbin"],
    "amp": ["rootfs", "recovery", "kernel", "bootloader", "partitions"],
}


@pytest.mark.parametrize(
    "component,key",
    [(c, k) for c, keys in _SENSITIVE.items() for k in keys],
)
def test_组件对其消费的配置键保持敏感(tmp_path: Path, component: str, key: str):
    before_config = _config()
    _seed(before_config, key)
    before = _cache(tmp_path, before_config).compute_hash(component)

    after = _cache(tmp_path, _mutate(before_config, key)).compute_hash(component)

    assert before != after, f"{component} 对 {key} 变化不敏感（漏失效）"


@pytest.mark.parametrize(
    "component,key",
    [(c, k) for c, keys in _INSENSITIVE.items() for k in keys],
)
def test_组件对无关配置键不再失效(tmp_path: Path, component: str, key: str):
    before_config = _config()
    _seed(before_config, key)
    before = _cache(tmp_path, before_config).compute_hash(component)

    after = _cache(tmp_path, _mutate(before_config, key)).compute_hash(component)

    assert before == after, f"{component} 因无关的 {key} 变化而失效（过度失效）"


def test_剔除表只列组件不消费的键():
    """剔除表与敏感键表不得冲突 —— 冲突意味着设计上自相矛盾。"""
    from builder.cache import CONFIG_IRRELEVANT_ALWAYS, CONFIG_IRRELEVANT_KEYS

    for component, keys in _SENSITIVE.items():
        irrelevant = (CONFIG_IRRELEVANT_ALWAYS
                      | CONFIG_IRRELEVANT_KEYS.get(component, frozenset()))
        overlap = irrelevant & set(keys)
        assert not overlap, f"{component} 把消费中的键 {overlap} 列入了剔除表"


def test_jsonnet源文件的语义无关编辑不再触发重建(tmp_path: Path):
    """旧实现把 jsonnet 源文件的原始字节混进每个组件哈希，加一行注释就全量重建。"""
    config = _config()
    cache_before = _cache(tmp_path, config)
    before = cache_before.compute_hash("kernel")

    # 模拟"改了 jsonnet 注释但求值结果不变"：jsonnet_hash 变、canonical 不变
    class _Resolved(dict):
        pass

    changed = _Resolved(copy.deepcopy(config))
    changed.jsonnet_hash = "different-after-comment-edit"

    assert before == _cache(tmp_path, changed).compute_hash("kernel")


# ---------------------------------------------------------------------------
# 缓存决策的可解释性（flange why）
# ---------------------------------------------------------------------------

def test_explain指出变化的分段(tmp_path: Path):
    """用户要能知道"为什么重建"，而不只是"要重建"。"""
    config = _config()
    cache = _cache(tmp_path, config)
    _kernel_artifacts(cache)
    cache.store("kernel")
    assert cache.explain("kernel")["up_to_date"]
    assert cache.explain("kernel")["reasons"] == []

    changed = copy.deepcopy(config)
    changed["kernel"]["defconfig"] = ["other"]
    report = _cache(tmp_path, changed).explain("kernel")

    assert not report["up_to_date"]
    assert [item["segment"] for item in report["reasons"]] == ["config", "own"]


def test_explain区分上游级联与自身变化(tmp_path: Path):
    config = _config()
    config["recovery"]["enabled"] = True
    cache = _cache(tmp_path, config)
    _kernel_artifacts(cache)
    cache.store("kernel")
    cache.store("boot")

    changed = copy.deepcopy(config)
    changed["kernel"]["defconfig"] = ["other"]
    report = _cache(tmp_path, changed).explain("boot")

    segments = [item["segment"] for item in report["reasons"]]
    assert "dep:kernel" in segments
    assert "own" not in segments, "boot 自身输入没变，不该记在 own 上"


def test_explain在无存档时给出说明(tmp_path: Path):
    report = _cache(tmp_path).explain("kernel")

    assert not report["up_to_date"]
    assert report["reasons"] == []
    assert "首次构建" in report["note"]


def test_explain识别产物缺失(tmp_path: Path):
    config = _config()
    cache = _cache(tmp_path, config)
    _kernel_artifacts(cache)
    cache.store("kernel")
    (cache.target_dir / "kernel/Image").unlink()

    report = _cache(tmp_path, config).explain("kernel")

    assert not report["up_to_date"]
    assert report["reasons"] == []
    assert "产物缺失" in report["note"]


def test_store写出分段存档(tmp_path: Path):
    import json as _json

    cache = _cache(tmp_path)
    _kernel_artifacts(cache)
    cache.store("kernel")

    archive = cache.target_dir / "kernel/.build_hash.json"
    segments = _json.loads(archive.read_text())
    assert set(segments) == {"identity", "config", "logic", "own"}


def test_构建期分区渲染进入构建逻辑指纹(tmp_path: Path):
    """parameter.txt 的渲染器住在 builder/partition/ 而非被排除的 flash.py。

    它的产物（target/image/parameter.txt、mtd-bundle.json）进 image 组件缓存，
    改了渲染格式却不重建 image 就会留下陈旧分区表 —— 整盘刷不进去。
    """
    from builder.cache import BUILD_LOGIC_EXCLUDE_FILES

    assert "rockchip.py" not in BUILD_LOGIC_EXCLUDE_FILES

    renderer = tmp_path / "builder/partition/rockchip.py"
    renderer.parent.mkdir(parents=True)
    renderer.write_text("VALUE = 1\n")
    before = _cache(tmp_path).compute_hash("image")

    renderer.write_text("VALUE = 2\n")

    assert before != _cache(tmp_path).compute_hash("image")


def test_image不再反向导入flash模块():
    """反向导入是分层错误的报警：image 是构建期、flash 是宿主机执行期。"""
    source = Path("builder/platforms/rockchip/image.py").read_text()
    assert "from builder.flash import" not in source


def test_平台复用的实现也进入构建逻辑指纹(tmp_path: Path):
    """qualcommsc8280xp 直接 re-export qualcommqcs6490 的实现。

    只保留"当前平台目录"会把实际执行的那份实现排除掉 —— 改它不会让本
    target 失效，是静默漏失效。
    """
    platforms = tmp_path / "builder/platforms"
    (platforms / "qualcommqcs6490").mkdir(parents=True)
    (platforms / "qualcommsc8280xp").mkdir(parents=True)
    (platforms / "amlogic").mkdir(parents=True)
    (platforms / "__init__.py").write_text("VALUE = 1\n")
    (platforms / "qualcommsc8280xp/__init__.py").write_text(
        "from builder.platforms.qualcommqcs6490 import create_builder\n")
    (platforms / "qualcommqcs6490/kernel.py").write_text("VALUE = 1\n")
    (platforms / "amlogic/kernel.py").write_text("VALUE = 1\n")

    config = _config()
    config["platform"] = "qualcommsc8280xp"
    before = _cache(tmp_path, config).compute_hash("kernel")

    # 无关平台：不该失效
    (platforms / "amlogic/kernel.py").write_text("VALUE = 2\n")
    assert before == _cache(tmp_path, config).compute_hash("kernel")

    # 被复用的实现：必须失效
    (platforms / "qualcommqcs6490/kernel.py").write_text("VALUE = 2\n")
    assert before != _cache(tmp_path, config).compute_hash("kernel")


def test_平台目录不存在时不做平台过滤(tmp_path: Path):
    """解析不出平台包时宁可多编，也不能漏掉真正参与构建的实现。"""
    platforms = tmp_path / "builder/platforms"
    (platforms / "someplatform").mkdir(parents=True)
    (platforms / "someplatform/kernel.py").write_text("VALUE = 1\n")

    config = _config()
    config["platform"] = "not-a-real-platform"
    before = _cache(tmp_path, config).compute_hash("kernel")

    (platforms / "someplatform/kernel.py").write_text("VALUE = 2\n")

    assert before != _cache(tmp_path, config).compute_hash("kernel")


def test_panel_firmware源内容变化使rootfs失效(tmp_path: Path):
    """面板 bringup 反复改的是 init 序列文本，而不是它的路径。

    只哈希 rootfs 配置子树只能覆盖 src/dest 声明；改内容不失效会刷出与源码
    不符的镜像。
    """
    config = _config()
    config["rootfs"]["panel_firmware"] = [
        {"src": "firmware/panel/demo.txt", "dest": "demo.bin"},
    ]
    source = tmp_path / "components/board/cache-test/firmware/panel/demo.txt"
    source.parent.mkdir(parents=True)
    source.write_text("command 0x11\n")
    before = _cache(tmp_path, config).compute_hash("rootfs")

    source.write_text("command 0x11\ncommand 0x29\n")

    assert before != _cache(tmp_path, config).compute_hash("rootfs")


@pytest.mark.parametrize(
    "platform", ["rockchip", "allwinnera733", "amlogic"])
def test_bootloader产物门禁非空(tmp_path: Path, platform: str):
    """缺门禁时缓存可在产物被删的情况下命中，刷出没有 bootloader 的设备。"""
    config = _config()
    config["platform"] = platform
    assert _cache(tmp_path, config)._required_artifacts("bootloader")


# ---------------------------------------------------------------------------
# local_path 的两半语义：不动工作树 + 放弃缓存
# ---------------------------------------------------------------------------

def test_local_path组件不重置工作树也不打补丁(tmp_path: Path):
    """`local_path` 声明的是"我正在 hack 这份源码"。

    历史上只兑现了缓存那一半（强制重建），而 `_local_mode` 开关无人写入、
    条件恒为假，于是 `git checkout -f .` 照跑 —— 用本地 kernel 调试时未提交
    的改动被静默抹掉，而文档白纸黑字承诺"框架不做 git 操作"。
    """
    from unittest.mock import MagicMock

    from builder.base import ComponentBuilder

    class _Probe(ComponentBuilder):
        component = "kernel"

        def __init__(self):
            super().__init__(MagicMock(), MagicMock())
            self.reset_calls = 0
            self.patch_calls = 0

        def reset_source(self, src_dir):
            self.reset_calls += 1

        def apply_patches(self, src_dir, config):
            self.patch_calls += 1

        def configure(self, src_dir, config): ...
        def compile(self, src_dir, config): ...
        def collect(self, src_dir, config): return {}

    local = tmp_path / "my-kernel"
    local.mkdir()
    config = _config()
    config["kernel"]["source"] = {"name": "linux"}
    config["sources"] = {"linux": {"local_path": str(local)}}

    builder = _Probe()
    builder.source.ensure.return_value = local
    builder.build(config)

    assert builder.reset_calls == 0, "local_path 工作树不该被 reset"
    assert builder.patch_calls == 0, "local_path 工作树不该被打补丁"

    # 非 local 源仍照常重置与打补丁
    config["sources"] = {"linux": {"url": "https://example.com/linux.git"}}
    other = _Probe()
    other.source.ensure.return_value = local
    other.build(config)

    assert other.reset_calls == 1
    assert other.patch_calls == 1


def test_local_path组件仍强制重建并级联下游(tmp_path: Path):
    """两半语义的另一半：不动工作树，但也不敢相信缓存。"""
    local = tmp_path / "my-kernel"
    local.mkdir()
    config = _config()
    config["kernel"]["source"] = {"name": "linux"}
    config["sources"] = {"linux": {"local_path": str(local)}}
    cache = _cache(tmp_path, config)
    _kernel_artifacts(cache)
    cache.store("kernel")

    assert not cache.is_up_to_date("kernel")
    assert not cache.is_up_to_date("rootfs"), "下游必须跟着强制重建"


def test_flash的构建期一半进入构建逻辑指纹(tmp_path: Path):
    """flash-config.json 是 image 组件的构建产物。

    拆包之前 flash.py 整个被排除 —— 改 flash-config 的生成规则不会让 image
    失效，刷写时读到的是上一次构建的分区偏移。这是漏失效。
    """
    from builder.cache import BUILD_LOGIC_EXCLUDE_PATHS

    for build_time in ("flash/plan.py", "flash/generate.py",
                       "flash/model.py", "flash/spi.py"):
        assert build_time not in BUILD_LOGIC_EXCLUDE_PATHS, build_time

    generator = tmp_path / "builder/flash/generate.py"
    generator.parent.mkdir(parents=True)
    generator.write_text("VALUE = 1\n")
    before = _cache(tmp_path).compute_hash("image")

    generator.write_text("VALUE = 2\n")

    assert before != _cache(tmp_path).compute_hash("image")


def test_flash的宿主机一半不进构建逻辑指纹(tmp_path: Path):
    """改一句 rkdeveloptool 的命令行不该让 kernel 重新编译。

    拆包之前这两半挤在一个文件里，只能整文件排除；现在按性质分别登记。
    """
    strategy = tmp_path / "builder/flash/strategy.py"
    strategy.parent.mkdir(parents=True)
    strategy.write_text("VALUE = 1\n")
    before = _cache(tmp_path).compute_hash("kernel")

    strategy.write_text("VALUE = 2\n")

    assert before == _cache(tmp_path).compute_hash("kernel")


def test_构建期一半不反向依赖宿主机一半():
    """generate/plan 依赖 strategy，就等于把整个刷写工具链拖进构建指纹。

    console 不在禁止之列：generate 用它打状态行，因此它也留在指纹里。
    含糊的文件一律留在指纹里 —— 过度失效只是多花时间，漏失效是产物错误。
    """
    import ast

    for build_time in ("builder/flash/generate.py", "builder/flash/plan.py",
                       "builder/flash/model.py", "builder/flash/spi.py"):
        tree = ast.parse(Path(build_time).read_text())
        imported = {
            node.module for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        } | {
            alias.name for node in ast.walk(tree)
            if isinstance(node, ast.Import) for alias in node.names
        }
        forbidden = {"builder.flash.strategy",
                     "builder.flash.execute"} & imported
        assert not forbidden, f"{build_time} 依赖了宿主机侧 {forbidden}"
