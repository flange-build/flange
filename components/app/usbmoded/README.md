# USB gadget 子系统（usbmoded）

本 App 用 Rust 实现设备端 USB gadget 管理服务与 `usb-mode` CLI（命令行客户端），
以静态 musl ELF（可执行与链接格式）交付，设备端不依赖 Python 或 PyYAML。adb 只是它管理的原子能力之一 ——
adbd 二进制与其 daemon unit 由独立的 `adbd` App 提供，后者通过
`build.deps` 依赖本 App。

平台竞态、init 适配与硬件验证范围见 [USB 管理参考](../../../docs/usb.md)。

## 架构

```
L3  场景层 (src/scene.rs)        场景 = 能力集合 + 参数 + role，切换编排
L2  原子能力层 (src/capabilities.rs) 每个 USB function 一个能力，统一接口 + 参数
L1  gadget 核心 (src/gadget.rs、src/system.rs)  configfs 原语、UDC 生命周期、竞态处理
```

L1 不认识任何具体 USB function —— 所有 function 相关行为都通过
`Capability` 生命周期接口调用。行为回归测试位于 `src/tests.rs`，通过伪 ConfigFS（内核配置文件系统）
覆盖排序、幂等、解绑、恢复、延迟 UDC 与回滚。

daemon（adbd、mtp-server）的生命周期交给当前 systemd 或 OpenRC，不自制保活循环 ——
后者的状态判断读写不对称曾在 ROCK 5B 上堆积 360+ 并发循环、USB 每 2 秒
断连一次。

## 构建与验收

在 flange 仓库根目录，完成 [开发环境准备](../../../docs/development-guide.md) 后运行：

```sh
flange --target luckfox-pico-pro-max-default-release app build usbmoded
flange --target luckfox-pico-pro-max-default-release app deploy usbmoded --no-build --serial <USB序列号>
```

Alpine 外部工作区使用相同命令，并加 `-C <工作区>`、选择 `luckfox-pico-pro-max-alpine-release`。
构建通过 custom 配方在 Docker 内执行 `cargo test --locked` 和 release 交叉编译；
支持 `armhf` → `armv7-unknown-linux-musleabihf`、`aarch64` → `aarch64-unknown-linux-musl`。
`build.py` 只用于构建，不安装到设备。Rust 1.90.0 的官方组件 URL 与 SHA256 固定在
`rust-toolchain-artifacts.json`，crate（Rust 依赖包）及校验和固定在 `Cargo.lock`；
首次构建需要访问 Rust 官方分发站和 crates.io，下载与工具链缓存在工作区 `.build/` 下。
摘要或测试失败会中止构建，不发布部分产物。

结果位于 `<工作区>/.build/target/<board>/<product>/<variant>/apps/usbmoded-<来源摘要>/`，
`install/usr/sbin/` 是两个静态程序，`artifacts/` 是 DEB 或 APK。
包内 `/usr/share/doc/usbmoded/licenses/` 保留上游依赖和 Rust 标准库的许可与版权。
增量部署后用目标 init 重启 `usbmoded`，并执行 `usbmoded --version` 与 `usb-mode get`。
从旧 Jetson 镜像升级，还须移除手工遗留的 Python ExecStart drop-in 与 `/usr/local/sbin/usb-mode`
包装；当前平台 overlay 已不包含它们。

主机端真机验收命令（设备不需要 Python）：

```sh
python3 tests/usbmoded_field_verify.py --serial <USB序列号>
python3 tests/adbd_usb_reconnect.py --serial <USB序列号> --cycles 3 --timeout 60 --allow-pid-change
```

第一条验证公开协议、5 次 reload、endpoint 持有和非特权拒绝；第二条会短暂断开 ADB，
由宿主等待恢复。失败时检查 `usb-mode get`、当前 init 的服务日志与 `dmesg`，
不要把伪 ConfigFS 测试当作外设通过。已测硬件与启动时间见 [Luckfox 板卡页](../../../docs/boards/luckfox-pico-pro-max.md)。

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

开机进入持久化场景，没有则进入 `default_scene`（默认 `debug`）。UDC 晚于服务注册
（deferred probe，如 RUBIK Pi 3 的 dwc3 依赖 pmic_glink，约 10 秒才出现）导致开机场景
失败时，服务在 UDC 注册触发的 udev reload 中自动重试，无需手动 `usb-mode set`。
SPI NAND 冷启动中 adbd 的代码装入可能较慢，服务按实际 endpoint 打开状态轮询，
就绪立即继续，最长等待 15 秒；开机场景仍未完成时按 5–30 秒退避重试，
不依赖 endpoint 就绪后再次产生 udev 事件。已成功选择场景后不再进行开机重试。

## 命令行

```
usb-mode list              列出可用场景与本平台能力
usb-mode get               当前场景 / 能力 / role / UDC 与枚举状态
usb-mode set <scene>       切换（重启后回到默认场景）
usb-mode set -p <scene>    持久化切换
usb-mode reset             清除持久化，回到板级默认场景
usb-mode reload            重新加载场景定义
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
| `scene.set` | `scene`、`persist`、`force`、`rollback_timeout`（兼容 `timeout`） | 变更 |
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

udev 通知由 `/usr/lib/usbmoded/notify` 适配当前 init；服务 reload/SIGHUP 用于重新评估设备状态，
`usb-mode reload` 用于重读场景定义，二者职责不同。初始化期间收到的 SIGHUP 延后处理，避免 OpenRC 下重入。

服务在操作硬件前取得单实例锁。SIGHUP、RPC 与单调时钟回滚在同一事件循环中执行；
布尔参数必须为 JSON 布尔值，回滚时间为 1–86400 秒整数，默认 60 秒。
控制接口最多接收 16 个并发连接，每行最多 64 KiB，未完成请求或未读响应的连接在 5 秒后关闭。
配置拒绝重复 YAML 键、未知字段和错误类型；持久化场景采用原子替换。
