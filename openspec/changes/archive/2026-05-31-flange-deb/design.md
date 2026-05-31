> **归档说明**：本设计方案属于 Bazel 构建系统时代（v1.0），仅作历史参考。当前架构参见 `openspec/flange-build-tool-design.md`。

## Context

flange 的 App 体系设计（`docs/app-architecture.md`）定义了 `flange_deb` 规则作为 App 打包的核心，但该规则尚未实现。当前已有 `app/adbd` 作为第一个消费者，其 BUILD.bazel 已编写好 `flange_deb` 调用，等待规则实现。

现有构建体系：
- Bazel 是唯一构建入口，所有构建规则用 Starlark 编写
- `rootfs_customize` 规则从 `packages/` 目录读取预置 .deb，通过 shell 脚本 `dpkg -i` 安装
- Docker 容器内执行实际构建，宿主机不做编译环境要求

关键约束：
- Starlark 无法解析 YAML（app.yaml 仅作参考，元数据在 BUILD.bazel 中声明）
- Bazel 产出在 `bazel-bin/`，不能写入源码目录 `packages/`
- 构建环境（Docker 容器）内有 `ar`、`tar`、`gzip` 等基础工具

## Goals / Non-Goals

**Goals:**

- 实现 `flange_deb` Bazel 规则，支持 `docs/app-architecture.md` 定义的 exec 和 service 类型 App 打包
- 打通 Bazel 产出 .deb → rootfs 安装的完整链路
- adbd 作为第一个 App 端到端跑通

**Non-Goals:**

- 不实现 lib 类型双包产出（后续扩展）
- 不实现 flange_cmake / flange_meson 等构建系统包装
- 不引入 rules_pkg 外部依赖

## Decisions

### 决策 1: Shell 脚本构建 .deb，不依赖 rules_pkg

在 `flange_deb` 规则的 action 中使用 shell 脚本直接构建 .deb 文件。.deb 本质上是一个 `ar` 归档，包含：

```
package.deb (ar archive)
├── debian-binary        # "2.0\n"
├── control.tar.gz       # control, conffiles, postinst, prerm
└── data.tar.gz          # 实际安装文件
```

**理由**: .deb 格式简单，shell 几十行即可实现。避免引入 `rules_pkg` 外部依赖，减少项目复杂度。flange 的 deb 不需要处理复杂的 dpkg 特性（triggers、alternatives 等），只需基本的文件安装和 systemd enable。

**替代方案**: 引入 `rules_pkg` 的 `pkg_deb`。优点是成熟稳定，缺点是额外依赖且 API 不完全匹配 flange 的设计（路径映射、systemd 集成等需要额外适配层）。

### 决策 2: macro + rule 双层结构

`flange_deb` 对外是一个 macro，内部调用 `_flange_deb_rule`。macro 负责将用户友好的 `systemd` dict（含 boolean `auto_start`）拆解为 rule 兼容的 `systemd_unit`（label）和 `systemd_auto_start`（bool）属性，因为 Starlark 的 `attr.string_dict()` 不支持 boolean 值。

rule 的 action 流程：
1. 根据 `paths` 映射构建 `data.tar.gz`（安装文件树）
2. 从 attrs 生成 `control` 文件
3. 根据 `conffiles` 生成 conffiles 文件
4. 根据 `systemd` 生成 `postinst`/`prerm` 脚本
5. 打包 `control.tar.gz`
6. 用 `ar` 组合为 .deb

### 决策 3: 通过 custom_deb_targets 集成 rootfs_customize

在 `rootfs_customize` 规则中新增 `custom_deb_targets` 属性（`label_list`），接受 Bazel 构建的 .deb target。规则将这些 .deb 的路径通过环境变量传递给 customize script。

```python
rootfs_customize(
    ...
    custom_deb_targets = select({
        "//build:board_radxa_zero3w": [
            "//app/adbd:adbd-deb",
        ],
    }),
)
```

与现有 `custom_packages_dir`（预置 .deb）机制并存，不破坏现有逻辑。

**理由**: 最小改动，只新增一个 attr 和对应的环境变量传递。customize script 中新增一段安装逻辑即可。

### 决策 4: deb 文件命名与架构

输出文件名格式：`<name>_<version>_<arch>.deb`

architecture 字段从 Bazel 的 target platform 推断：
- 由 `flange_deb` 的 `architecture` attr 指定，默认 `"arm64"`
- 未来可从 toolchain 配置自动推断

### 决策 5: build/defs.bzl 作为统一导出入口

`build/defs.bzl` 作为所有构建规则的统一 load 入口：

```python
load("//build:deb.bzl", _flange_deb = "flange_deb")
flange_deb = _flange_deb
```

App 的 BUILD.bazel 统一从 `//build:defs.bzl` 加载，不直接引用内部 .bzl 文件。符合 `docs/app-architecture.md` 的设计。

### 决策 6: postinst 脚本兼容 chroot 环境

deb 安装发生在 rootfs 构建阶段的 chroot 内，此时 systemd 不在运行，`systemctl enable` 会失败。postinst 脚本需做环境检测：

- 若 `/run/systemd/system` 存在（真实系统）：执行 `systemctl daemon-reload && systemctl enable`
- 否则（chroot 环境）：解析 unit 文件的 `WantedBy=` 字段，直接创建 `/etc/systemd/system/<target>.wants/` 下的 symlink

```bash
if [ -d /run/systemd/system ]; then
    systemctl daemon-reload
    systemctl enable usbdevice.service
else
    WANTED_BY=$(grep "^WantedBy=" /lib/systemd/system/usbdevice.service | cut -d= -f2)
    for target in $WANTED_BY; do
        mkdir -p /etc/systemd/system/$target.wants
        ln -sf /lib/systemd/system/usbdevice.service /etc/systemd/system/$target.wants/usbdevice.service
    done
fi
```

**理由**: 这是实际验证中发现的 bug——dpkg postinst 在 chroot 中运行 `systemctl enable` 会报错。Debian 官方包也使用类似的环境检测逻辑。

### 决策 7: dpkg 安装使用 find + 显式路径列表

customize script 中安装 .deb 时，不使用 shell glob（`*.deb`），而是用 `find -printf` 生成 chroot 内的路径列表传给 `dpkg -i`：

```bash
DEB_LIST=$(find "${ROOTFS}/tmp/bazel-debs" -name '*.deb' -printf '/tmp/bazel-debs/%f\n')
chroot "${ROOTFS}" dpkg -i ${DEB_LIST}
```

**理由**: 直接 `dpkg -i /tmp/bazel-debs/*.deb` 在 chroot 中可能因 glob 展开时机问题而失败。`find -printf` 生成的是 chroot 内的相对路径，更可靠。

## Risks / Trade-offs

- **[Shell 构建的 deb 兼容性]** → 自行实现的 .deb 可能在边界情况下与 dpkg 不完全兼容（如 control 文件格式细节）。→ 以 adbd 作为第一个测试用例验证，确保 `dpkg -i` 能正确安装。
- **[architecture 硬编码]** → 当前 architecture 需手动指定，不能自动感知 Bazel platform。→ MVP 阶段可接受，后续可通过 toolchain resolution 自动推断。
- **[rootfs_customize 修改兼容性]** → 新增 `custom_deb_targets` 不影响现有 `custom_packages_dir` 流程，向后兼容。