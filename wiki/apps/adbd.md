---
title: adbd
type: app
status: stable
sources:
  - components/app/adbd/app.yaml
  - components/app/adbd/bin/adbd-arm64
  - components/app/adbd/bin/adbd-armhf
  - components/app/adbd/bin/README.md
  - components/app/adbd/conf/usbdevice.conf
  - components/app/adbd/scripts/usbdevice
  - components/app/adbd/systemd/usbdevice.service
  - components/app/adbd/udev/61-usbdevice.rules
  - components/board/atk-rk3506b/overlay/etc/modules-load.d/flange-usbgadget.conf
  - components/board/radxa-rock5b/overlay/etc/usbdevice.conf
  - components/rootfs/overlay/root/.bashrc
  - builder/platforms/rockchip/rootfs.py
related:
  - "[[recoveryctl]]"
  - "[[recovery 系统]]"
  - "[[atk-rk3506b]]"
  - "[[radxa-rock5b]]"
updated: 2026-08-27
---

## TL;DR

USB ADB gadget 服务，可运行于 normal 或 recovery rootfs，提供 host ↔ device 调试通道。支持 DWC2/DWC3 与模块化 ConfigFS gadget。daemon 为 **ADB 36.0.1 standalone adbd**（2026-08 从 Android 5 时代的 vendor adbd 升级，根因见下文定位记录）；[[atk-rk3506b]] 与 [[radxa-rock5b]] 均已验证断电冷启动后自动绑定并可 `adb shell`。

## 关键设计要点

- **app.yaml 类型**：`type: service`，`arch: [aarch64, armhf]`，`capabilities: [usb-gadget, adb-debug]`
- **二进制**：预编译 `bin/adbd-arm64` / `bin/adbd-armhf`，无编译步骤。均为 ADB 36.0.1 静态链接（arm64 取上游 release，armhf 自行交叉编译；来源与 SHA256 见 [bin/README.md](../../components/app/adbd/bin/README.md)）
- **systemd unit**：`usbdevice.service`（`Type=oneshot` + `RemainAfterExit=yes`）要求 `sys-kernel-config.mount`，并排在 `systemd-modules-load.service` 之后；入口 `/usr/sbin/usbdevice start` 负责启动 adbd。历史上曾用 `Type=forking`，systemd 会把脚本 spawn 的 daemon 守护循环误当 main process 追踪——服务"存活"实际依赖该循环永不退出这一 bug，循环被正常回收即触发 `ExecStop` 拆掉刚建好的 gadget（commit 0c9b03a2 修正）
- **udev 规则**：`61-usbdevice.rules` 监听 `android_usb` 状态变化，触发 `usbdevice update`
- **配置文件**：`/etc/usbdevice.conf`（conffiles，升级不覆盖）；板级 overlay 覆盖 VID/PID；默认 `USB_FUNCS=adb`，序列号取自 cpuinfo。ADB 36 adbd 额外读取两个 export：`ADB_TCP_PORT=5555`（旧 adbd 内建监听、新 adbd 须显式指定）与 `ADBD_SHELL=/bin/bash`（`adb shell` 以 argv[0]=`-/bin/bash` 启动 **login bash**，经 `/etc/profile` → `/root/.profile` 读到 [/root/.bashrc](../../components/rootfs/overlay/root/.bashrc)，提示符/补全/历史与 ssh 登录一致；旧 adbd 固定 `/bin/sh`→dash）
- **USB gadget 依赖**：`usbdevice` 在 configfs 创建 gadget group、挂载 functionfs、等待 `ep1` 后写 UDC；函数顺序由内核要求排列
- **daemon 守护循环**：`usb_start_daemon` 为每个 daemon 起一个 respawn 循环，活性由 per-daemon 的 `TAG_FILE` + PID 文件控制（`usb_reap_daemon_loop` 精确回收）。历史实现中 spawn 守卫读 `$USB_FUNCS_FILE` 的"内容非空"而循环退出读它的"文件存在"，disconnect recovery 只清空不删除——每次 USB disconnect 净泄漏一个永生循环，N 个循环并发 `start-stop-daemon` 抢同一 FunctionFS ep0 制造新 disconnect，正反馈雪崩（rock5b 实测开机 11 分钟堆积 360+ 进程、USB 每 2 秒断连；commit 0c9b03a2 修正）
- **模块化内核自愈**：板级 `modules-load.d` 冷启动加载 `phy-rockchip-inno-usb2`、`dwc2`、`usb_f_fs`；脚本若未看到 `usb_gadget`，会幂等 `modprobe usb_f_fs` 并给出明确错误
- **最小 rootfs**：`fuser` 仅用于占用诊断/清理；未安装 `psmisc` 时安全降级，不阻断 gadget 初始化
- **与 normal rootfs 差异**：recovery rootfs 默认启用；normal rootfs 取决于板级配置

## 关键代码位置

- [scripts/usbdevice](../../components/app/adbd/scripts/usbdevice) — gadget 编排（start / stop / update）
- [conf/usbdevice.conf](../../components/app/adbd/conf/usbdevice.conf) — 默认配置，板级 overlay 覆盖
- [systemd/usbdevice.service](../../components/app/adbd/systemd/usbdevice.service) — systemd unit
- [udev/61-usbdevice.rules](../../components/app/adbd/udev/61-usbdevice.rules) — udev 触发
- [bin/README.md](../../components/app/adbd/bin/README.md) — 二进制来源、SHA256 与升级缘由

## 易踩坑

- UDC 已绑定时写 `idProduct` 触发软断开，与 udev 形成无限触发循环；`update` 动作会跳过此写入
- adbd 须先打开 `ep1`，`usbdevice` 轮询 `/proc/<pid>/fd/` 确认后才写 UDC
- **UDC bind 竞态**：脚本写 UDC 后立即 read-back；不一致则退出 1，由 systemd 以 2 秒间隔有界重试。持续失败应检查 controller `dr_mode`/role、VBUS/ID、PHY 与 dmesg，不能把所有 DWC2/DWC3 故障都归因于 USB-C PD
- **`/sys/class/udc/*/state` 是 stale 的**：UDC 解绑后它仍报 `configured`。判断 gadget 是否真的 bind 只能读 `/sys/kernel/config/usb_gadget/*/UDC`；用 state 做"枚举成功"校验会被骗
- **adbd close(ep0) 会连带解绑整个 gadget**：内核 f_fs 的 `ffs_closed()` 调 `unregister_gadget_item()` 清空 UDC。日志里"没人写 UDC 它却变空"多半是持有 ep0 的进程关闭/重开了 FFS
- **板级 conf 整文件覆盖 App conf**：rootfs 构建 Phase 2 先 `dpkg -i` 装 app deb、最后 `cp -a` 叠 overlay（`rootfs → platform → board`，见 [builder/platforms/rockchip/rootfs.py](../../builder/platforms/rockchip/rootfs.py)）。语义是**替换不是合并**：App 层 conf 新增任何配置键，所有带自有 overlay 版本的板子必须手动跟进，否则静默丢失（`ADB_TCP_PORT` 首次落地时 rock5b 实测踩中；commit e13a6ec7 为全部 11 块板补齐并加警示注释）
- **macOS 上 tar 打包源码传设备**：`._*` AppleDouble 文件会污染 git pack 与 `*.patch` glob，构建前 `find . -name '._*' -delete`

## 2026-08-27：USB adb 不可用根因定位（rock5b × macOS host）

现象：rock5b 接 macOS 主机，`adb devices` 永远为空，设备端 adbd 反复被杀。定位过程分两层，最终换掉 adbd 二进制（commit 0c9b03a2、e13a6ec7）。

### 第一层：usbdevice 守护循环泄漏雪崩（放大器）

开机 11 分钟 `usbdevice` 进程堆到 361 个、服务内存 134.7M、dmesg 每 2 秒一轮 `device reset`。根因是守护循环的读写不对称（见上文"daemon 守护循环"）。修复后进程稳定 2–5 个，但 USB 仍在 bind→掉线循环——泄漏只是放大器，不是振荡源。

### 第二层：三个分离实验锁定元凶

1. **换内核态 ACM gadget**（无用户态 daemon）→ 在 Mac USB 树中稳定存在 20s+，零错误 → **排除 dwc3 控制器、USB 链路、供电、Mac 主机**
2. **停掉 Mac 的 adb server，adb gadget 手动 bind** → 同样稳定，dmesg 零新增 → **排除 gadget 配置本身**
3. **设备稳定期间启动 adb server** → 0.5 秒内必掉线 → **元凶是 adb server 的探测动作**

### 抓崩溃瞬间：dwc3 ftrace × strace 对时

- 设备端开 `/sys/kernel/debug/tracing/events/dwc3/dwc3_ctrl_req`（能看到 ep0 上每个 SETUP 包）+ `strace -f` 附着 adbd；Mac 端 `ioreg -p IOUSB` 高频轮询看设备存在性
- 时间线精确对齐：adb server claim interface 后发 **`ClearFeature(HALT)` ep1out/ep1in**（macOS 版 adb host 的预防性 clear-stall；**Linux 版 adb 不发**，所以旧 adbd 在 Linux 主机下从未暴露）→ 内核终止 FFS 上 pending 的 bulk 读并 giveback（mainline 语义，`dwc3_gadget_move_cancelled_request(…STALLED)` → 用户态 read 返回 **EPIPE**）→ 旧 vendor adbd（协议 1.0.28，Android 5 时代）把 EPIPE 当 USB 断开：`close(ep0)` → configfs 自动 unbind UDC → 设备从总线消失 → host 视为新设备再 claim → 死循环
- 反证实验：写"UDC 一空就 0.2s 内重新 bind、不碰 adbd"的守护，29 轮全部在下一次 claim 时再触发 EPIPE，**永不收敛** → 必须改 adbd 行为，任何外围 workaround 无效

### 修复：升级 adbd 到含 AOSP 官方修复的版本

AOSP `packages/modules/adb/daemon/usb.cpp` 的注释一字不差描述此场景（"some clients will send a ClearFeature(HALT)… Instead of treating this as a failure, which will tear down the interface and lead to the client doing the same thing again, just resubmit"），修复自 Android 10 时代：**首包前的 read EPIPE → 重新提交读，而非拆接口**。

采用 [happyme531/standalone-linux-adbd](https://github.com/happyme531/standalone-linux-adbd)（nmeum/android-tools 的 daemon 扩展，ADB 36.0.1，静态链接，专为 vendor adbd 过老的开发板设计，兼容 Rockchip `usbdevice.service`）。arm64 直接用上游 release（SHA256 校验）；armhf 上游无产物，在 rock5b 上以 `g++-arm-linux-gnueabihf` 交叉编译（toolchain 文件照抄上游 aarch64 版改三元组），并在 aarch32 用户态 smoke test 通过。

验证：`adb devices` 枚举即现（此前永远为空）→ root shell → push 85.6 MB/s（USB 2.0 近线速）、SHA256 一致 → 冷启动零干预可用 → 90s 观测进程/日志零增长。TCP 5555 与 USB 并行（`ADB_TCP_PORT`）。

### 残留疑点

首次以 root `setsid` 启动新 adbd 后约 3 秒设备整机失联（网络 + USB 双无响应），需断电恢复；pstore 无记录，重试同一路径未复现，判定偶发未追。BSP f_fs.c 与 mainline 仅 30 行无害 diff，已排除描述符解析魔改。

## 2026-08-24：udev 热插拔自愈修正

早期 udev 规则直接执行 `usbdevice update`。进程如果由 udev worker 拉起，会在事件结束后的清理阶段被终止，表现为热插拔后 gadget 短暂出现、随后 adbd 消失。现在由 udev 执行 `systemctl --no-block reload usbdevice.service`，再通过 unit 的 `ExecReload=/usr/sbin/usbdevice update` 进入原有幂等更新路径。这样既保留 UDC `add|change` 和 `android_usb change` 的自愈能力，也让 adbd 归 systemd 生命周期管理。
