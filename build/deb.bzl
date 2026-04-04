"""flange_deb — 将 App 文件打包为 .deb 的 Bazel 规则

用法:
    load("//build:defs.bzl", "flange_deb")

    flange_deb(
        name = "my-app-deb",
        version = "1.0.0",
        description = "My app",
        maintainer = "name <email>",
        binary = ":my-app",
        paths = {"bin": "/usr/bin"},
    )
"""

def _get_package_name(ctx):
    """从 package_name 属性或 Bazel 包路径推导 deb 包名"""
    if ctx.attr.package_name:
        return ctx.attr.package_name
    return ctx.label.package.split("/")[-1]

def _flange_deb_rule_impl(ctx):
    pkg_name = _get_package_name(ctx)
    version = ctx.attr.version
    arch = ctx.attr.architecture
    deb_filename = "{}_{}_{}.deb".format(pkg_name, version, arch)
    deb_file = ctx.actions.declare_file(deb_filename)

    # 收集所有输入文件
    input_files = []

    # binary 文件
    binary_files = []
    if ctx.attr.binary:
        binary_files = ctx.attr.binary.files.to_list()
        input_files.extend(binary_files)

    # scripts 文件
    script_files = []
    for target in ctx.attr.scripts:
        script_files.extend(target.files.to_list())
    input_files.extend(script_files)

    # conf 文件
    conf_files = []
    for target in ctx.attr.conf:
        conf_files.extend(target.files.to_list())
    input_files.extend(conf_files)

    # res 文件
    res_files = []
    for target in ctx.attr.res:
        res_files.extend(target.files.to_list())
    input_files.extend(res_files)

    # systemd unit 文件
    systemd_unit_file = None
    systemd_unit_name = ""
    if ctx.attr.systemd_unit:
        unit_files = ctx.attr.systemd_unit.files.to_list()
        if unit_files:
            systemd_unit_file = unit_files[0]
            systemd_unit_name = systemd_unit_file.basename
            input_files.append(systemd_unit_file)

    systemd_auto_start = ctx.attr.systemd_auto_start

    # app_yaml（传入但不解析）
    if ctx.attr.app_yaml:
        input_files.extend(ctx.attr.app_yaml.files.to_list())

    # --- 路径映射 ---
    paths = ctx.attr.paths
    data_commands = []

    # binary → paths["bin"]
    if binary_files and "bin" in paths:
        dest = paths["bin"]
        data_commands.append('mkdir -p "$DATA_DIR{}"'.format(dest))
        for f in binary_files:
            # adbd-arm64 → adbd (去掉架构后缀)
            out_name = f.basename.rsplit("-", 1)[0] if "-" in f.basename else f.basename
            data_commands.append('cp "$EXEC_ROOT/{src}" "$DATA_DIR{dest}/{name}"'.format(
                src = f.path, dest = dest, name = out_name,
            ))
            data_commands.append('chmod 755 "$DATA_DIR{dest}/{name}"'.format(
                dest = dest, name = out_name,
            ))

    # scripts → paths["scripts"]
    if script_files and "scripts" in paths:
        dest = paths["scripts"]
        data_commands.append('mkdir -p "$DATA_DIR{}"'.format(dest))
        for f in script_files:
            data_commands.append('cp "$EXEC_ROOT/{src}" "$DATA_DIR{dest}/{name}"'.format(
                src = f.path, dest = dest, name = f.basename,
            ))
            data_commands.append('chmod 755 "$DATA_DIR{dest}/{name}"'.format(
                dest = dest, name = f.basename,
            ))

    # conf → paths["conf"]
    if conf_files and "conf" in paths:
        dest = paths["conf"]
        data_commands.append('mkdir -p "$DATA_DIR{}"'.format(dest))
        for f in conf_files:
            data_commands.append('cp "$EXEC_ROOT/{src}" "$DATA_DIR{dest}/{name}"'.format(
                src = f.path, dest = dest, name = f.basename,
            ))
            data_commands.append('chmod 644 "$DATA_DIR{dest}/{name}"'.format(
                dest = dest, name = f.basename,
            ))

    # res → paths 中非 bin/scripts/conf 的 key
    if res_files:
        for key, dest in paths.items():
            if key in ("bin", "scripts", "conf"):
                continue
            data_commands.append('mkdir -p "$DATA_DIR{}"'.format(dest))
            for f in res_files:
                data_commands.append('cp "$EXEC_ROOT/{src}" "$DATA_DIR{dest}/{name}"'.format(
                    src = f.path, dest = dest, name = f.basename,
                ))
                data_commands.append('chmod 644 "$DATA_DIR{dest}/{name}"'.format(
                    dest = dest, name = f.basename,
                ))

    # systemd unit → /lib/systemd/system/
    if systemd_unit_file:
        data_commands.append('mkdir -p "$DATA_DIR/lib/systemd/system"')
        data_commands.append('cp "$EXEC_ROOT/{src}" "$DATA_DIR/lib/systemd/system/{name}"'.format(
            src = systemd_unit_file.path, name = systemd_unit_name,
        ))
        data_commands.append('chmod 644 "$DATA_DIR/lib/systemd/system/{name}"'.format(
            name = systemd_unit_name,
        ))

    data_install = "\n".join(data_commands)

    # --- control 文件 ---
    control_lines = [
        "Package: {}".format(pkg_name),
        "Version: {}".format(version),
        "Architecture: {}".format(arch),
        "Maintainer: {}".format(ctx.attr.maintainer),
        "Description: {}".format(ctx.attr.description),
    ]
    if ctx.attr.runtime_deps:
        control_lines.append("Depends: {}".format(", ".join(ctx.attr.runtime_deps)))
    control_content = "\\n".join(control_lines)

    # --- conffiles ---
    conffiles_commands = "# 无 conffiles"
    if ctx.attr.conffiles:
        lines = []
        for cf in ctx.attr.conffiles:
            lines.append('echo "{}" >> "$CONTROL_DIR/conffiles"'.format(cf))
        conffiles_commands = "\n".join(lines)

    # --- postinst ---
    postinst_lines = []
    if ctx.attr.data_dirs:
        for d in ctx.attr.data_dirs:
            postinst_lines.append("mkdir -p {}".format(d))
    if systemd_unit_name and systemd_auto_start:
        postinst_lines.append("if [ -d /run/systemd/system ]; then")
        postinst_lines.append("    systemctl daemon-reload")
        postinst_lines.append("    systemctl enable {}".format(systemd_unit_name))
        postinst_lines.append("else")
        postinst_lines.append("    # chroot 环境无 systemd，直接创建 symlink")
        postinst_lines.append("    WANTED_BY=$(grep \"^WantedBy=\" /lib/systemd/system/{} | cut -d= -f2)".format(systemd_unit_name))
        postinst_lines.append("    for target in $WANTED_BY; do")
        postinst_lines.append("        mkdir -p /etc/systemd/system/$target.wants")
        postinst_lines.append("        ln -sf /lib/systemd/system/{} /etc/systemd/system/$target.wants/{}".format(systemd_unit_name, systemd_unit_name))
        postinst_lines.append("    done")
        postinst_lines.append("fi")

    postinst_commands = "# 无 postinst"
    if postinst_lines:
        postinst_content = "\\n".join(["#!/bin/sh", "set -e"] + postinst_lines)
        postinst_commands = """printf '{content}\\n' > "$CONTROL_DIR/postinst"
chmod 755 "$CONTROL_DIR/postinst"
""".format(content = postinst_content)

    # --- prerm ---
    prerm_commands = "# 无 prerm"
    if systemd_unit_name:
        prerm_content = "\\n".join([
            "#!/bin/sh",
            "set -e",
            "if [ -d /run/systemd/system ]; then",
            "    systemctl disable {}".format(systemd_unit_name),
            "fi",
        ])
        prerm_commands = """printf '{content}\\n' > "$CONTROL_DIR/prerm"
chmod 755 "$CONTROL_DIR/prerm"
""".format(content = prerm_content)

    # --- 组装 .deb ---
    script = """\
set -euo pipefail

EXEC_ROOT="$(pwd)"
WORK_DIR="$(mktemp -d)"
DATA_DIR="$WORK_DIR/data"
CONTROL_DIR="$WORK_DIR/control"
DEB_DIR="$WORK_DIR/deb"

mkdir -p "$DATA_DIR" "$CONTROL_DIR" "$DEB_DIR"

# === 1. 构建 data 文件树 ===
{data_install}

# === 2. 构建 data.tar.gz ===
cd "$DATA_DIR"
tar czf "$DEB_DIR/data.tar.gz" --owner=root --group=root .
cd "$EXEC_ROOT"

# === 3. 生成 control 文件 ===
printf '{control_content}\\n' > "$CONTROL_DIR/control"

# === 4. 生成 conffiles ===
{conffiles_commands}

# === 5. 生成 postinst ===
{postinst_commands}

# === 6. 生成 prerm ===
{prerm_commands}

# === 7. 构建 control.tar.gz ===
cd "$CONTROL_DIR"
tar czf "$DEB_DIR/control.tar.gz" --owner=root --group=root .
cd "$EXEC_ROOT"

# === 8. 构建 debian-binary ===
echo "2.0" > "$DEB_DIR/debian-binary"

# === 9. 组装 .deb ===
cd "$DEB_DIR"
ar rcs "$EXEC_ROOT/{deb_out}" debian-binary control.tar.gz data.tar.gz

# === 清理 ===
rm -rf "$WORK_DIR"

echo "=== 打包完成: {deb_filename} ==="
""".format(
        data_install = data_install,
        control_content = control_content,
        conffiles_commands = conffiles_commands,
        postinst_commands = postinst_commands,
        prerm_commands = prerm_commands,
        deb_out = deb_file.path,
        deb_filename = deb_filename,
    )

    ctx.actions.run_shell(
        outputs = [deb_file],
        inputs = input_files,
        command = script,
        mnemonic = "FlangeDeb",
        progress_message = "打包 deb: {}".format(deb_filename),
    )

    return [DefaultInfo(files = depset([deb_file]))]

_flange_deb_rule = rule(
    implementation = _flange_deb_rule_impl,
    attrs = {
        "app_yaml": attr.label(
            allow_single_file = [".yaml", ".yml"],
            doc = "app.yaml 描述文件（传入但不在 Starlark 中解析）",
        ),
        "version": attr.string(
            mandatory = True,
            doc = "语义化版本号",
        ),
        "description": attr.string(
            mandatory = True,
            doc = "包描述",
        ),
        "maintainer": attr.string(
            mandatory = True,
            doc = "维护者（格式: Name <email>）",
        ),
        "package_name": attr.string(
            doc = "deb 包名（默认使用 Bazel 包路径最后一段）",
        ),
        "architecture": attr.string(
            default = "arm64",
            doc = "目标架构",
        ),
        "binary": attr.label(
            doc = "可执行文件 target 或 filegroup",
        ),
        "scripts": attr.label_list(
            allow_files = True,
            default = [],
            doc = "脚本文件列表",
        ),
        "conf": attr.label_list(
            allow_files = True,
            default = [],
            doc = "配置文件列表",
        ),
        "res": attr.label_list(
            allow_files = True,
            default = [],
            doc = "资源文件列表",
        ),
        "systemd_unit": attr.label(
            allow_single_file = [".service"],
            doc = "systemd unit 文件",
        ),
        "systemd_auto_start": attr.bool(
            default = False,
            doc = "是否在 postinst 中 systemctl enable",
        ),
        "paths": attr.string_dict(
            mandatory = True,
            doc = "安装路径映射: {类别: /目标路径}",
        ),
        "conffiles": attr.string_list(
            default = [],
            doc = "配置文件绝对路径列表（dpkg 升级保护）",
        ),
        "runtime_deps": attr.string_list(
            default = [],
            doc = "运行期 apt 依赖",
        ),
        "data_dirs": attr.string_list(
            default = [],
            doc = "运行时数据目录（postinst 创建）",
        ),
    },
)

def flange_deb(name, systemd = None, **kwargs):
    """flange_deb macro — 用户接口，将 systemd dict 拆解后传入 rule

    Args:
        name: Bazel target 名称
        systemd: systemd 配置 dict，格式 {"unit": "path/to/unit.service", "auto_start": True/False}
        **kwargs: 其他参数直接传递给 _flange_deb_rule
    """
    systemd_unit = None
    systemd_auto_start = False

    if systemd:
        unit_path = systemd.get("unit", "")
        if unit_path:
            systemd_unit = unit_path
        systemd_auto_start = systemd.get("auto_start", False)

    _flange_deb_rule(
        name = name,
        systemd_unit = systemd_unit,
        systemd_auto_start = systemd_auto_start,
        **kwargs
    )
