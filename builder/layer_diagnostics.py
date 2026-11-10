"""组合来源诊断；不声称能追踪任意 Jsonnet 表达式的字段来源。"""

from builder.layers import stack_for
from builder.layer_resources import patch_resources, overlay_resources
from builder.config.apps import gather_custom_packages


def composition_report(config, context):
    stack = stack_for(config, context)
    resources = []
    for directory, names in (
        ("app", gather_custom_packages(config)),
        ("packages", config.get("packages") or []),
    ):
        for item in names:
            name = item if isinstance(item, str) else item.get("name", "")
            refs = stack.all(f"components/{directory}/{name}")
            if refs:
                resources.append(
                    {
                        "resource": f"{directory}/{name}",
                        "selected": refs[-1].identity,
                        "overridden": [ref.identity for ref in refs[:-1]],
                    }
                )
    return {
        "layers": stack.to_dict(),
        "config_chain": list(getattr(config, "config_chain", ())),
        "resources": resources,
        "patches": {
            name: [ref.identity for ref in patch_resources(stack, config, name)]
            for name in ("kernel", "bootloader")
        },
        "overlays": {
            name: [ref.identity for ref in overlay_resources(stack, config, name)]
            for name in ("rootfs", "recovery")
        },
    }


def composition_lines(report):
    lines = ["层顺序：" + " → ".join(item["name"] for item in report["layers"])]
    for label, values in (
        ("配置组合", report["config_chain"]),
        *((f"{name} 补丁", values) for name, values in report["patches"].items()),
    ):
        if values:
            lines.append(label + "：")
            lines.extend("  " + value for value in values)
    for resource in report["resources"]:
        lines.append(f"资源 {resource['resource']}：{resource['selected']}")
        lines.extend("  覆盖 " + value for value in resource["overridden"])
    return lines
