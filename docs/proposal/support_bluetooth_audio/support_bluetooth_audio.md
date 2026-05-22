# 蓝牙音频（A2DP）连接与开机自启

## 概述

在一块 **Allwinner sunxi 板子**（AIC8800 USB combo WiFi/BT，`adb shell` root 接入）上，从「内核蓝牙驱动已加载但完全没有蓝牙/音频用户态」的状态出发，装齐 BlueZ + PipeWire，把一台**蓝牙音箱（小爱触屏音箱-6059）**配成 A2DP 音频输出，并做成开机自启。

**当前状态**：全链路已验证通过（2026-05-23）。A2DP 实机听到测试音；PipeWire 三件套配成 root 级 systemd 系统服务并 `enable` 自启；经一次实机 **reboot 实测**，开机自启 + `bt-speaker-connect.service` 自动重连音箱 + 出声全部自动恢复（重启后 `uptime ~42s` 即 `Connected: yes` 且默认 sink 正常出声）。

**约束/范围**：本方案是**运行中设备上的现场配置**（apt 安装 + systemd 单元 + 改 wireplumber 配置）。要让所有板子镜像都自带，应改造为 `components/packages` 硬件特性包（见 [[#后续工作]]）。

## 设备环境

| 项目 | 值 |
|---|---|
| 平台 | Allwinner sunxi（`soc@3000000`，`4200000.ehci1-controller`，`sunxi-ehci`） |
| 系统 | Ubuntu 24.04.4 LTS noble (aarch64) |
| Kernel | 5.15.147+ |
| 蓝牙/WiFi 芯片 | AIC8800（aicsemi）USB combo，BT 走 `btusb`，固件 `fw_patch_8800d80_u02_ext0.bin` |
| BT Controller | `F4:AB:5C:E1:D4:6E`（`hci0`） |
| 网络 | USB WiFi `wlxf4ab5ce1e86a`（联网用，apt 走它） |
| 目标音箱 | 小爱触屏音箱-6059 `50:64:2B:BF:68:B1`，Class `0x0024041c`（audio-card） |
| init | systemd（PID 1） |

## 起始状态

- 内核侧 OK：`hci0` 存在，`btusb` 已注册，AIC8800 BT 固件已加载，蓝牙协议栈（L2CAP/SCO 等）就绪。
- 用户态**全缺**：无 `bluetoothctl`/`hciconfig`/`bluetoothd`；无 `pipewire`/`wireplumber`/`pactl`/`aplay` 二进制（只有 `libbluetooth3`、`libpipewire`、`libpulse` 等库）。
- `dbus-send` 在，dbus 系统总线在，`/dev/rfkill` 在。

## 安装

```sh
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y \
    bluez pipewire pipewire-pulse wireplumber libspa-0.2-bluetooth
```

- `bluez` 提供 `bluetoothd`（自动建好 `bluetooth.service` 软链并 enable）+ `bluetoothctl`/`hciconfig`。
- `libspa-0.2-bluetooth` 提供 PipeWire 的蓝牙后端 `spa-0.2/bluez5/`（SBC/LDAC/aptX/LC3/Opus 编解码 + `libspa-bluez5.so`），**A2DP/HFP 都靠它**。

```sh
systemctl start bluetooth          # bluetoothctl list 应能看到 Controller
```

## 三个关键坑（核心经验）

### 坑 1：PipeWire 的 systemd **user** 单元拒绝以 root 运行

`/usr/lib/systemd/user/pipewire.service` 带 `ConditionUser=!root`，root 启动会被直接 skip：

```
pipewire.service ... was skipped because of an unmet condition check (ConditionUser=!root).
```

而这是个无头 root 系统，没有普通用户图形会话。

### 坑 2：root 没有 logind 会话 → 没有 `XDG_RUNTIME_DIR`

`/run/user/0` 不存在、无 user bus、`systemctl --user` 报 `Failed to connect to bus: No medium found`。

**解法**：给 root 开 linger，让 systemd 拉起 `user@0.service`，自动建出 `/run/user/0` 和 `/run/user/0/bus`（linger 持久，重启后仍生效）：

```sh
loginctl enable-linger root
# 之后 user@0.service active，/run/user/0 与 /run/user/0/bus 就绪
```

随后所有 PipeWire 相关命令都要带：

```sh
export XDG_RUNTIME_DIR=/run/user/0
export DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/0/bus
```

### 坑 3（最隐蔽）：WirePlumber 蓝牙 monitor 被 **logind 座位（seat）门控**

`/usr/share/wireplumber/scripts/monitors/bluez.lua` 里 `startStopMonitor` **只在 seat 状态为 `active` 时才启动蓝牙 monitor**：

```lua
logind_plugin = Plugin.find("logind")
if logind_plugin then
  function startStopMonitor(seat_state)
    if seat_state == "active" then monitor = createMonitor()
    elseif monitor then monitor:deactivate(...) ; monitor = nil end
  end
  ...
else
  monitor = createMonitor()   -- 没有 logind 时无条件启动
end
```

linger 拉起的 root 会话 seat 状态是 `lingering`（**不是 `active`**），日志里能看到：

```
script/bluez bluez.lua:410:startStopMonitor: Seat state changed: lingering
```

→ 蓝牙 monitor 永不启动 → **不向 BlueZ 注册 A2DP media endpoint** → 音箱即使 `Connected: yes` 也只是连了 ACL/AVRCP 控制通道，PipeWire 里**没有 sink、没有音频传输**。

**解法**：关掉 WirePlumber bluez 的 logind 集成。配置文件 `/usr/share/wireplumber/bluetooth.lua.d/50-bluez-config.lua` 的注释自己就写明了「system-wide 实例应 disable」：

```lua
-- This requires access to the D-Bus user session; disable if you are running
-- a system-wide instance of wireplumber.
["with-logind"] = false,   -- 原为 true
```

改成 `false` 后 `30-bluez-monitor.lua` 不再 `load_optional_module("logind")`，`Plugin.find("logind")` 返回 nil，monitor 走 `else` 分支无条件启动。重启 wireplumber 后日志不再出现 "Seat state"，改为 bluez5 SPA 插件活动（如 UPower 查询警告，无害）。

## 配对与连接（操作坑）

- **`bluetoothctl pair/connect` 报 `not available`**：非交互模式下每条命令是独立 client，扫描一停设备对象就老化。
  必须在**同一个持续的 bluetoothctl 会话**里保持 `scan on` 再配对：

  ```sh
  (echo "power on"; echo "agent on"; echo "default-agent"; echo "scan on"; \
   sleep 10; echo "pair 50:64:2B:BF:68:B1"; sleep 7; \
   echo "trust 50:64:2B:BF:68:B1"; sleep 2; \
   echo "connect 50:64:2B:BF:68:B1"; sleep 8; echo "quit") | bluetoothctl
  ```

- **endpoint 注册前连上的，要断开重连**：若在 wireplumber 注册 A2DP endpoint 之前就连上了音箱，A2DP profile 不会协商。改 `with-logind` 并重启 wireplumber 后，`disconnect` 再 `connect`，BlueZ 才会用本地 endpoint 协商出：

  ```
  NEW Endpoint .../sep1, .../sep2
  NEW Transport .../sep1/fd0        ← A2DP 媒体传输建立
  ```
  此时 `wpctl status` 出现 sink `小爱触屏音箱-6059`。

- 设默认输出并测试：

  ```sh
  wpctl set-default <sink-id>
  wpctl set-volume  <sink-id> 0.7
  pw-play --target <sink-id> /tmp/test.wav   # 实机已听到出声
  ```

## 两个设备特性须知

- **这台小爱音箱只支持 A2DP（Audio Sink）+ AVRCP，没有 HFP/HSP**，因此**无法用它做蓝牙麦克风收音**——智能音箱通常只做音频输出。`bluetoothctl info` 的 UUID 里只有 `Audio Sink` / `A/V Remote Control`，没有 `Handsfree`/`Headset`。
- **不持久化 link key**：`/var/lib/bluetooth/<ctrl>/<dev>/info` 里只有 `Trusted=true`，**没有 `[LinkKey]` 段**；断开后 `Paired: no`。故 bluetoothd 无法靠存储密钥在开机时自动重连，需要主动 `connect`（每次 `connect` 是即时重新协商，能成功）。

## 开机自启（持久化方案）

linger 已持久。新增 4 个 systemd **system** 单元（均以 root 跑，env 指向 `/run/user/0`）：

| 单元 | 作用 |
|---|---|
| `pipewire-system.service` | `ExecStart=/usr/bin/pipewire`，`After/Requires=user@0.service` |
| `wireplumber-system.service` | `ExecStart=/usr/bin/wireplumber`，`After/Requires=pipewire-system`，`Wants=bluetooth.service` |
| `pipewire-pulse-system.service` | `ExecStart=/usr/bin/pipewire-pulse`，`After/Requires=pipewire-system` |
| `bt-speaker-connect.service` | oneshot，跑 `/usr/local/bin/bt-speaker-connect.sh` best-effort 重连音箱 |

三个 PipeWire 单元共用的 env：

```ini
[Service]
Type=simple
Environment=XDG_RUNTIME_DIR=/run/user/0
Environment=DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/0/bus
ExecStart=/usr/bin/<pipewire|wireplumber|pipewire-pulse>
Restart=on-failure
RestartSec=2
[Install]
WantedBy=multi-user.target
```

自动重连脚本 `/usr/local/bin/bt-speaker-connect.sh`（best-effort，失败不阻塞启动；MAC 写死本音箱）：

```sh
#!/bin/sh
set -x
MAC=50:64:2B:BF:68:B1
bluetoothctl power on
for i in $(seq 1 12); do
    bluetoothctl info "$MAC" 2>/dev/null | grep -q "Connected: yes" && exit 0
    bluetoothctl --timeout 6 scan on >/dev/null 2>&1
    bluetoothctl connect "$MAC" >/dev/null 2>&1 && exit 0
    sleep 5
done
exit 0
```

启用：

```sh
loginctl enable-linger root
systemctl daemon-reload
systemctl enable --now pipewire-system wireplumber-system pipewire-pulse-system bt-speaker-connect.service
```

## 复现速查（全流程）

```sh
# 1. 装包
apt-get update && apt-get install -y bluez pipewire pipewire-pulse wireplumber libspa-0.2-bluetooth
# 2. root 运行时目录
loginctl enable-linger root
# 3. 关掉 wireplumber bluez 的 logind 门控
sed -i 's/\["with-logind"\] = true,/["with-logind"] = false,/' \
    /usr/share/wireplumber/bluetooth.lua.d/50-bluez-config.lua
# 4. 装 4 个 systemd 单元 + 重连脚本（见上），enable --now
# 5. 首次配对（保持 scan on 的单会话）→ 断开重连 → wpctl set-default → pw-play 测试
```

## 后续工作

- **改造为 flange 包**：把上述（包列表、`with-logind` 改写、4 个 systemd 单元、重连脚本）沉淀到 `components/packages` 的一个蓝牙音频特性包，随镜像构建分发，避免每块板子手动操作。参见 CLAUDE.md「Product/Variant 支持」与 packages 机制。
- **音箱 MAC 参数化**：`bt-speaker-connect.sh` 目前写死 MAC，包化时应改为可配置（环境文件 / lunch 变量）。
- **复验自动重连**：已确认（2026-05-23 实机 reboot，开机自动连回并出声）。
- **HFP 收音的现实限制（实测 2026-05-23，DJI Mic Mini 2）**：本音箱不支持 HFP；而对一台**支持 HFP 的蓝牙麦（DJI Mic Mini 2）实测收音失败**——它以 HFP **HF 角色**（UUID `0x111E Handsfree`）广播，要求本端当 **AG（Audio Gateway）**；但 PipeWire 的 native AG **无 modem/电话后端**，对 HF 发来的 `AT+CCWA` / `AT+BTRH` 只能回 ERROR（journal：`RFCOMM receive command but modem not available`），DJI 据此约 5 秒断开，Source 节点刚建出即销毁。关 mSBC（`bluez5.enable-msbc=false`）无效，属协议层不兼容（DJI 蓝牙模式为手机设计）。
  - 结论：**HF 角色的蓝牙麦在 headless/无 modem 的 PipeWire 上走 HFP-AG 收音不可靠**。
  - 收音的可靠路径：① 走 **USB**（DJI Mic / USB 麦枚举为 USB Audio Class → ALSA capture → 自动出现真 Source）；② 若坚持蓝牙 AG，需要给 native AG 配电话后端（ModemManager / ofono+phonesim 等），折腾且不保证成功。
  - 注：本板**无任何板载音频采集**（ALSA 仅 `allwinnerhdmi` 输出，无 capture PCM），故收音必须靠外接 USB 设备。

## 相关

- 同类「服务自启 + adb shell 接入」经验：[[support_weston]]
- 平台/包机制约定：见仓库根 `CLAUDE.md`、`ProjectSpec.md` §9
