## 1. App 工程脚手架

- [x] 1.1 创建 `app/adbd/` 目录结构：app.yaml、BUILD.bazel、bin/、scripts/、conf/、systemd/、udev/
- [x] 1.2 编写 `app/adbd/app.yaml`：name=adbd、type=service、arch=[aarch64, armhf]
- [x] 1.3 放置预编译二进制 `bin/adbd-arm64` 和 `bin/adbd-armhf`

## 2. usbdevice 脚本改造

- [x] 2.1 基于 Armbian usbdevice 脚本，移除 uvc/mtp/ums/hid/acm/rndis 具体实现，保留 configfs 核心逻辑和 adb function
- [x] 2.2 提取平台硬编码为配置文件加载：将 USB_GROUP、idVendor、product 等改为从 `/etc/usbdevice.conf` 读取
- [x] 2.3 改造 `usb_pid()` 函数，从 `USB_PID_*` 配置变量动态查找 PID
- [x] 2.4 保留 `/etc/usbdevice.d/` hook 扩展机制

## 3. 配置与服务文件

- [x] 3.1 编写 `conf/usbdevice.conf` 默认配置文件（通用 fallback 值 + 中文注释说明）
- [x] 3.2 编写 `systemd/usbdevice.service`（Type=forking, After=local-fs.target, WantedBy=sysinit.target）
- [x] 3.3 编写 `udev/61-usbdevice.rules`（监听 android_usb subsystem change 事件）

## 4. Bazel 构建与打包

- [x] 4.1 编写 `app/adbd/BUILD.bazel`：select() 架构选择 + flange_deb 打包规则，声明 conffiles、systemd auto_start、安装路径映射
- [x] 4.2 在 `board/radxa-zero3w/board.bzl` 的 `custom_packages` 中添加 `"adbd"`

## 5. 板级配置

- [x] 5.1 创建 `board/radxa-zero3w/overlay/etc/usbdevice.conf`：Rockchip RK3566 平台特定配置（VID=0x2207, USB_GROUP=rockchip, PID 映射表）
