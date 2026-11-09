# 板级配置迁移对照表

对应 tasks 1.3。源：12 份 `components/board/*/overlay/etc/usbdevice.conf`（本变更中移除）。

## 核心发现：7 个键在全部 12 块板上完全相同

| 键 | 全板一致的值 |
|---|---|
| `USB_FUNCS` | `adb` |
| `USB_SERIAL_SOURCE` | `cpuinfo` |
| `USB_BCD_DEVICE` | `0x0310` |
| `USB_BCD_USB` | `0x0200` |
| `USB_MAX_POWER` | `500` |
| `ADB_TCP_PORT` | `5555` |
| `ADBD_SHELL` | `/bin/bash` |

这 7 个键本该是 App 层默认值，却因板级 conf 的**整文件覆盖**语义被迫在每块板重复一遍 —— 这是 design D14 所述陷阱的直接实证。迁移到按键合并的 YAML 后，板级只需声明真正有差异的键，12 份配置可瘦身约 60%。

## 真正有差异的维度

### VID / 厂商 / gadget group

| 分组 | 板子 | vendor_id | manufacturer | group |
|---|---|---|---|---|
| Rockchip | orangepi-5-plus, orangepi-cm4, radxa-rock5b, radxa-rock5c-lite, radxa-zero3w, rp-pro-rk3568-h, tspi-rk3566 | `0x2207` | `rockchip` | `rockchip` |
| Amlogic/Khadas | khadas-vim3, khadas-vim3l | `0x18d1` | `khadas` | `khadas-vim3` / `khadas-vim3l` |
| Amlogic/Radxa | radxa-zero | `0x18d1` | `radxa` | `radxa-zero` |
| Allwinner | radxa-cubie-a7a, radxa-cubie-a7z | `0x1f3a` | `Allwinner` | `sunxi` |

`product_name` 每板不同，值恒等于板名。

### PID 映射表

只有两组：

**A 组 —— Rockchip 完整表**（7 块板，上表 Rockchip 分组）

```
adb=0x0006  mtp=0x0001  adb_mtp=0x0011  ums=0x0000
adb_ums=0x0018  adb_uvc=0x0015  acm=0x1005  default=0x0019
```

**B 组 —— 简表**（5 块板）

- khadas-vim3 / khadas-vim3l / radxa-zero：`adb=0xd001`，`default=0xd002`
- radxa-cubie-a7a / radxa-cubie-a7z：`adb=0x0006`，`default=0x0019`（与 A 组的这两项相同）

## 无板级配置的板子

以下板子引用了 adbd 但**没有**板级 `usbdevice.conf`，当前使用 App 层默认值（`vendor_id=0x1d6b` 即 Linux Foundation 测试 VID、`product_name=linux-gadget`）：

- `atk-rk3506b`
- `radxa-dragon-q8b`

迁移时不得遗漏这两块 —— 它们的行为等价基线是 App 层默认值，而非某份板级配置。

## 目标 YAML 形态

**App 层默认**（`/etc/usbmode/gadget.yaml`）承载 7 个全板一致的键 + fallback：

```yaml
gadget:
  vendor_id: "0x1d6b"
  product_name: linux-gadget
  manufacturer: linux
  group: linux
  serial_source: cpuinfo
  bcd_device: "0x0310"
  bcd_usb: "0x0200"
  max_power: 500
  pid_map:
    adb: "0x0006"
    default: "0x0019"
default_scene: debug
```

**板级覆盖**（`/etc/usbmode/gadget.d/20-<board>.yaml`）只声明差异：

```yaml
gadget:
  vendor_id: "0x2207"
  product_name: radxa-rock5b
  manufacturer: rockchip
  group: rockchip
  pid_map:
    mtp: "0x0001"
    adb_mtp: "0x0011"
    ums: "0x0000"
    adb_ums: "0x0018"
    adb_uvc: "0x0015"
    acm: "0x1005"
```

**adb 的两个参数**（`ADB_TCP_PORT` / `ADBD_SHELL`）不属于 gadget 描述符，迁移为 adb 能力的参数，随场景定义走。

## 实现注意：YAML 的十六进制解析

PyYAML 默认按 YAML 1.1 解析，裸写的 `0x2207` 会被解析为整数 `8711`，写回 configfs 时需格式化回 `0x2207` 形式。

**约定**：所有十六进制值在 YAML 中一律加引号写成字符串，由加载层显式转换。这样配置文件里所见即 configfs 所得，避免十进制/十六进制在两端来回翻译造成的对不上。加载层 SHALL 校验这些值的格式，非法时明确报错而非静默降级。

## 迁移验收

每块板迁移后，以下五项必须与迁移前逐字节一致（对应 tasks 8.2）：

1. `idVendor`
2. `idProduct`（默认场景下）
3. 产品名字符串
4. 厂商名字符串
5. 序列号（来源与取值方式）

其中 2 依赖 PID 映射表迁移正确；默认场景均为 `adb`，因此各板默认 PID 分别为：A 组与 a7a/a7z 为 `0x0006`，khadas/radxa-zero 为 `0xd001`，atk-rk3506b 与 radxa-dragon-q8b 为 App 默认 `0x0006`。
