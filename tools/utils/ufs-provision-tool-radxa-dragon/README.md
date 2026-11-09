# Q8B UFS provision 独立工具

`provision.py` 对 Radxa Dragon Q8B（SC8280XP）的 UFS（通用闪存存储）执行
provision（存储布局初始化）。分享时只需发送这一个脚本；它不导入 flange 模块，
不读取仓库配置、flash 或 bootloader 产物，也不需要 Docker、lunch、pip 包或 .NET。

## 直接运行

宿主要求：Python 3.12+，Linux 或 macOS，x86_64 或 ARM64。
首次运行需联网下载约 32 MiB 工具包及 loader（设备端加载程序）、布局 XML。
macOS 工具包自带 libusb（USB 通信库）；Linux 需要系统提供 libusb，
Debian/Ubuntu 可执行 `sudo apt install libusb-1.0-0`。Linux 还需要当前用户具有 USB
设备访问权限；权限不足时，可配置 udev 规则或使用 `sudo python3` 执行脚本。

1. 将 Q8B 按板卡说明置于 EDL（紧急下载模式），USB 标识应为 `05c6:9008`。
   只连接一块待初始化 Q8B，关闭其他正在访问它的刷写工具。
2. 在收到脚本的目录运行：

   ```bash
   python3 provision.py
   ```

3. 脚本自动下载、校验资源，显示布局与实际命令；输入 `Q8B` 后执行初始化。
4. 成功后断电并重新进入 EDL，再使用你自己的刷写工具写入系统镜像。

该操作可能清除 UFS 上的数据，已有配置锁可能阻止重新 provision。
脚本仅通过 USB 标识检查 EDL 设备数量，不能自动证明设备型号，必须确认是 Q8B。
脚本不会自动写入系统镜像或 SPI 固件，也不会在失败后自动重试硬件操作。

## 布局与参数

默认 `lun0-only` 使用单用户 LUN（逻辑单元），与 flange 当前 Q8B 默认初始化布局一致。
`qcom` 使用现有 flash 中的官方 LUN 0–7 布局：

```bash
python3 provision.py --profile qcom
```

只下载与检查宿主运行环境，不连接设备：

```bash
python3 provision.py --prepare-only
```

准备资源并显示实际命令，不连接设备：

```bash
python3 provision.py --dry-run
```

明确确认型号及数据风险后，可用于非交互执行：

```bash
python3 provision.py --yes
```

通过 `--help` 查看全部参数。设备未进入 EDL、有多个 EDL 设备、资源校验失败或
edl-ng 失败时返回非零退出码。设备型号确认不能代替检查物理连接。

## 离线分享

默认下载缓存为 `~/.cache/q8b-ufs-provision/`。使用明确目录预下载：

```bash
python3 provision.py --prepare-only --cache-dir ./ufs-cache
python3 provision.py --prepare-only --profile qcom --cache-dir ./ufs-cache
```

第二条仅在需要 `qcom` 布局时执行。将 `provision.py` 和整个 `ufs-cache` 目录一起分享，
接收者运行：

```bash
python3 provision.py --offline --cache-dir ./ufs-cache
```

缓存包含所有支持架构的工具包；接收者仍须满足 Python、系统运行库和 USB 权限要求。
离线模式不会联网；缓存缺失或损坏会报错。每次执行重新校验 SHA-256（内容摘要），
并在临时目录提取工具，退出时清理临时执行文件。`--dry-run` 打印的临时路径随后也会清理。
使用 sudo 时建议同时指定绝对 `--cache-dir`，避免切换用户后重复下载。

## 固定资源与维护

资源地址和 SHA-256 全部内置于脚本，运行时无需本 README 或任何配置文件。

- [edl-ng v1.6.0 官方下载](https://dl.radxa.com/dragon/q6a/images/edl-ng-dist-v1.6.0.zip)
  提供宿主工具；[上游说明](https://github.com/strongtz/edl-ng)列出通信方式与运行要求。
- [Q8B UFS loader](https://github.com/armbian/qcombin/blob/f2d55c46dcbe2af57dc400658cd14e70cd8baa79/Makena/prog_firehose_ddr.elf)
  在本工具中保存为 `prog_firehose_ufs.elf`，用于区别 SPI loader。
- [单 LUN 布局](https://github.com/armbian/qcombin/blob/f2d55c46dcbe2af57dc400658cd14e70cd8baa79/Makena/radxa-dragon-q8b/provision_ufs31_lun0_only.xml)
  与 [官方多 LUN 布局](https://dl.radxa.com/q6a/images/android/provision_ufs31.xml)
  沿用现有 Q8B flash 配置。

工具包摘要由本次实际下载计算固定；固件及 XML 摘要与现有 Q8B 板级配置一致。
更新资源时必须重新核验内容、摘要及平台兼容性，不能跳过校验。
本脚本采用 Apache-2.0；下载的第三方工具和固件保留各自许可，
edl-ng 包中的 LICENSE 随工具提取，分发缓存时应保留原始完整压缩包。

## 验证范围

`test_provision.py` 使用 Python 标准库验证下载校验、离线失败、设备数量保护、
预览不操作设备及 provision 命令和失败状态传播：

```bash
python3 -m unittest discover -s . -p 'test_provision.py' -v
```

开发验证包括 macOS ARM64 上真实下载、两种布局的摘要校验与离线预览。
未对实板执行 provision；Linux 与其他宿主架构尚待实机验证。
