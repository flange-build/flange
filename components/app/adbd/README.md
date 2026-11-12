# adbd

Android Debug Bridge daemon，作为 [usbmoded](../usbmoded/README.md) 的 adb
能力后端。

本 App 提供 `/usr/bin/adbd` 预编译二进制，以及按目标 init 系统选择的服务：

| init | 服务入口 |
| --- | --- |
| systemd | `/lib/systemd/system/usbmoded-adbd.service` |
| OpenRC | `/etc/init.d/usbmoded-adbd` |

两者均声明 `auto_start: false`，默认由 usbmoded 的 ADB 能力管理启停。
FunctionFS 要求 daemon 在 gadget 绑定 UDC 前打开 ep0 并写入描述符，时序由 usbmoded 控制。
systemd unit 没有 `[Install]` 段，`systemctl is-enabled` 显示 `static` 是预期结果。
OpenRC 的安装策略不主动撤销用户此前启用的服务；应避免额外启动入口与 gadget 编排竞争。
OpenRC 脚本在成功启动后将 adbd 标记为 `hotplugged`（热插拔服务）及 `started`，
避免 usbmoded 在 `boot` 提前拉起它后，切换到 `default` 时被作为手工服务停掉。
该标记不增加开机启动入口，也不阻止显式停止或正常关机。

gadget 配置、场景定义、`usb-mode` CLI 与控制协议都属于 usbmoded，见
[usbmoded 的 README](../usbmoded/README.md)。

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
usbmoded 的断连恢复分支会重新启动 adbd 并绑定。因此允许 PID 改变、TCP 连接中断后重连；
验收要求是插拔后自动恢复，无需人工重启，不增加定时 watchdog（看门狗）。

- arm64：已部署 ROCK5B；旧版一次模拟断连即恢复超时，修复版连续 9 轮恢复成功。
  第 10 轮因图形会话自动挂起而中断，未计为通过；真实数据线插拔仍待确认。
- armhf：2026-11-12，在 Luckfox Pico Max（RV1106G3、SPI NAND）、
  `luckfox-pico-pro-max-alpine-release`、Alpine 3.24.4 / Linux 6.1.115+ 上验证
  USB 与 TCP ADB、正常重启后自动连接，以及连续 3 次模拟断连恢复。
  每次由 usbmoded 自动重启 adbd 并重新绑定 UDC，无需人工重启服务；二进制摘要与上表一致。
  真实数据线插拔尚未验证；首次烧录的长时间启动见 [Luckfox 板卡说明](../../../docs/boards/luckfox-pico-pro-max.md#首次启动与-adb-排障)。

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

## macOS USB 兼容性

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
