# Arduino UNO Q

UNO Q 使用 QRB2210 Linux 主处理器和 STM32U585 MCU（微控制器）。flange 提供 Ubuntu、
Arduino 工具链、Router/Bridge、App CLI、Bricks 及离线运行资源。
默认 debug 镜像已完成全量刷写、重复启动、启动成功标记和 Linux 到 MCU 的上传/RPC 验证；
下方验证表限定实际完成范围，release 和 App Lab 桌面端的完整流程不能由此推定。

[板卡索引](README.md) · [运行时与资源版本](../../components/packages/arduino-unoq-runtime/README.md)

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

需要保留设备上的用户数据时，追加 `--keep-userdata`：照常写入启动固件、efi、rootfs 并恢复 A/B
启动属性，但跳过 userdata 镜像，实板 userdata 的起点、GUID 和内容不变：

```bash
flange flash --yes --keep-userdata
```

若只是启动槽位重试耗尽（boot_a 不可启动）而系统本身完好，可只重写主备 GPT 的 A/B 启动属性，
不写任何分区镜像：

```bash
flange flash --reset-slots --yes
```

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
构建检查 ELF（可执行文件格式）依赖并编译 MCU sketch；Linux 到 MCU 的上传及板间通信另有下表实机结果。

设备端可检查：

```bash
systemctl status arduino-router arduino-app-cli flange-unoq-data rmtfs tqftpserv adbd
arduino-cli core list
journalctl -b -u arduino-router -u arduino-app-cli -u flange-unoq-data
```

Linux 首启、重启及 rootfs 更新均不自动覆盖 MCU sketch。确实需要初始化 MCU 时，以 `arduino` 用户执行
`/usr/lib/flange/unoq/mcu-initialize --replace-mcu-firmware`；该操作会替换 MCU 固件及 sketch。
相同版本初始化成功后再次执行会跳过；确需重新初始化时追加 `--force`。

userdata 初始为 3 GiB，rootfs 镜像也小于分区；每次启动核对挂载点、LABEL/UUID 和 eMMC 设备后，
在线把两者的 ext4 扩展至现有分区容量，不改变 GPT。

release 与官方镜像一致，`arduino` 用户构建时不设口令（空口令且立即过期），首次用 App Lab 连接时会引导
设置口令；在此之前 SSH 不能用该账户登录（sshd 不接受空口令），ADB 不受影响。
debug 保留研发默认口令 `arduino`，不强制过期，因此 App Lab 不会进入首次设置口令流程。`arduino` 属于 `sysupgrade` 组，
App Lab 可免密修改板名。arduino-router 停止或重启时会经 GPIO 38 复位 MCU，与官方行为一致。
离线容器导入失败或运行时锁不匹配时，`flange-unoq-data` 失败但 App CLI 仍会启动，
可用 `journalctl -u flange-unoq-data` 查看原因。
预装五种 UNO Q 容器服务及 EI runner 的 10 个模型；两个可选 GGUF 模型仍按固定版本联网下载。
板端 ADB 由独立运行时组件提供，使用 Arduino 补丁版 `adbd` 和 Ubuntu 原生 Android 库，
并配置 ADB/USB 串口组合设备；USB 枚举、重连及双角色切换仍需实板验收。
云服务需要用户自己的网络和凭据。资源锁、版本和离线范围详见
[运行时说明](../../components/packages/arduino-unoq-runtime/README.md)。

## Waveshare 10.1" DSI 触摸屏（waveshare-display-10.1a）

适配 UNO Q 插在 [Waveshare UNO-Q-DSI-TOUCH-10.1A](https://docs.waveshare.net/UNO-Q-DSI-TOUCH-10.1A)
（Arduino media carrier 兼容载板，经 JMEDIA/JMISC 板对板连接）上的组合：

```bash
lunch arduino-uno-q-waveshare-display-10.1a-debug
flange build
flange flash --yes
```

- 等价于官方 `arduino-linux-config carrier enable media-carrier display=10-dsi-touch-a
  camera0=none camera1=none`，但在构建期用 fdtoverlay 合成 DTB，不依赖运行期工具。
- DSI0 只能接一路：以 `qrb2210-arduino-imola-base.dtb` 为底，**不含 USB-C 视频输出**。
- overlay 合并顺序为面板 → carrier-media → 板私有触摸修正，不可对调：两个官方 overlay 各带
  一份 pca9555 节点，carrier-media 不在最后时 LED 引用的 phandle 悬空，`leds-gpio` 整组
  （含板载 LED）probe 失败。
- 显示默认顺时针旋转 90°（1280×800 横屏），由 LightDM display-setup 脚本在检测到该面板时执行
  `xrandr --output DSI-1 --rotate right`。
- GT9271 经 CCI 读配置返回 -EOPNOTSUPP，驱动退回 0..4095 默认范围；板私有 dtso 声明 800×1280
  原始尺寸，并以 `touchscreen-inverted-x` + `touchscreen-swapped-x-y` 在内核与显示同向旋转。
  官方 udev 近似校准矩阵依赖 fb0 先于触摸出现，此时被板级 udev 规则置为单位矩阵。
- 改方向须同时修改 dtso 的触摸属性和 `waveshare-display-setup` 的 `--rotate` 参数。
- 摄像头接口未启用；4 组 RGB LED 为 `/sys/class/leds/media-carrier:{red,green,blue}{1..4}`。

实板（debug）已验证：横屏显示、触摸四角与拖动对齐、12 个载板 LED 与板载 LED 均注册、
无失败单元。音频与摄像头未验证。

## 已验证结果与限制

2026-11-08，`arduino-uno-q-default-debug` 在 4GB/32GB 实板完成以下验证；
写入记录中的 36 项均为 `written`。该状态表示工具写入完成，启动及应用结论来自后续独立检查。

| 范围 | 已确认结果 |
| --- | --- |
| 完整镜像 | 全量刷写后启动，无失败 systemd 单元；rootfs 从约 9 GiB 扩展到约 9.8 GiB，userdata 独立挂载 |
| A/B 启动成功 | qbootctl 服务成功标记 boot_a，最终属性为 `0x77`，boot_b 为 `0`，再次重启保持成功状态 |
| Arduino 账户与容器 | debug 口令不强制过期，用户属于 sysupgrade 组；首启导入五种容器，保留官方标签；App CLI `/v1/version` 返回 0.13.0 / HTTP 200 |
| MCU 初始化 | `mcu-initialize --replace-mcu-firmware` 经 SWD 识别 STM32U585，RDP 0、TrustZone 关闭，执行成功 |
| MCU 编译与上传 | `arduino:zephyr:unoq` 的 Bridge 验证 sketch 编译、上传到 `0x08100000` 成功 |
| Bridge RPC | 官方 python-apps-base 0.12.0 环境下 echo 三次正确，计数返回 18、19、20 |
| 复位与调试 | Router 重启复位 MCU，约 6 秒后恢复 RPC；arduino-reset 可用；OpenOCD/GDB 0.16.8 的 halt、stepi、detach 后 RPC 继续工作 |

官方 251020 ABL 在本次实际 DTB 中未提供槽位参数。`mark-boot-success` 在这种情况下仅接受 GPT 中
**唯一可启动的 boot 槽位**；另一槽必须完全不可启动，存在歧义就拒绝标记，不能把优先级猜测当作当前槽位。
该回退曾把 boot_a `0x2f` 标记到 `0x67` 并通过重启，随后最终完整镜像的属性稳定为 `0x77`。

此前 debug 实板已验证基本启动、ADB 与 Wi-Fi 联网。Waveshare 产品的显示、触摸和 LED 结果见上节。
这些结果不扩大为以下未完成项：

- PC 端 ADB 上传、网络上传，以及 App Lab 桌面端设备发现、首次设置和完整应用流程。
- 全部 Bricks、模型、Bluetooth 配对、USB 双角色/重连组合和每种供电方式的验收。
- 音频实际输入输出；目前声卡/UCM 可枚举，但存在启动路由报错。
- CPUidle 驱动仍未注册，PSCI 曾出现 `-517`；不能声明低功耗功能完成。
- release 实板验收、所有容量版本及长期压力测试。

QDL 曾在写完后的复位/USB 收尾阶段不退出；2026-11-08 的完整写入已完成，
但这不足以证明该偶发问题对所有宿主与 USB 路径已消失。遇到等待时保留 `program.log` 和 flash-records，
先确认写入阶段与设备状态，避免直接重复刷写。

## 上游基线

- [Arduino Linux kernel](https://github.com/arduino/linux-qcom)：`122c2c22d838ca826e7f4e7360df96fb4e8f7ad2`。
- [Arduino U-Boot](https://github.com/arduino/u-boot)：`8008ca96a4dc53ddb3e51b96ea7e86d881ab7969`。
- [官方系统构建](https://github.com/arduino/arduino-deb-images)与[官方恢复工具](https://github.com/arduino/arduino-flasher-cli)。
- 固件下载与 SHA256 在板级配置中；运行时资源、core 及容器摘要在 `components/packages/arduino-unoq-runtime/` 的锁文件中。
