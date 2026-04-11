> **归档说明**：本设计方案属于 Bazel 构建系统时代（v1.0），仅作历史参考。adbd 的当前打包实现基于 Python App 打包系统，参见 `builder/app.py` 和 `app/adbd/app.yaml`。

## Context

flange 需要为嵌入式设备提供 adb 调试通道。adbd 通过 Linux USB gadget（configfs）暴露 ADB function，宿主机通过 `adb` 客户端即可进行 shell、文件传输、端口转发等操作。

参考实现来自 Armbian 的 `extensions/adbd/`，其中包含预编译的 adbd 二进制和一个功能完整的 USB gadget 管理脚本 `usbdevice`。

当前 `app/` 目录为空，这是第一个 service 类型的 App 实现，遵循 `docs/app-architecture.md` 定义的工程结构。

## Goals / Non-Goals

**Goals:**

- 实现 adbd 作为 flange 第一个 service 类型 App，验证 App 工程结构和 `flange_deb` 打包流程
- 基于 Armbian usbdevice 脚本做平台无关化改造，通过配置文件抽象平台差异，保留所有 USB function 支持和 hook 扩展框架
- 支持 adb shell、adb push/pull、adb forward/reverse 场景

**Non-Goals:**

- 不实现 `flange_deb` Bazel 规则（假设已可用）
- 不处理 adb RSA 认证
- 不修改 rootfs 构建流程

## Decisions

### 决策 1: App 工程结构遵循 service 类型模板

adbd 作为 service 类型 App 放在 `app/adbd/`，包含 app.yaml、BUILD.bazel、预编译二进制、脚本、systemd unit、udev rule。

**理由**: 遵循 `docs/app-architecture.md` 定义的标准结构，与将来的其他 App 保持一致。adbd 是 systemd 管理的后台服务，符合 service 类型定义。

**替代方案**: 放在 board overlay 中。但 overlay 是板级特定的，adbd 是通用应用，任何板子都可能需要，不应与特定板子耦合。

### 决策 2: 预编译二进制 + Bazel select() 架构选择

adbd 二进制以预编译形式提供（arm64、armhf 两个版本），通过 Bazel `select()` 按 `//toolchain:aarch64` / `//toolchain:armhf` 选择对应二进制。

```python
filegroup(
    name = "adbd-bin",
    srcs = select({
        "//toolchain:aarch64": ["bin/adbd-arm64"],
        "//toolchain:armhf": ["bin/adbd-armhf"],
    }),
)
```

**理由**: 符合 Bazel 惯例，不需要修改 `flange_deb` 规则。预编译二进制因为 adbd 源自 AOSP，交叉编译链路复杂，直接分发预编译版本更实际。

**替代方案**: 在 `flange_deb` 规则中新增 `prebuilt` 参数做架构映射。语义更清晰但需要改规则，为单个特例改规则不值得。

### 决策 3: 基于 Armbian 脚本做平台无关化改造

基于 Armbian 原版 usbdevice 脚本，将所有平台特定硬编码值提取到 `/etc/usbdevice.conf` 配置文件，脚本本身不包含任何平台特定值。

改造内容：
- 脚本启动时加载 `/etc/usbdevice.conf`，所有平台参数（VID、PID、产品名、厂商名、USB_GROUP）从配置读取
- `usb_pid()` 从硬编码 case 语句改为动态查找 `USB_PID_<key>` 配置变量，未匹配时使用 `USB_PID_DEFAULT`
- `usb_init()` 中使用 `$USB_VENDOR_ID`、`$USB_PRODUCT_NAME`、`$USB_MANUFACTURER` 等配置变量
- 序列号来源由 `$USB_SERIAL_SOURCE` 控制（cpuinfo / random / 固定值）
- 保留所有 USB function 实现（adb、mtp、uvc、ums、hid、acm、rndis、ntb）
- 保留 `/etc/usbdevice.d/` hook 扩展机制

配置覆盖机制：
- `app/adbd/conf/usbdevice.conf` 提供通用 fallback 默认值（Linux Foundation 测试 VID）
- `board/<board>/overlay/etc/usbdevice.conf` 板级覆盖（Rockchip VID=0x2207、板级产品名等）
- `conffiles` 声明确保 dpkg 升级时不覆盖用户修改

**理由**: 遵循 ProjectSpec 的框架与策略分离原则，脚本作为平台无关的框架层，配置文件作为平台特定的策略层。新增平台时只需提供板级配置文件，无需修改脚本。

## Risks / Trade-offs

- **[预编译二进制的可信度]** → adbd 二进制由用户自行编译提供，flange 不负责编译。需要用户确保二进制与目标架构匹配。
- **[configfs 内核支持]** → 目标设备内核必须启用 `CONFIG_USB_CONFIGFS`、`CONFIG_USB_CONFIGFS_F_FS` 等选项。如果内核未启用，usbdevice 脚本会静默失败。→ 可在脚本启动时检查 configfs 挂载状态并输出警告日志。
- **[配置文件缺失]** → 若板级 overlay 未提供 `/etc/usbdevice.conf`，脚本使用 App 默认的 Linux Foundation 测试 VID（0x1d6b），设备在宿主机上可能显示为未知设备。→ 新增板级支持时应同时提供板级 USB 配置。
- **[hook 机制的安全性]** → `/etc/usbdevice.d/*.sh` 会被 source 执行，任何放入该目录的脚本都会以 root 权限运行。→ 嵌入式设备通常为受控环境，风险可接受。
