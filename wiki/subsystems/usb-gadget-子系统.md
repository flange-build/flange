---
title: USB gadget 子系统（usbmoded）
type: subsystem
status: partially-verified
updated: 2026-09-19
sources:
  - components/app/usbmoded/
  - components/app/adbd/app.yaml
  - openspec/changes/add-usb-mode-switching/field-findings.md
  - tests/test_usbmoded.py
  - openspec/changes/add-usb-mode-switching/
related:
  - "[[adbd]]"
  - "[[recoveryctl]]"
---

# USB gadget 子系统（usbmoded）

## TL;DR

设备端的 USB gadget 管理服务，提供原子能力的组合与运行时工作模式切换。
三层架构：场景层（业务）→ 原子能力层（单个 USB function）→ gadget 核心层
（configfs 与竞态处理）。以 `usb-mode` CLI 与 unix socket 上的 JSON-RPC 2.0 对外。

2026-09-19 由三层 Python 服务替换了原先的 `usbdevice` shell 脚本，并拆成两个包：
`usbmoded`（服务本体）与 `adbd`（二进制 + daemon unit，`build.deps` 依赖前者）。

**当前状态：ROCK 5B 已完成首轮实板验证**（等价性、场景切换、权限分级、自锁回滚、
开机路径）。首轮验证发现并修复 8 个实板才能暴露的缺陷，见
`openspec/changes/add-usb-mode-switching/field-findings.md`。其余 13 块板仍为
「已迁移未验证」。

## 关键设计要点

- **L1 不认识任何具体 function。** 所有 function 行为经 `Capability` 接口调用，
  核心层没有 `if name == "adb"` 这类分支。有自动化校验守着这条线。
- **能力自带排序权重。** 内核对 function 排列有顺序要求，权重由各能力声明，
  核心层不再持有硬编码顺序表，新增能力无需改 L1。
- **daemon 交给 systemd。** 不自制保活循环 —— 那是 ROCK 5B 雪崩的根因。
- **配置按键合并。** 板级只声明差异键，App 层新增的键自动对各板生效。
  旧的整文件覆盖语义曾导致 7 个键在 12 份板级配置中各重复一遍。
- **状态以 configfs 为唯一真实来源。** 服务重启后从 configfs 反推已启用能力，
  不依赖可能陈旧的状态文件。
- **失败不静默。** UDC 绑定回读校验、role 切换回读校验、平台不支持时明确报错并
  列出已尝试路径 —— USB 问题定位成本极高，「返回成功但硬件没动」代价太大。

## 关键代码位置

| 层 | 文件 | 职责 |
|---|---|---|
| L3 | `app/usbmoded/usbmoded/scene.py` | 场景模型、切换编排、自锁回滚、持久化 |
| L3 | `usbmoded/control.py` | unix socket、JSON-RPC 2.0、`SO_PEERCRED` 授权 |
| L2 | `usbmoded/capability.py` | L1↔L2 接口契约、排序权重刻度 |
| L2 | `usbmoded/capabilities/` | 各能力实现 + systemd daemon 设施 |
| L1 | `usbmoded/gadget.py` | 描述符、生命周期编排、幂等守卫、断连恢复 |
| L1 | `usbmoded/udc.py` | UDC 探测、绑定校验、枚举校验与恢复 |
| L1 | `usbmoded/configfs.py` | configfs 原语、幂等写 |
| — | `usbmoded/role.py` | device↔host 角色切换的平台抽象 |
| — | `usbmoded/config.py` | YAML 分层加载与按键合并 |

入口：`bin/usbmoded`（服务）、`bin/usb-mode`（CLI）。

## 数据流

开机：`usbmoded.service` → 加载配置 → 从 configfs 重建状态 → 进入持久化场景
（无则板级默认场景）→ 启动控制 socket。

切换：`usb-mode set <scene>` → socket → 授权判定 → 解析能力与互斥检查 →
按 role 方向编排（切 host 先停 gadget 后写 role；切 device 反之）→
按内核顺序建实例 → prepare → 建链接 → 绑定 UDC → start → 枚举校验。

udev 事件：USB 状态变化 → `systemctl --no-block reload` → SIGHUP →
重新评估（UDC 掉了走断连恢复；能力未变则被幂等守卫短路）。

## 平台竞态知识（13 项）

这些知识来自被替换的 shell 脚本，每一项都对应一个在真实硬件上定位过的故障。
完整对照表（含原实现位置与验证方法）见
`openspec/changes/add-usb-mode-switching/race-checklist.md`，此处是独立于
代码注释与变更目录的第三份备份。

| # | 知识 | 丢失后果 | 自动化覆盖 |
|---|---|---|---|
| 1 | 读 UDC 前等 controller 就绪 | deferred probe 平台取到空 UDC | 否（需真实时序） |
| 2 | UDC 绑定后回读校验 | 写失败被吞，静默运行在未绑定状态 | 是 |
| 3 | 枚举状态轮询 | 只确认 bind，确认不了枚举 | 是 |
| 4 | soft_connect bounce **不动 ConfigFS/FFS** | 触发 `functionfs_unbind`，adbd 的 ep fd 永久失效 | 部分 |
| 5 | 区分「无主机连接」与真实故障 | 没插线被判故障，systemd 无限重启 | 是 |
| 6 | configfs 幂等写 | 无谓写入触发重新枚举 | 是 |
| 7 | idProduct 仅在 UDC 未绑定时写 | soft-disconnect + udev reload = 无限重置环 | 是 |
| 8 | 断连恢复只重启 daemon、不拆 ConfigFS | 同 #4 | 是 |
| 9 | 能力变化先停后启 | 往已绑定的 gadget 上追加 function | 是 |
| 10 | 守护循环 per-daemon 语义 | **ROCK 5B 雪崩**：11 分钟堆积 360+ 循环 | 已消灭（改用 systemd） |
| 11 | 并发互斥 | udev 与手动触发并发 | 否（需并发场景） |
| 12 | 内核要求的 function 排序 | 描述符顺序错乱 | 是 |
| 13 | 启动幂等守卫 | 每次 udev 事件都重配，重置环 | 是 |

自动化覆盖在 `tests/test_usbmoded.py`，用伪 configfs 验证编排逻辑。
标「否」的三项依赖真实硬件时序，只能实板验证。

## 板级支持矩阵

**除 ROCK 5B 外均为「已迁移未验证」** —— 配置已从 `usbdevice.conf` 迁移并通过
脚本比对确认等价。首次上板必须准备串口或其他带外通道（SSH over 网络即可）：
本服务处于开机关键路径，失败会让 adb 通道消失。

| 板子 | VID | gadget group | 配置来源 | role 切换 |
|---|---|---|---|---|
| orangepi-5-plus | 0x2207 | rockchip | 板级 | 未探测 |
| orangepi-cm4 | 0x2207 | rockchip | 板级 | 未探测 |
| radxa-rock5b | 0x2207 | rockchip | 板级 | **不可用**（无可写节点） |
| radxa-rock5c-lite | 0x2207 | rockchip | 板级 | 未探测 |
| radxa-zero3w | 0x2207 | rockchip | 板级 | 未探测 |
| rp-pro-rk3568-h | 0x2207 | rockchip | 板级 | 未探测 |
| tspi-rk3566 | 0x2207 | rockchip | 板级 | 未探测 |
| khadas-vim3 | 0x18d1 | khadas-vim3 | 板级 | 未探测 |
| khadas-vim3l | 0x18d1 | khadas-vim3l | 板级 | 未探测 |
| radxa-zero | 0x18d1 | radxa-zero | 板级 | 未探测 |
| radxa-cubie-a7a | 0x1f3a | sunxi | 板级 | 未探测 |
| radxa-cubie-a7z | 0x1f3a | sunxi | 板级 | 未探测 |
| atk-rk3506b | 0x1d6b | linux | **App 默认** | 未探测 |
| radxa-dragon-q8b | 0x1d6b | linux | **App 默认** | **不可用** |

最后两块没有板级配置文件，使用 App 层默认值（Linux Foundation 测试 VID）——
迁移前后一致，但迁移时容易遗漏，需专门确认。

Dragon Q8B 的 role 切换不可用是确定的：其 DTS patch 把 `usb_0_dwc3` 的
`dr_mode` 固定为 `peripheral`，而 dwc3 只在 `dr_mode = "otg"` 时才注册
role switch 接口。这类板子上 `usb-mode set host` 会明确报错而非静默失败。

## 易踩坑

- **清空 configfs 属性必须写换行符**，0 字节写入不触发内核 store 回调，
  解绑 UDC、清空 ums lun 会**静默失效**。
- **停用时不要删除 function 实例**，只解除 configuration 里的链接。删实例会
  销毁底层对象而挂载点残留，daemon 打开 ep0 后写描述符得到 EINVAL。
- **udev 触发的重新评估不能走 `switch`**，否则会取消自锁回滚计时器 ——
  切换本身就会引起 USB 状态变化并触发 udev。
- **ROCK 5B 内核只支持 ffs / mass_storage / acm / uvc**，通用场景里的
  `media`（mtp）与 `net`（ncm）在该板不可用；系统也缺 `mkfs.vfat`。
- **拆包后在已装旧版的设备上增量升级会撞 dpkg overwrite 冲突**，需先
  `dpkg -r adbd`。rootfs 全新构建不受影响。

- **首次上板必须有串口。** 本服务在 `sysinit.target` 阶段启动，失败即失联。
- **`-p` 持久化到不含 adb 的场景会让设备每次开机都无法远程访问**，需 `--force`
  才能执行，恢复只能靠串口或重新刷写。
- **不要把 `usbmode` 加进 rootfs 顶层 `groups`。** 该字段的第二职是「作为每个
  user 的默认入组集合」，加进去会让所有普通用户自动获得切换权限。该组由服务
  启动时创建，授予用户需显式 `usermod -aG`。
- **YAML 里的十六进制要加引号。** 裸写的 `0x2207` 会被 YAML 1.1 解析成整数。
- **uvc 帧目录按高度命名**，同高不同宽的分辨率（640x480 与 800x480）会落到同一
  目录，后者被静默跳过。这是从 shell 实现继承的行为。

## 延伸阅读

- [[adbd]] —— App 打包与 adbd 二进制来源
- `components/app/adbd/README.md` —— 能力清单、场景格式、CLI 与协议
- `openspec/changes/add-usb-mode-switching/` —— 设计决策与 13 项竞态对照表
