"""平台包契约的符合性检查。

**为什么需要它**：`builder/platforms/<name>/` 是插件包，engine 靠
`ARTIFACT_NAMES` 与 `create_builder` 两个符号驱动它。此前这个契约只存在于
"其他平台都这么写"的约定里，没有任何一处校验 —— 新增平台漏一个符号，要等
构建跑到那个组件才抛 AttributeError。

同样，平台能力此前靠 `platform.startswith("qualcomm")` 在两个文件里各判一次，
把能力和命名绑死。现在能力由平台自己声明，这里锁住"声明的能力必须是已知的"。
"""

from __future__ import annotations

from pathlib import Path

import pytest

import builder.platforms as platforms_pkg
from builder.platforms import spec


def _platform_names() -> list[str]:
    root = Path(platforms_pkg.__file__).parent
    return sorted(
        entry.name for entry in root.iterdir()
        if entry.is_dir() and entry.name != "__pycache__"
        and (entry / "__init__.py").is_file()
    )


def test_至少发现了全部五个平台():
    """守住发现逻辑本身：目录扫描扫空时，下面的参数化测试会全部静默通过。"""
    names = _platform_names()
    assert len(names) >= 5, names
    assert "qualcommsc8280xp" in names, "re-export 型平台也必须被覆盖"


@pytest.mark.parametrize("platform", _platform_names())
def test_平台包符合契约(platform: str):
    module = spec.load(platform)
    missing = spec.missing_attrs(module)
    assert not missing, (
        f"{platform} 缺少平台契约符号 {missing}；"
        f"漏掉会等到构建跑到对应组件才抛 AttributeError")


@pytest.mark.parametrize("platform", _platform_names())
def test_平台只声明已知能力(platform: str):
    """写错能力名（拼写、复数）会静默走进默认分支，比不声明更难查。"""
    module = spec.load(platform)
    declared = {
        name.lower() for name in dir(module)
        if name.isupper() and name.lower().startswith("dtbo_")
    }
    unknown = declared - set(spec.CAPABILITIES)
    assert not unknown, (
        f"{platform} 声明了未知能力 {unknown}；"
        f"已知能力: {sorted(spec.CAPABILITIES)}")


def test_高通两个平台都走构建期DTBO合并():
    """sc8280xp 是 qcs6490 的 re-export —— 能力必须一并转发，不能只转发工厂。"""
    for platform in ("qualcommqcs6490", "qualcommsc8280xp"):
        assert spec.capability({"platform": platform}, "dtbo_merge_at_build") is True


def test_非高通平台走运行期overlay():
    for platform in ("rockchip", "amlogic", "allwinnera733"):
        assert spec.capability(
            {"platform": platform}, "dtbo_merge_at_build") is False


def test_平台名写错由validate拦截而不是能力查询():
    """分工：能力查询是查询，拼写检查是校验。

    此前 `startswith("qualcomm")` 两样都不做 —— `qualcom`（少一个 m）静默
    走进非高通分支，既不报错也不走对分支。
    """
    from builder.config.validate import ConfigError, validate_platform

    with pytest.raises(ConfigError) as exc:
        validate_platform({"platform": "qualcom6490"})
    assert "qualcommqcs6490" in str(exc.value), "报错要列出可选平台"

    # 能力查询本身不承担校验：没有平台包时退回默认值，
    # 这样合成平台名的测试夹具不会被能力查询绊住。
    assert spec.capability(
        {"platform": "qualcom6490"}, "dtbo_merge_at_build") is False


def test_已注册平台列表与磁盘一致():
    assert spec.known_platforms() == _platform_names()


def test_未知能力名立即报错():
    with pytest.raises(KeyError):
        spec.capability({"platform": "rockchip"}, "dtbo_merge_at_buildd")


def test_缺platform时退回默认值():
    """能力查询是查询不是校验；config 完整性归 validate 管。"""
    assert spec.capability({}, "dtbo_merge_at_build") is False
