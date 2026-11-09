# USB gadget 子系统（usbmoded）

本 App 是设备端的 USB gadget 管理服务。adb 只是它管理的原子能力之一 ——
adbd 二进制与其 daemon unit 由独立的 `adbd` App 提供，后者通过
`build.deps` 依赖本 App。

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

开机进入持久化场景，没有则进入 `default_scene`（默认 `debug`）。UDC 晚于服务注册
（deferred probe，如 RUBIK Pi 3 的 dwc3 依赖 pmic_glink，约 10 秒才出现）导致开机场景
失败时，服务在 UDC 注册触发的 udev reload 中自动重试，无需手动 `usb-mode set`。

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
