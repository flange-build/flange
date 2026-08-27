# adbd 预编译二进制来源

## adbd-arm64 — ADB 36.0.1 standalone（当前）

- 来源：[happyme531/standalone-linux-adbd](https://github.com/happyme531/standalone-linux-adbd)（nmeum/android-tools 的 daemon 扩展，AOSP ADB 36.0.1 源码 + CMake 静态构建）
- Release：`v36.0.1-linux.2`（2026-07-22），资产 `adbd-36.0.1-linux-aarch64-static`
- SHA256：`e7876da9ddf2fd74176de83b7ff276252292c0e5e1150565d53a812c6eab2442`
- 特性：静态链接（无 DT_NEEDED）、FunctionFS USB + TCP + VSOCK 并行、
  兼容 Rockchip `usbdevice` 的 `ADB_TCP_PORT` / `ADBD_SHELL` 环境变量
- **注意**：无认证（authentication disabled），与旧 vendor adbd 安全模型一致，
  勿将 USB / 5555 端口暴露给不可信主机

### 为什么替换旧版（2026-08 rock5b USB adb 排查结论）

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

## adbd-armhf — ADB 36.0.1 standalone（自编译）

- 源码：同上游仓库 tag `v36.0.1-linux.2`（上游未发布 armhf 产物，自行交叉编译）
- 构建：rock5b（Ubuntu 24.04 arm64）上以 `g++-arm-linux-gnueabihf` 13.3.0
  交叉编译，toolchain 文件照抄上游 `aarch64-linux-gnu.cmake` 改三元组，
  `scripts/build-linux-adbd.sh` 默认参数（ADBD_ONLY + FULLY_STATIC + USB），
  产物经 `arm-linux-gnueabihf-strip`
- SHA256：`840bc2410ad025dd2f008061e5461c88e9743b630c0ecd91732f50705fb8a6fa`
- 验证：rock5b（aarch32 用户态）纯 TCP smoke test 通过（监听/连接/shell）；
  USB FunctionFS 路径与 arm64 版同源同修复，暂无 armhf 板实测
