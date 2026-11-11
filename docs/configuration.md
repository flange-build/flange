# 配置参考

系统配置回答“构建哪块板、哪些软件和哪些镜像”。命令用法见[开发指南](development-guide.md)，
跨仓库组合见[多层工作区](layers.md)，App 字段见[App 参考](app-architecture.md)。

## 目标与配置入口

目标写作 `<board>-<product>-<variant>`。board 是板型，product 是功能组合，variant 是 debug/release 等变体。
名称可以包含连字符；有效组合来自板卡配置的 `products` 与 `variants`，不由目录名猜测。

```bash
flange target list radxa-zero3w
flange --target radxa-zero3w-default-debug target show
flange --json --target radxa-zero3w-default-debug target show
```

`target show` 不切换保存的目标；`target select` / `lunch` 将选择写入工作区 `.flange/current_config`。
一次调用的选择顺序是 `--target` → 工作区保存状态 → `flange.toml` 的默认目标。

| 描述文件 | 作用 | 路径解释 |
| --- | --- | --- |
| `flange.toml` | 工作区、输出根、层集合、App 注册 | 相对清单目录 |
| `layer.toml` | 扩展层身份、依赖和策略提供者 | 相对所属层 |
| `components/rootfs/config.jsonnet` | 内建 Ubuntu 基线 | 工具基础层 |
| `components/distro/<name>/config.jsonnet` | 扩展层中的发行版基线 | 所选发行版所在层 |
| `components/platform/<platform>/config.jsonnet` | 平台公共能力 | 所属内容层 |
| `components/platform/<platform>/<soc>/config.jsonnet` | SoC（片上系统）事实 | 所属内容层 |
| `components/board/<board>/config.jsonnet` | 板级硬件与产品选择 | 所属内容层 |
| `components/packages/<name>/config.jsonnet` | 直接启用功能包的可选系统配置 | 功能包所在层 |

## 求值与覆盖

配置顺序为 **发行版 → platform → SoC → board → 直接启用 Package**，每个阶段内部按扩展层低到高组合。
共享 kernel/device-tree-overlay 基线由求值器加载。发行版在基础配置组合前确定；不能把 Ubuntu 包集合
无条件叠加到 Alpine 等其他发行版。

普通字段由后层替换；嵌套对象或数组追加使用 Jsonnet 的 `+:`。移除元素使用
`components/config/lib.libsonnet` 的 `without` 或按稳定身份过滤数组。
product/variant 通过 `std.extVar` 与 `if` 求值；最终交给 builder 的是 canonical JSON（规范化 JSON），
不含待执行的条件后缀、add/remove 操作或 Python 配置对象。

```jsonnet
// 板级产品配置片段：仅 desktop 产品增加软件包，保留继承字段。
local product = std.extVar('product');
{
  rootfs+: {
    packages+: if product == 'desktop' then ['mesa-utils'] else [],
  },
}
```

这是合并片段，不是可单独使用的完整板卡文件。完整示例见[扩展指南](extension-guide.md)。
Package 配置只按首次求值得到的直接启用列表加载一轮，不递归加载它新增的 Package。

## 硬件与构建字段

| 字段 | 当前语义 |
| --- | --- |
| `architecture.userspace` | 用户态 ABI：`aarch64` 或 `armhf` |
| `architecture.kernel` / `bootloader` | 对应 Kbuild ARCH，与用户态独立 |
| `sources.<name>` | 远端 `url` + 可选 branch/commit/recurse_submodules，或互斥的 local_path |
| `<component>.source` | `{name, subpath}` 引用命名源码，多个组件可共享下载 |
| `kernel.defconfig` / `bootloader.defconfig` | 有序字符串数组，包含 make target 或配置片段 |
| `kernel.config` / `bootloader.config` | 完整 `CONFIG_*` 名称到 Kconfig 右值；`n` 渲染为未启用 |
| `kernel.device_tree.directory` / `name` | 设备树目录和基础名，推导 `.dts` / `.dtb` |
| `kernel.device_tree.build_overlays` | 构建时合并进基础 DTB 的设备树覆盖 |
| `boot.overlays` | 引导期覆盖的来源与启用顺序，详见[设备树覆盖](hardware/device-tree-overlays.md) |
| `kernel.oot_sources` / `oot_modules` | 独立驱动源码及编译/安装声明 |
| `partitions.entries` | 分区几何与产物用途，见[启动与刷写](boot-and-flash.md) |

`local_path` 引用的用户源码不执行 Git reset 或重复应用仓库补丁；构建使用隔离副本与内容身份。
下载文件使用包含 `url`、可信 `sha256` 和可选 `filename` 的描述符，校验通过后才进入缓存。
普通相对路径与跨层 `layer.path()` 的区别见[路径与 import](layers.md#路径与-import)。

## rootfs 与账户

| 配置 | 行为 |
| --- | --- |
| `rootfs.url` / `sha256` | 基础归档及其可信摘要 |
| `package_sets` / `package_set` | 命名软件包集合与选择，求值后展开为 packages |
| `packages` | 发行版软件包名；Ubuntu 交给 APT，其他发行版由后端处理 |
| `install_recommends` | Ubuntu 默认 false；影响 Phase 1（基础阶段）缓存 |
| `custom_packages` | 选择 App 运行依赖闭包，由准确构建报告安装 |
| `extra_apt_sources` | 带唯一名称及密钥下载摘要的额外 APT 源 |
| `extra_debs` | Ubuntu 额外完整 DEB 下载；逐项校验 SHA256 |
| `extra_firmware` | 命名源码或校验下载，可用 `{src, dest}` 重命名 |
| `default_locale` | `{lang, language}`，写入 locale.conf 与 default/locale |
| `default_user` | 优先建立 UID 1000 与同名 GID 1000；编号冲突时构建失败 |
| `users` / `groups` | 用户、附加组和 sudo 策略；缺失的附加组按系统组建立 |
| `disable_root_login` | 锁定 root 登录并配置 SSH；不关闭独立 ADB 调试通道 |
| `default_session` | 默认用户的 X11/Wayland 会话；检查对应 desktop launcher 存在 |
| `gnome_remote_desktop_login` | 为默认用户配置 GNOME 远程登录；需要非空凭据 |

上述字段位于 `rootfs` 下；未声明语言或会话时保持发行版默认。用户的 sudo 可为 true、false
或 `{nopasswd: true}`，生成的 sudoers 在构建时校验。登录策略与 USB 调试策略应分别配置。
远程桌面首启凭据仅 root 可读，证书、私钥及后端设置全部成功后删除暂存凭据。

`extra_debs` 中 `force_overwrite` 只适用于确认过的文件冲突，默认仍拒绝冲突；
`hold_packages` 用于锁定实际已安装的相关包。不要把 Ubuntu 特定包名当作跨发行版依赖。
`ubuntu-desktop` 功能包的常亮与禁休眠策略只影响显式启用它的产品，见[桌面与图形](hardware/desktop.md)。

## 严格校验与诊断

系统对象拒绝未知字段、错误类型、失效 source 引用和互斥组合；布尔值不能写成字符串。
`packages_meta`、`boot.package_overlay_sources` 是解析器生成的字段，不能写进作者配置。
App YAML 也拒绝重复键。配置边界和消费者分别位于
[schema.py](../builder/config/schema.py)、[validate.py](../builder/config/validate.py) 与
[jsonnet.py](../builder/config/jsonnet.py)。

配置错误先修正文中给出的字段路径，再运行 `target show`；用 `plan` 看影响范围、`why` 看重建原因。
配置可解析不等于目标已经编译或硬件已通过验收。
