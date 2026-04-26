"""extlinux 配置生成与默认项处理。

flange 在 boot 分区内使用 U-Boot distro_bootcmd 标准的 extlinux 启动配置。
启用 recovery 时，normal 与 recovery 分别写入 ``extlinux.conf`` 与
``recovery.conf``；U-Boot 根据 reboot reason 或 boot-once 状态选择本次读取
哪一份配置文件，extlinux 文件本身只描述如何启动对应系统。

公开 API：

- ``NORMAL_LABEL`` / ``RECOVERY_LABEL`` — normal/recovery 配置内使用的 label 名常量
- ``NORMAL_CONFIG`` / ``RECOVERY_CONFIG`` — boot 分区中的 extlinux 配置文件名
- ``LabelSpec`` — 描述单个 label 的内容（kernel / fdt / append 等）
- ``render_extlinux`` — 把若干 ``LabelSpec`` 渲染为完整 extlinux 配置字符串
- ``set_default_label`` — 纯字符串变换：把现有 extlinux.conf 的 DEFAULT 改写到
  指定 label，输入不合法时 raise ``ValueError``。当前仅用于兼容 fallback
  或手工修复场景。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


NORMAL_LABEL = "flange"
RECOVERY_LABEL = "flange-recovery"
NORMAL_CONFIG = "extlinux.conf"
RECOVERY_CONFIG = "recovery.conf"


@dataclass
class LabelSpec:
    """一个 extlinux label 的内容描述。

    所有路径相对 boot 分区的根（即 boot 分区挂载点）。
    """
    name: str
    kernel: str                          # 例如 "/Image" 或 "/extlinux/Image"
    fdt: str = ""                        # devicetree blob 路径
    fdt_directive: str = "fdt"           # "fdt" (Rockchip) 或 "devicetree" (Allwinner)
    fdtoverlays: list[str] = field(default_factory=list)
    append: str = ""                     # 完整的 kernel cmdline


def render_extlinux(default_label: str, labels: list[LabelSpec]) -> str:
    """把多个 LabelSpec 渲染为单一 extlinux.conf 字符串。

    顺序保留输入顺序；首行写入 ``DEFAULT <default_label>``。``default_label``
    必须出现在 labels 之中，否则 raise ``ValueError``——避免生成出永远启动
    不到的菜单。
    """
    if default_label not in {l.name for l in labels}:
        raise ValueError(
            f"default_label={default_label!r} 不在 labels 列表中："
            f"{[l.name for l in labels]}"
        )

    lines: list[str] = [f"DEFAULT {default_label}", ""]
    for spec in labels:
        lines.append(f"label {spec.name}")
        lines.append(f"  kernel {spec.kernel}")
        if spec.fdt:
            lines.append(f"  {spec.fdt_directive} {spec.fdt}")
        if spec.fdtoverlays:
            lines.append("  fdtoverlays " + " ".join(spec.fdtoverlays))
        if spec.append:
            lines.append(f"  append {spec.append}")
        lines.append("")  # label 间空行
    return "\n".join(lines).rstrip() + "\n"


# --- 默认项原子切换 ---------------------------------------------------

# 用 [ \t] 而非 \s，避免 \s 在 MULTILINE 模式下吞掉换行符 / 空行
_DEFAULT_RE = re.compile(r"^[ \t]*DEFAULT[ \t]+(\S+)[ \t]*$", re.IGNORECASE | re.MULTILINE)
_LABEL_RE = re.compile(r"^[ \t]*label[ \t]+(\S+)[ \t]*$", re.IGNORECASE | re.MULTILINE)


def _existing_labels(content: str) -> list[str]:
    return [m.group(1) for m in _LABEL_RE.finditer(content)]


def set_default_label(content: str, target: str) -> str:
    """把 extlinux.conf 文本的 ``DEFAULT`` 指令切换到 ``target``。

    要求：
      - ``target`` 必须出现在文本的 ``label <name>`` 段中
      - 文本中 ``DEFAULT`` 出现 0 或 1 次：0 次时插入到首行；1 次时整行替换
      - 多次出现 ``DEFAULT`` 视为损坏，raise ``ValueError``

    返回新的完整文本（保持其余内容不变）。本函数不做磁盘写入；调用方应
    把返回值写到临时文件后 ``os.replace`` 原子替换原文件。
    """
    labels = _existing_labels(content)
    if target not in labels:
        raise ValueError(
            f"目标 label {target!r} 不在 extlinux.conf 中：{labels}"
        )

    matches = list(_DEFAULT_RE.finditer(content))
    if len(matches) > 1:
        raise ValueError(
            f"extlinux.conf 中存在 {len(matches)} 处 DEFAULT 指令，应为 0 或 1"
        )

    if not matches:
        # 没有 DEFAULT 行，插入到首行（保持文件以换行结尾）
        head = f"DEFAULT {target}\n"
        return head + content if content.startswith("\n") or not content else head + content

    # 整行替换 DEFAULT
    return _DEFAULT_RE.sub(f"DEFAULT {target}", content, count=1)


def get_default_label(content: str) -> str | None:
    """从 extlinux.conf 中读取当前 DEFAULT 指令；未声明时返回 None。"""
    matches = list(_DEFAULT_RE.finditer(content))
    if not matches:
        return None
    if len(matches) > 1:
        raise ValueError("extlinux.conf 中存在多处 DEFAULT 指令")
    return matches[0].group(1)
