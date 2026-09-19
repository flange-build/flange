# USB gadget 子系统（usbmoded）

本 App 承载完整的 USB gadget 子系统。App 名沿用历史上的 `adbd`，但实际
内容已远超 adb —— adb 只是其中一个原子能力。

> 本 App 在 2.0.0 中以三层架构的 Python 服务替换了原先的 `usbdevice`
> shell 脚本。脚本中积累的 13 项平台竞态知识已逐条迁移，对照表见
> `openspec/changes/add-usb-mode-switching/race-checklist.md`；
> **修改 L1 之前请先读它**。

## 架构

```
L3  场景层 (scene.py)        场景 = 能力集合 + 参数 + role，切换编排
L2  原子能力层 (capabilities/) 每个 USB function 一个能力，统一接口 + 参数
L1  gadget 核心 (gadget/udc/configfs)  configfs 原语、UDC 生命周期、竞态处理
```

L1 不认识任何具体 USB function —— 所有 function 相关行为都通过
`capability.Capability` 接口调用。这条约束有自动化校验（`tests/test_usbmoded.py`
与变更任务 2.11），是分层是否真正成立的硬指标。

daemon（adbd、mtp-server）的生命周期交给 systemd，不自制保活循环 ——
后者的状态判断读写不对称曾在 ROCK 5B 上堆积 360+ 并发循环、USB 每 2 秒
断连一次。

## 能力清单

按内核要求的排列顺序：

| 能力 | configfs 实例 | 参数 | 说明 |
|---|---|---|---|
| `ncm` / `rndis` | `ncm.gs0` / `rndis.gs0` | — | USB 网卡，二者互斥 |
| `uac1` / `uac2` | `uac1.gs0` / `uac2.gs0` | — | 音频，二者互斥 |
| `uvc` | `uvc.gs6` | `formats` | 摄像头。**不含取流 daemon**（沿用既有缺口） |
| `adb` | `ffs.adb` | `tcp_port` `shell` `mountpoint` | 调试通道 |
| `ntb` | `ffs.ntb` | `mountpoint` | 自定义 FunctionFS 通道 |
| `ums` | `mass_storage.0` | `file` `size` `fstype` `ro` `auto_mount` `mountpoint` | U 盘 |
| `mtp` | `mtp.gs0` | `device` | 媒体传输 |
| `acm` | `acm.gs6` | — | CDC 串口 |
| `hid` | `hid.usb0` | `protocol` `subclass` `report_length` `report_desc` | 默认标准键盘 |

## 配置

均为 YAML，按文件名顺序加载、**按键合并**（App 层 `10-`，板级 `20-`）。
这与旧的 `usbdevice.conf` 整文件覆盖语义不同：后者会让 App 层新增的键在
各板默默丢失，实测曾导致 7 个键在 12 份板级配置中各重复一遍。

| 路径 | 内容 |
|---|---|
| `/etc/usbmode/gadget.d/*.yaml` | VID/PID、产品名、厂商名、gadget group、默认场景 |
| `/etc/usbmode/scenes.d/*.yaml` | 场景定义 |
| `/etc/usbmode/persist.yaml` | 持久化场景（由 `usb-mode set -p` 写入） |

十六进制值一律写成带引号的字符串。YAML 1.1 会把裸写的 `0x2207` 解析成
整数 8711，加载层虽能兼容，但写成字符串才能做到配置文件所见即 configfs 所得。

### 场景定义

```yaml
scenes:
  debug:
    capabilities: [adb]
    params:
      adb: {tcp_port: 5555, shell: /bin/bash}
  storage:
    capabilities: [ums]
    params:
      ums: {file: /userdata/ums_shared.img, size: 256M, fstype: vfat}
  host:
    role: host        # 只声明 role，不改变能力集合
```

能力集合与 role 是正交维度，场景可以只声明其一。

## 命令行

```
usb-mode list              列出可用场景与本平台能力
usb-mode get               当前场景 / 能力 / role / UDC 与枚举状态
usb-mode set <scene>       切换（重启后回到默认场景）
usb-mode set -p <scene>    持久化切换
usb-mode reset             清除持久化，回到板级默认场景
usb-mode confirm           确认当前场景，取消自动回滚
```

### 失联风险

切换到不含 `adb` 的场景（或 `role: host`）会切断 adb 通道本身。服务对此有
自锁保护：检测到会切断通道时启动回滚计时器，未在窗口内 `usb-mode confirm`
则自动切回原场景。

**`-p` 持久化到这类场景需要额外的 `--force`** —— 否则设备每次开机都会进入
无法远程访问的状态，只能靠串口或重新刷写恢复。

## 控制协议

`/run/usbmode.sock` 上的 **JSON-RPC 2.0**，行分隔传输 —— `socat` / `nc` 可直接调试：

```sh
echo '{"jsonrpc":"2.0","method":"scene.get","id":1}' | socat - UNIX-CONNECT:/run/usbmode.sock
```

| 方法 | 参数 | 权限 |
|---|---|---|
| `scene.list` | — | 查询 |
| `scene.get` | — | 查询 |
| `scene.set` | `scene`、`persist`、`force` | 变更 |
| `scene.reset` | — | 变更 |
| `scene.confirm` | — | 变更 |
| `config.reload` | — | 变更 |

支持规范的通知（无 `id`，不回响应）与批量（数组）。错误码：`-32700`..`-32603`
为协议层标准错误；领域错误用规范保留给服务端的 `-32000`..`-32099`：

| 码 | 含义 |
|---|---|
| `-32000` | 权限不足 |
| `-32001` | 场景未定义 |
| `-32002` | 能力冲突 |
| `-32003` | 切换失败（`data.step` 指出失败步骤） |
| `-32004` | 平台不支持 role 切换 |
| `-32005` | 配置错误 |

按码分支即可，不必解析消息文本。

授权基于 `SO_PEERCRED`：查询类命令对所有本机进程开放，变更类命令要求
`uid == 0` 或属于 `usbmode` 组。该组由服务启动时幂等创建，**不会有任何
用户默认加入** —— 授予普通用户需显式 `usermod -aG usbmode <user>`。

---

## adbd 二进制来源：ADB 36.0.1 standalone（2026-08-31）

- 来源：[happyme531/standalone-linux-adbd](https://github.com/happyme531/standalone-linux-adbd)（nmeum/android-tools 的 daemon 扩展，AOSP ADB 36.0.1 源码 + CMake 静态构建）
- 基线 tag：`v36.0.1-linux.2`，commit `bdb5cdc4b516b3bc71fd2b805bc36190041a9393`
- 本地补丁：[0032-adb-fix-worker-exit-on-glibc.patch](patches/0032-adb-fix-worker-exit-on-glibc.patch)
- 两种架构均在 `flange-build:latest` 的 `linux/amd64` Docker 容器内使用 GCC 13.3 交叉编译，
  经目标架构 `strip` 裁剪及 `readelf -d` 检查，无 `DT_NEEDED` 动态依赖。
- 特性：静态链接（无 DT_NEEDED）、FunctionFS USB + TCP + VSOCK 并行、
  兼容 Rockchip `usbdevice` 的 `ADB_TCP_PORT` / `ADBD_SHELL` 环境变量
- **注意**：无认证（authentication disabled），与旧 vendor adbd 安全模型一致，
  勿将 USB / 5555 端口暴露给不可信主机

| 文件 | SHA256 |
| --- | --- |
| `bin/adbd-arm64` | `22ac697d0eb674d74874b162021fccd2421f360368e2b6968f219449b9b8b22b` |
| `bin/adbd-armhf` | `96414539827ea44c5165cf7b9ed905ad7dee4f93582e1823928e48f46cb62a3c` |

## USB 插拔后 offline 修复

上游 `UsbFfsConnection::StopWorker()` 用 `pthread_kill(worker, 0)` 返回 `ESRCH`
判断线程退出。当前 glibc 对已退出但尚未 `join`（回收）的线程仍返回成功，导致 monitor
永久等待，主线程与 USB open 线程也无法继续；重插后设备保持 offline。
补丁复用 libbase ScopeGuard（作用域退出清理器），在 worker 所有退出路径设置原子完成标记，
保留中断阻塞 AIO（异步输入输出）的信号与正常 `join`，使 FunctionFS 可以重新打开。
参见 [glibc 官方行为说明](https://sourceware.org/pipermail/glibc-cvs/2021q3/074935.html)。

ROCK5B 的 vendor kernel 6.1.115 在重新打开 ep0 时仍会自动解绑 UDC（USB 设备控制器），
现有 `usbdevice` 恢复分支会重新启动 adbd 并绑定。因此允许 PID 改变、TCP 连接中断后重连；
验收要求是插拔后自动恢复，无需人工重启，不增加定时 watchdog（看门狗）。

- arm64：已部署 ROCK5B；旧版一次模拟断连即恢复超时，修复版连续 9 轮恢复成功。
  第 10 轮因图形会话自动挂起而中断，未计为通过；真实数据线插拔仍待确认。
- armhf：已完成交叉编译及静态依赖检查，本次修复产物尚未做运行验证。

宿主机回归命令如下，使用 `adb devices` 中的目标 USB 序列号；该检查会短暂断开整个 gadget：

```bash
set -xe
python3 tests/adbd_usb_reconnect.py --serial 'USB序列号' --cycles 10 --allow-pid-change
```

## 重建方法

从 flange 仓库根目录新检出源码，并在首次构建前放入补丁：

```bash
set -xe
git clone --branch v36.0.1-linux.2 --depth 1 \
    https://github.com/happyme531/standalone-linux-adbd.git .build/sources/standalone-linux-adbd
test "$(git -C .build/sources/standalone-linux-adbd rev-parse HEAD)" = \
    bdb5cdc4b516b3bc71fd2b805bc36190041a9393
cp components/app/adbd/patches/0032-adb-fix-worker-exit-on-glibc.patch \
    .build/sources/standalone-linux-adbd/patches/adb/
```

上游脚本负责获取所需子模块并在首次 CMake 配置时自动 `git am` 补丁。
若源码已应用上游补丁，须先在该源码目录执行
`git -C vendor/adb am "$PWD/patches/adb/0032-adb-fix-worker-exit-on-glibc.patch"`；
已应用本地补丁的目录不要重复执行。无需修改 flange 构建框架。

将仓库挂载到 `linux/amd64` 平台的 `flange-build:latest` 容器，在容器内进入上述源码目录。
arm64 使用自带 toolchain（工具链配置）；armhf 从它替换工具链三元组与处理器名称：

```bash
set -xe
sed -e 's/aarch64-linux-gnu/arm-linux-gnueabihf/g' \
    -e 's/CMAKE_SYSTEM_PROCESSOR aarch64/CMAKE_SYSTEM_PROCESSOR arm/' \
    cmake/toolchains/aarch64-linux-gnu.cmake > cmake/toolchains/arm-linux-gnueabihf.cmake
CMAKE_TOOLCHAIN_FILE="$PWD/cmake/toolchains/aarch64-linux-gnu.cmake" \
    scripts/build-linux-adbd.sh build/linux-adbd-aarch64
CMAKE_TOOLCHAIN_FILE="$PWD/cmake/toolchains/arm-linux-gnueabihf.cmake" \
    scripts/build-linux-adbd.sh build/linux-adbd-armhf
aarch64-linux-gnu-strip --strip-unneeded build/linux-adbd-aarch64/vendor/adbd
arm-linux-gnueabihf-strip --strip-unneeded build/linux-adbd-armhf/vendor/adbd
readelf -d build/linux-adbd-aarch64/vendor/adbd
readelf -d build/linux-adbd-armhf/vendor/adbd
```

脚本默认启用 `ADBD_ONLY`、`FULLY_STATIC`、`USB` 及内置依赖。确认两份产物均无 `NEEDED`
条目后，将它们分别复制到 `components/app/adbd/bin/adbd-arm64` 与 `adbd-armhf`，更新摘要。

## 历史：为什么替换旧 vendor adbd

旧 vendor adbd（协议 1.0.28，Android 5 时代）在 macOS adb host（1.0.41+）
claim interface 时必然崩溃：macOS 版 adb 在 claim 后发预防性
`ClearFeature(HALT)`，内核（mainline 语义）会终止 FunctionFS 上 pending 的
bulk 读并返回 `EPIPE`；旧 adbd 将其视为 USB 断开，关闭 ep0 → configfs 自动
unbind UDC → 设备从总线消失 → host 重试 → 无限循环（实测 29 轮不收敛），
`adb devices` 永远为空。Linux 版 adb host 不发 Clear Halt，故 Linux 主机下
未暴露。

AOSP 于 Android 10 时代修复（`daemon/usb.cpp`：首包前的 read `EPIPE` →
resubmit 而非拆接口），ADB 36.0.1 含此修复，已在 rock5b + macOS 实测：
枚举即连、冷启动零干预可用、push ≈85 MB/s（USB 2.0 高速）。

2026-08-27 首次采用上游 release（2026-07-22）的 arm64 资产
`adbd-36.0.1-linux-aarch64-static`，SHA256 为
`e7876da9ddf2fd74176de83b7ff276252292c0e5e1150565d53a812c6eab2442`。
上游未发布 armhf 资产，当时在 ROCK5B Ubuntu 24.04 上用 GCC 13.3.0 交叉编译，
旧产物 SHA256 为 `840bc2410ad025dd2f008061e5461c88e9743b630c0ecd91732f50705fb8a6fa`，
只验证过 aarch32 用户态 TCP 监听、连接及 shell。这些历史验证不代表本次产物的运行结果。
