# Arduino UNO Q

UNO Q 使用 QRB2210 Linux 主处理器和 STM32U585 微控制器（MCU）。flange 的目标是提供
Ubuntu 系统及完整 Arduino 工具链、Router/Bridge、App Lab 和 Bricks。已完成离线实现、组件构建和镜像组装验证，
已完成首次 debug 启动、ADB、Wi-Fi 联网和部分运行时热修复验证，完整实板验收仍未完成；最新证据见 [OpenSpec 验证记录](../../openspec/changes/add-qrb2210-arduino-uno-q/verification.md)。

2026-09-09 已通过标准 Docker 环境端到端构建 default-debug 成套镜像，包含首轮实板热修复。
最终交付的烧入和冷启动验收由用户执行；release 的离线基线不代表这批 debug 修复已完成 release 实板验收。

公共构建器改动、可复用新增能力及板级实现的边界，见[适配影响清单](arduino-uno-q-integration.md)。

当前已知限制：qbootctl 启动成功确认尚未完成，反复重启仍可能耗尽 A/B 尝试次数；
QDL 在写完后的复位或 USB 收尾阶段曾出现等待不退出，具体阻塞点待定位。
当前 CPUidle 驱动也未注册；音频声卡/UCM 可枚举但存在启动路由报错，实际音频未验证。
这些问题和未完成的硬件验收需在合入评审中明确保留，不能声明完整生产可用。


## 目标与构建

2GB/16GB 与 4GB/32GB 共用一个板级配置，不需要选择不同内核或 rootfs。
刷写程序读取设备真实分区表处理容量和 userdata 起点，不从内存规格推测存储位置。

在仓库中按[开发指南](../development-guide.md)准备 Docker 和大小写敏感构建目录，然后执行：

```bash
source envsetup.sh
lunch arduino-uno-q-default-debug
flange plan image
flange build image
flange flash --list
```

发布变体为 `arduino-uno-q-default-release`。debug 默认用户及密码均为 `arduino`；release 未设置
可登录密码，部署前应通过产品配置准备登录凭据。两个变体都保留 Arduino 所需的 UID 1000。
第一次构建会下载固定源码、固件、工具链和 OCI（容器镜像）资源，需要网络和足够构建空间。

组件也可以单独构建；构建引擎自动补齐依赖：

```bash
flange build kernel
flange build bootloader
flange build rootfs
flange build boot
flange build image
```

`boot` 依赖 rootfs 生成的 initramfs（初始内存文件系统）及 ARM64 systemd-boot，不能只替换 Image
而留下不匹配的 modules/initrd。组件变化后重新构建 `image`，以刷新发布包和摘要。

| 组件产物 | 用途/物理分区 |
| --- | --- |
| `kernel/Image`、DTB、modules、config | Linux 内核及匹配模块；不是 `boot_a` 的内容 |
| `bootloader/uboot-boot.img` | 含 U-Boot 的 Android boot 容器，写 `boot_a`、`boot_b` |
| `boot/boot.img` | 含 systemd-boot、Image、DTB、initrd 的 EFI 文件系统，写 `efi` |
| `rootfs/rootfs.img` | Ubuntu 系统，写 `rootfs` |
| `rootfs/userdata.img` | 挂载在 `/home/arduino` 的用户数据，写 `userdata` |
| `image/flash-bundle/` | 完整 QDL（高通下载工具）发布包，包含 XML/GPT、固件与 SHA256 清单 |

产物位于当前目标的 `.build/target/arduino-uno-q/default/<variant>/`；自定义 build_dir 时以 CLI 输出为准。
Linux 启动顺序为 Qualcomm 前级固件 → ABL → U-Boot → EFI systemd-boot → kernel/initrd → Ubuntu。

## 宿主刷写

仓库已包含 Arduino `qdl-packing v2.4-26`，覆盖 macOS/Linux 的 ARM64 和 x86_64，
`flange flash` 自动选择 `tools/<macos|linux>/qdl/<arch>/qdl`，无需额外安装。
原有 `tools/<macos|linux>/qdl/qdl` 本地覆盖路径及 PATH 回退仍保留。USB 不传入构建容器。
实板首次验证前，应记录官方系统和 GPT，并保存官方恢复工具所需资源及自己的用户数据备份。

按 [Arduino 官方恢复说明](https://github.com/arduino/arduino-flasher-cli)进入 EDL（紧急下载模式）。
只连接目标 UNO Q；读取 GPT 后 QDL 会复位，保持 JCTL EDL 跳线，让同一设备重新枚举后继续写入。
程序绑定产品字符串 `_SN` 中的串号，核对主备 GPT、分区身份和容量后才写镜像。
不接受无可绑定串号、多 EDL 设备或损坏/未知 GPT；后者应先使用官方工具恢复。
设备主备 GPT、实际容量、发布包/执行计划摘要和 QDL 日志保存在目标目录的 `flash-records/unoq-*/`。
记录中的 `written` 只代表工具完成写入，仍需单独验证读回、启动和功能。
交互终端实时显示 QDL 分区进度和百分比；重定向时保留普通消息。QDL 输出同时持续写入
本次记录目录的 `read-gpt.log`、`program.log`，失败和超时保留已有日志且不自动重试。
镜像摘要复核和 GPT 读取均有阶段提示；摘要复核期间尚未开始写入。

确认发布包匹配目标后，全量刷写命令为：

```bash
flange flash --yes
```

全量写入会替换 rootfs、userdata 和列入发布包的启动固件，并从官方 GPT 模板恢复成对 A/B 分区的
启动属性，清除旧不可启动/重试耗尽状态；不改其他属性、实板 GUID 或布局，不代写启动成功。
官方 XML 中空 filename 的校准及持久化区域被保留。
`--yes` 是现有 CLI 对受保护固件写入的明确确认。完成后移除 JCTL 跳线并重新上电。

单刷使用 `flange flash --list` 中的物理分区名，例如：

```bash
flange flash efi
flange flash rootfs
flange flash boot_a --yes
```

单刷不重写 GPT，也不顺带重写 userdata。内核变更通常需要配套更新 rootfs 和 efi；仅更新 `boot_a`
不会同步 `boot_b`。跨运行时版本更新还需迁移 userdata 中的 Arduino core/Bricks 资源，不能假设旧资源
自动与新 rootfs 兼容。全量写 userdata 前务必保留自己的 sketch、应用和模型。

UNO Q 不支持 `--no-reboot`，因为 QDL 会自行复位。它也不使用现有 QCS6490 的 UFS/SPI 初始化或
`--raw` 整盘流程；独立 flange ADB recovery 尚未启用。

## Arduino 运行时

运行时使用 Ubuntu 原生系统库，固定并校验 Arduino 二进制、Zephyr core、上传工具、Bridge 库和容器摘要。
不安装会替换 flange 内核的 Debian `arduino-unoq` 元包。
构建门禁检查 ELF（可执行文件格式）依赖，并实际编译一个 MCU sketch；这不代表上传及板间通信已经验证。

设备端可检查：

```bash
systemctl status arduino-router arduino-app-cli flange-unoq-data rmtfs tqftpserv adbd
arduino-cli core list
journalctl -b -u arduino-router -u arduino-app-cli -u flange-unoq-data
```

Linux 首启、重启及 rootfs 更新均不自动覆盖 MCU sketch。确实需要初始化 MCU 时，以 `arduino` 用户执行
`/usr/lib/flange/unoq/mcu-initialize --replace-mcu-firmware`；该操作会替换 MCU 固件及 sketch。
相同版本初始化成功后再次执行会跳过；确需重新初始化时追加 `--force`。

userdata 初始为 3 GiB，首启核对挂载点和 UUID 后扩展 ext4 至现有分区容量，不改变 GPT。
预装五种 UNO Q 容器服务及 EI runner 的 10 个模型；两个可选 GGUF 模型仍按固定版本联网下载。
板端 ADB 由独立运行时组件提供，使用 Arduino 补丁版 `adbd` 和 Ubuntu 原生 Android 库，
并配置 ADB/USB 串口组合设备；USB 枚举、重连及双角色切换仍需实板验收。
云服务需要用户自己的网络和凭据。资源锁、版本和离线范围详见
[运行时说明](../../components/packages/arduino-unoq-runtime/README.md)。

## 实板验收清单

以下为最终烧入后的验收范围。此前热修复系统上的部分验证已经通过，仍须对最终镜像复验；
每项记录镜像摘要、设备状态、命令输出及失败日志。操作步骤见[本轮交付与验收](arduino-uno-q-handoff.md)。

- 官方系统基线、板卡身份和可恢复备份；EDL 恢复、全量刷写及 efi/rootfs/boot_a 单刷。
- 冷启动、重复重启、正确内核/模块/initrd、独立 userdata 挂载、启动成功标记及更新后的数据保留。
- Wi-Fi 扫描/连接、Bluetooth、USB Host、ADB 重连与实际使用的供电路径。
- GPU/桌面、USB-C 显示、音频输入输出；摄像头与载板按实际配件逐项记录。
- MCU 编译上传、Router 双向 RPC（远程过程调用）、重复重启后 sketch 保留。
- App Lab 连接与应用创建，Bricks 运行/停止/恢复，以及离线容器和模型的可用范围。

完成容器构建与全部实板验收后，才同步正式能力规格并归档本次 OpenSpec 变更。

## 上游基线

- [Arduino Linux kernel](https://github.com/arduino/linux-qcom)：`122c2c22d838ca826e7f4e7360df96fb4e8f7ad2`。
- [Arduino U-Boot](https://github.com/arduino/u-boot)：`8008ca96a4dc53ddb3e51b96ea7e86d881ab7969`。
- [官方系统构建](https://github.com/arduino/arduino-deb-images)与[官方恢复工具](https://github.com/arduino/arduino-flasher-cli)。
- 固件下载与 SHA256 在板级配置中；运行时资源、core 及容器摘要在 `components/packages/arduino-unoq-runtime/` 的锁文件中。
