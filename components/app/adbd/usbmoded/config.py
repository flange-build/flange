"""配置加载：gadget 描述符与场景定义。

配置格式为 YAML，与 flange 既有的配置风格（app.yaml）一致。
控制协议不受影响，仍为行分隔 JSON —— 配置面向人工编辑，协议面向程序
解析与手工调试，两者载体不必统一。

分层合并语义：同一目录下的 .yaml 按文件名排序依次加载，后者按键合并
覆盖前者。App 层用 10- 前缀，板级用 20- 前缀。

**必须是按键合并而非整文件覆盖**：既有 shell 实现中板级 usbdevice.conf
整文件覆盖 App 层 conf，导致 App 层新增的键在 12 块板上默默丢失 ——
实测 7 个键因此在每块板重复了一遍（见 migration-table.md）。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from .gadget import GadgetDescriptor

log = logging.getLogger(__name__)

CONFIG_ROOT = Path("/etc/usbmode")
GADGET_DIR = CONFIG_ROOT / "gadget.d"
SCENES_DIR = CONFIG_ROOT / "scenes.d"
PERSIST_FILE = CONFIG_ROOT / "persist.yaml"

RUNTIME_ROOT = Path("/run/usbmoded")


class ConfigError(Exception):
    """配置加载或校验失败。"""


def deep_merge(base: dict, overlay: dict) -> dict:
    """递归按键合并。

    dict 递归合并；其余类型（含 list）整体替换 —— 列表语义上是「完整的
    一组值」，合并两个列表几乎总是得到调用方不想要的结果。uvc 的格式
    列表就是典型：板级声明只支持 mjpeg 时，必须替换而非追加。
    """
    result = dict(base)
    for key, value in overlay.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_dir(directory: Path) -> dict[str, Any]:
    """按文件名顺序加载并合并目录下的所有 .yaml。"""
    merged: dict[str, Any] = {}
    if not directory.is_dir():
        return merged
    for path in sorted(directory.glob("*.yaml")):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            raise ConfigError(f"解析配置失败：{path}: {exc}") from exc
        if data is None:
            continue
        if not isinstance(data, dict):
            raise ConfigError(f"配置根节点应为映射：{path}")
        merged = deep_merge(merged, data)
        log.debug("加载配置：%s", path)
    return merged


def _hex_str(value: Any, field: str) -> str:
    """校验并归一化十六进制配置项。

    约定所有十六进制值在 YAML 中写成带引号的字符串（见 migration-table.md）。
    PyYAML 按 YAML 1.1 会把裸写的 0x2207 解析成整数 8711，若放任不管，
    配置文件里写的和 configfs 里看到的就对不上了。这里兼容整数写法但
    统一归一化为 0x 字符串，并对非法值明确报错而非静默降级。
    """
    if isinstance(value, int) and not isinstance(value, bool):
        return f"0x{value:04x}"
    text = str(value).strip()
    try:
        return f"0x{int(text, 16):04x}"
    except ValueError as exc:
        raise ConfigError(
            f"{field} 不是合法的十六进制值：{value!r}（应形如 \"0x2207\"）"
        ) from exc


def load_gadget() -> tuple[GadgetDescriptor, str]:
    """加载 gadget 描述符配置，返回 (描述符, 默认场景名)。"""
    data = load_dir(GADGET_DIR)
    gadget = data.get("gadget") or {}
    if not isinstance(gadget, dict):
        raise ConfigError("配置项 gadget 应为映射")

    required = ("vendor_id", "product_name", "manufacturer", "group")
    missing = [k for k in required if not gadget.get(k)]
    if missing:
        raise ConfigError(
            f"gadget 配置缺少必填项：{', '.join(missing)}（检查 {GADGET_DIR}）"
        )

    pid_map_raw = gadget.get("pid_map") or {}
    if not isinstance(pid_map_raw, dict):
        raise ConfigError("配置项 gadget.pid_map 应为映射")
    pid_map = {str(k): _hex_str(v, f"gadget.pid_map.{k}") for k, v in pid_map_raw.items()}

    descriptor = GadgetDescriptor(
        group=str(gadget["group"]),
        vendor_id=_hex_str(gadget["vendor_id"], "gadget.vendor_id"),
        product_name=str(gadget["product_name"]),
        manufacturer=str(gadget["manufacturer"]),
        serial_source=str(gadget.get("serial_source", "cpuinfo")),
        bcd_device=_hex_str(gadget.get("bcd_device", "0x0310"), "gadget.bcd_device"),
        bcd_usb=_hex_str(gadget.get("bcd_usb", "0x0200"), "gadget.bcd_usb"),
        max_power=int(gadget.get("max_power", 500)),
        pid_map=pid_map,
    )
    default_scene = str(data.get("default_scene") or "debug")
    return descriptor, default_scene


def load_scenes() -> dict[str, dict[str, Any]]:
    """加载场景定义。

    场景结构：

        scenes:
          <name>:
            capabilities: [adb, mtp]      # 可省略，表示不改变能力集合
            role: device | host           # 可省略，表示不改变角色
            params:
              <capability>: {...}         # 能力参数，覆盖能力默认值
    """
    data = load_dir(SCENES_DIR)
    scenes = data.get("scenes") or {}
    if not isinstance(scenes, dict):
        raise ConfigError("配置项 scenes 应为映射")

    normalized: dict[str, dict[str, Any]] = {}
    for name, body in scenes.items():
        if not isinstance(body, dict):
            raise ConfigError(f"场景 {name} 的定义应为映射")

        caps = body.get("capabilities")
        if caps is not None and not isinstance(caps, list):
            raise ConfigError(f"场景 {name} 的 capabilities 应为列表")

        role_value = body.get("role")
        if role_value is not None and str(role_value) not in ("host", "device"):
            raise ConfigError(
                f"场景 {name} 的 role 应为 host 或 device，实际 {role_value!r}"
            )

        params = body.get("params") or {}
        if not isinstance(params, dict):
            raise ConfigError(f"场景 {name} 的 params 应为映射")

        if caps is None and role_value is None:
            raise ConfigError(
                f"场景 {name} 既未声明 capabilities 也未声明 role，无实际作用"
            )

        normalized[str(name)] = {
            "capabilities": [str(c) for c in caps] if caps is not None else None,
            "role": str(role_value) if role_value is not None else None,
            "params": params,
        }
    return normalized


def load_persisted_scene() -> str | None:
    """读取持久化的场景名，未设置时返回 None。"""
    if not PERSIST_FILE.is_file():
        return None
    try:
        data = yaml.safe_load(PERSIST_FILE.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        # 持久化文件损坏不应让设备无法启动 —— 记录后回落到默认场景。
        log.warning("持久化场景配置损坏，忽略：%s", exc)
        return None
    scene = data.get("scene") if isinstance(data, dict) else None
    return str(scene) if scene else None


def save_persisted_scene(name: str) -> None:
    """持久化场景名。"""
    CONFIG_ROOT.mkdir(parents=True, exist_ok=True)
    PERSIST_FILE.write_text(
        "# 由 usb-mode set -p 写入；usb-mode reset 可清除\n"
        f"scene: {name}\n",
        encoding="utf-8",
    )


def clear_persisted_scene() -> None:
    """清除持久化场景。"""
    PERSIST_FILE.unlink(missing_ok=True)
