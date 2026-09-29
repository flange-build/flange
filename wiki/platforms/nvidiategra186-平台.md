---
title: nvidiategra186 平台
type: platform
status: wip
sources:
  - components/platform/nvidiategra186/config.jsonnet
  - components/platform/nvidiategra186/tegra186/config.jsonnet
  - components/platform/nvidiategra186/patches/kernel/0001-actmon-drop-init-from-actmon_map_resource.patch
  - builder/platforms/nvidiategra186/__init__.py
  - builder/platforms/nvidiategra186/kernel.py
  - builder/platforms/nvidiategra186/bootloader.py
  - builder/platforms/nvidiategra186/boot.py
  - builder/platforms/nvidiategra186/rootfs.py
  - builder/platforms/nvidiategra186/image.py
  - builder/flash/tegra.py
  - builder/rootfs.py
  - components/platform/nvidiategra186/overlay/etc/systemd/system/usbmoded.service.d/10-python3.8.conf
  - components/platform/nvidiategra186/overlay/etc/systemd/system/usbmoded-adbd.service.d/10-nsswitch.conf
  - components/platform/nvidiategra186/overlay/etc/flange/adbd-nsswitch.conf
  - components/platform/nvidiategra186/overlay/usr/local/sbin/usb-mode
  - components/app/usbmoded/udev/61-usbmode.rules
  - openspec/changes/add-tegra186-jetson-tx2/
related:
  - "[[nvidia-jetson-tx2]]"
  - "[[FlashStrategy 抽象]]"
updated: 2026-09-29
---

> [返回平台索引](index.md) · 设计依据与验收记录见 [add-tegra186-jetson-tx2](../../openspec/changes/add-tegra186-jetson-tx2/)

## TL;DR

NVIDIA Tegra186（Jetson TX2）平台以 **L4T R32.7.6** 为基线：内核是 4.9（OE4T 合并单仓），用户态是
**Ubuntu 18.04** + NVIDIA L4T 包，启动链（MB1 / MB2 / cboot / BPMP / TOS / U-Boot）全部用 BSP 预编译件，
刷写只能在 USB Recovery（`0955:7c18`）下经 BSP 自带的 `tegraflash.py` 完成。这是 flange 唯一不用
Ubuntu 24.04 rootfs 的平台：L4T R32 的 CUDA / 硬件编解码 / 摄像头只在 4.9 内核 + 18.04 上完整可用。

## 启动链与组件分工

```
BootROM → MB1 → MB2 → cboot ──(kernel-dtb 分区的 DTB，运行期修正)──┐
                          └→ U-Boot（kernel 分区 boot.img）→ APP:/boot/extlinux/extlinux.conf
                                                              → /boot/Image + /boot/initrd → Linux
```

| 组件 | 产物 | 说明 |
|---|---|---|
| kernel | `Image`、`<dtb>.dtb`、modules、`config` | OE4T `linux-tegra-4.9` 固定提交，`tegra_defconfig`，gcc-10.5；release `4.9.337-tegra` |
| bootloader | `tegraflash/` 刷写目录 | 下载校验 BSP，平铺 `bootloader/` 与点名的 BCT/DTB；mkbootimg 封装 U-Boot 为 `boot.img` |
| boot | `kernel-dtb.dtb` | 内核 DTB，构建期合并 DTBO（`DTBO_MERGE_AT_BUILD`） |
| rootfs | `rootfs.img` | 18.04 + L4T 包（`phase2_packages`）+ `/boot/Image` + L4T `/boot/initrd` + extlinux |
| image | `tegraflash-bundle/` | 渲染 `flash.xml`、稀疏 `system.img`、版本文件、`manifest.json`；不产 `raw.img` |

- **cboot DTB 与内核 DTB 分离**：`bootloader-dtb` 固定用 BSP 预编译 DTB，`kernel-dtb` 用 flange 编的 DTB。
- **extlinux 不写 FDT**：DTB 由 cboot 提供，`append` 以 `${cbootargs}` 开头；运行期 overlay 无处加载。
- **initrd 用 L4T 的**：stock 内核 xhci 为 built-in，固件从 `nvidia-l4t-initrd` 的 initrd 加载。

## Ubuntu 18.04 适配点

- 平台层覆盖 rootfs 基线 URL / SHA256，剔除 `btop`、`systemd-timesyncd`（18.04 无此包名）。
  flange 编译型 App 按容器内 glibc 2.39 编译，不能在 18.04 运行（adbd 为静态链接，不受影响）。
- L4T 包的 preinst 在 chroot 中读不到 `/proc/device-tree`，因此经通用字段 `rootfs.phase2_packages`
  在 Phase 2 安装，平台 rootfs 子类在 Phase 2 期间放置 NVIDIA `nv-apply-debs.sh` 同款标记文件。
- 18.04 的 `sshd_config` 不加载 `sshd_config.d`，且 OpenSSH 7.6 的 `sshd_config` 不支持 `Include`（8.2 起才有，写入会让 sshd
  拒绝启动）；RootfsBuilder 把 `PermitRootLogin no` 直接写在主配置首行，`disable_root_login` 才生效。
- NVIDIA `jetson/common` 与 `jetson/t186` r32.7 源保留在镜像中，设备上可 `apt install nvidia-jetpack`；
  `jetpack` product 在构建期预装。

## USB gadget：usbmoded + adb

与其他平台一样由 usbmoded 管理 gadget、默认 `debug` 场景提供 adb；L4T 自带的 USB device mode
（`nv-l4t-usb-device-mode`，RNDIS/ECM `192.168.55.1` + ACM）在平台 overlay 中 mask，避免两套 gadget 争用
`3550000.xudc`。18.04 上需要额外处理：

- **Python**：usbmoded 用到 `typing.Protocol`，需要 ≥ 3.8；平台装 `python3.8`、`python3-yaml`，
  `usbmoded.service.d/10-python3.8.conf` 改 `ExecStart`，`/usr/local/sbin/usb-mode` 包装 CLI。
- **adbd 的 NSS**：静态 glibc 2.39 的 adbd 会 dlopen 系统 2.27 的 `libnss_compat`，`adb shell` 时 abort
  （`_dl_call_libc_early_init` 断言），随后 FunctionFS 关闭、gadget 被解绑。`usbmoded-adbd.service.d/10-nsswitch.conf`
  用 `BindReadOnlyPaths` 只在 adbd 的挂载命名空间里换成仅 `files` / `dns` 的 nsswitch（glibc ≥ 2.34 内建这两个
  后端）。`adb shell` 的子进程继承该命名空间，看到的是副本。
- **udev 路径**：usbmoded 的 `61-usbmode.rules` 改用 `/bin/systemctl`（18.04 未合并 `/usr`，原 `/usr/bin/systemctl`
  不存在，adbd 重启后 gadget 不会被重新绑定；24.04 上两者等价）。
- 4.9 内核没有 `usb_role` 类，usbmoded 的 host / device 角色切换场景不可用。
- 按 NVIDIA `nv_customize_rootfs.sh` 对齐 stock：启用 `nvpmodel.service`，mask `ondemand`、`NetworkManager-wait-online`。

历史：首版（commit 9d0c7bf）保留 L4T USB device mode、剔除 `adbd`，并为其脚本补齐 `bridge-utils` /
`isc-dhcp-server`（后者服务无配置，overlay 中 mask）；实板验收后按用户选择改为 usbmoded，这些包与 mask 随之移除。
设计与实板证据见变更的 design.md D10 与 verification.md 第 10 节。

## 刷写

- `flange flash`：校验刷写包摘要 → 等待唯一 Recovery 设备 → `tegrarcm_v2 --uid` →
  `tegraflash --skipuid dump eeprom` + `chkbdinfo` 核对 board ID / SKU / FAB → 确认后 `--cmd "flash; reboot"`。
- `flange flash APP` / `flange flash kernel-dtb`：同样核对身份后按分区名 `write` / `signwrite`；
  其余分区是 NVIDIA 启动链，单刷需要 `--yes`。
- 只能在 x86_64 Linux 宿主运行（tegraflash 宿主二进制只有 x86 版本），需要 sudo。

## 易踩坑

- gcc 10 下 `tegra_actmon_register()` 引用 `__init actmon_map_resource()` 触发 modpost 致命 section mismatch，
  平台补丁去掉 `__init`（gcc 7 内联掩盖了这个真实缺陷）。
- L4T 的 dts Makefile 会产出两份同名 DTB（`_ddot_` 嵌套路径与 dts 根目录），内容相同。
- 不设 `LOCALVERSION=` 时 setlocalversion 在非 tag 树上追加 `+`，release 与 stock 不一致。
- 新增平台不能复用 TX2 4GB / TX2i / TX2 NX：它们的 BCT、BPMP DTB 与内核 DTB 不同。
- L4T 的蓝牙由 `99-nv-wifibt.rules` 在 `bluedroid_pm` rfkill 解除阻塞时启动 `nvwifibt.service`；该 rfkill 默认阻塞，
  stock 靠 GNOME 会话解除，无桌面时没有 `hci0`。TX2 的处理（预置 systemd-rfkill 状态 + `bluez`）见
  [nvidia-jetson-tx2](../boards/nvidia-jetson-tx2.md)。
