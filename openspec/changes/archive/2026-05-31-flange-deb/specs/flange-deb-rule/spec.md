## ADDED Requirements

### Requirement: flange_deb 规则接口

`flange_deb` SHALL 作为 Bazel rule 实现于 `build/deb.bzl`，并通过 `build/defs.bzl` 导出。

规则 SHALL 支持以下属性：

| 属性 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `name` | string | 是 | Bazel target 名称 |
| `app_yaml` | label | 否 | app.yaml 文件（传入但不在 Starlark 中解析） |
| `version` | string | 是 | 语义化版本号 |
| `description` | string | 是 | 包描述 |
| `maintainer` | string | 是 | 维护者（格式: "Name \<email\>"） |
| `package_name` | string | 否 | deb 包名（默认使用 Bazel target 所在包路径的最后一段） |
| `architecture` | string | 否 | 目标架构（默认 "arm64"） |
| `binary` | label | 否 | 可执行文件 target 或 filegroup |
| `scripts` | label_list | 否 | 脚本文件列表 |
| `conf` | label_list | 否 | 配置文件列表 |
| `res` | label_list | 否 | 资源文件列表 |
| `systemd` | dict | 否 | systemd 配置 `{"unit": "path", "auto_start": True/False}` |
| `paths` | dict | 是 | 安装路径映射 `{"类别": "/目标路径"}` |
| `conffiles` | string_list | 否 | 需保护的配置文件绝对路径列表 |
| `runtime_deps` | string_list | 否 | 运行期 apt 依赖 |
| `data_dirs` | string_list | 否 | 运行时数据目录（postinst 中创建） |

#### Scenario: 从 BUILD.bazel 加载 flange_deb

- **WHEN** App 的 BUILD.bazel 中声明 `load("//build:defs.bzl", "flange_deb")`
- **THEN** `flange_deb` 符号可用，可调用创建 deb 打包 target

#### Scenario: 最小化 service 类型调用

- **WHEN** 调用 `flange_deb(name="foo-deb", version="1.0.0", description="test", maintainer="a <a@b>", binary=":foo", paths={"bin": "/usr/bin"}, systemd={"unit": "systemd/foo.service", "auto_start": True})`
- **THEN** 构建成功，产出包含可执行文件和 systemd unit 的 .deb 包

### Requirement: deb 包文件结构

`flange_deb` 产出的 .deb 文件 SHALL 遵循 Debian 包格式：

```
<name>_<version>_<arch>.deb  (ar archive)
├── debian-binary            # 内容: "2.0\n"
├── control.tar.gz
│   ├── control              # 包元数据
│   ├── conffiles            # 可选: 配置文件路径列表
│   ├── postinst             # 可选: 安装后脚本
│   └── prerm                # 可选: 卸载前脚本
└── data.tar.gz              # 安装文件树
```

#### Scenario: deb 包可被 dpkg 安装

- **WHEN** 在目标架构的 rootfs chroot 中执行 `dpkg -i <name>_<version>_<arch>.deb`
- **THEN** dpkg 成功安装，文件被放置到 `paths` 映射声明的目标路径

### Requirement: 路径映射安装

`flange_deb` SHALL 按 `paths` 字典将文件安装到目标路径。映射规则：

- `binary` 对应的文件安装到 `paths["bin"]`
- `scripts` 列表中的文件安装到 `paths["scripts"]`
- `conf` 列表中的文件安装到 `paths["conf"]`
- `res` 列表中的文件安装到 `paths["udev"]` 或其他对应 key

安装的二进制和脚本文件 SHALL 在 data.tar.gz 中设置 755 权限。配置文件和资源文件设置 644 权限。

#### Scenario: adbd 的路径映射

- **WHEN** `paths = {"bin": "/usr/bin", "scripts": "/usr/bin", "conf": "/etc", "udev": "/usr/lib/udev/rules.d"}`，binary 为 adbd，scripts 包含 usbdevice，conf 包含 usbdevice.conf，res 包含 61-usbdevice.rules
- **THEN** data.tar.gz 中文件布局为 `./usr/bin/adbd`、`./usr/bin/usbdevice`、`./etc/usbdevice.conf`、`./usr/lib/udev/rules.d/61-usbdevice.rules`

### Requirement: control 文件生成

`flange_deb` SHALL 从属性生成 debian control 文件，格式：

```
Package: <package_name>
Version: <version>
Architecture: <architecture>
Maintainer: <maintainer>
Description: <description>
Depends: <runtime_deps 逗号分隔>
```

`Package` 名称：若 `package_name` 未指定，SHALL 使用 Bazel target 所在包路径的最后一段（如 `app/adbd` → `adbd`）。

#### Scenario: control 文件内容正确

- **WHEN** `version="1.0.0"`, `description="test daemon"`, `maintainer="foo <foo@bar>"`, `architecture="arm64"`, `runtime_deps=["libc6"]`
- **THEN** control 文件包含对应字段，Depends 行为 `Depends: libc6`

#### Scenario: 无运行时依赖

- **WHEN** `runtime_deps` 为空或未指定
- **THEN** control 文件中不包含 Depends 行

### Requirement: conffiles 声明

当 `conffiles` 属性非空时，`flange_deb` SHALL 在 control.tar.gz 中生成 `conffiles` 文件，每行一个配置文件绝对路径，末尾无空行。

#### Scenario: conffiles 保护

- **WHEN** `conffiles = ["/etc/usbdevice.conf"]`
- **THEN** control.tar.gz 中包含 conffiles 文件，内容为 `/etc/usbdevice.conf\n`（无末尾空行）
- **THEN** dpkg 升级该包时不覆盖用户修改过的 `/etc/usbdevice.conf`

### Requirement: systemd 集成

当 `systemd` 属性指定时：

1. systemd unit 文件 SHALL 被安装到 `/lib/systemd/system/`（在 data.tar.gz 中）
2. 若 `auto_start` 为 True，SHALL 生成 `postinst` 脚本，兼容真实系统和 chroot 环境：
   - 真实系统（`/run/systemd/system` 存在）：执行 `systemctl daemon-reload && systemctl enable`
   - chroot 环境：解析 unit 文件的 `WantedBy=` 字段，直接创建 `/etc/systemd/system/<target>.wants/` 下的 symlink
3. SHALL 生成 `prerm` 脚本执行 `systemctl disable <service>`

postinst 和 prerm 脚本 SHALL 在 control.tar.gz 中设置 755 权限。

#### Scenario: auto_start 为 True（真实系统）

- **WHEN** `systemd = {"unit": "systemd/usbdevice.service", "auto_start": True}`，且在真实系统中安装（`/run/systemd/system` 存在）
- **THEN** `usbdevice.service` 被安装到 `/lib/systemd/system/usbdevice.service`
- **THEN** postinst 执行 `systemctl daemon-reload && systemctl enable usbdevice.service`

#### Scenario: auto_start 为 True（chroot 环境）

- **WHEN** `systemd = {"unit": "systemd/usbdevice.service", "auto_start": True}`，且在 chroot 环境中安装（`/run/systemd/system` 不存在）
- **THEN** postinst 解析 unit 文件的 `WantedBy=sysinit.target`，创建 `/etc/systemd/system/sysinit.target.wants/usbdevice.service` symlink
- **THEN** prerm 脚本包含 `systemctl disable usbdevice.service`

#### Scenario: auto_start 为 False

- **WHEN** `systemd = {"unit": "systemd/foo.service", "auto_start": False}`
- **THEN** unit 文件被安装但不生成 postinst 中的 systemctl enable

### Requirement: data_dirs 运行时目录

当 `data_dirs` 属性非空时，`flange_deb` SHALL 在 postinst 脚本中为每个目录执行 `mkdir -p`。

#### Scenario: 创建运行时数据目录

- **WHEN** `data_dirs = ["/var/lib/my-app", "/var/log/my-app"]`
- **THEN** postinst 脚本包含 `mkdir -p /var/lib/my-app` 和 `mkdir -p /var/log/my-app`
