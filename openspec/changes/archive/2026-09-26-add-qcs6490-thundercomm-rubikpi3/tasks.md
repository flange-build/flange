## 1. 调研与提案

- [x] 1.1 梳理参考工程内核、启动链、UFS 分区、BP 固件与外设，核对主线 DTS 与上游修复（2 小时）
- [x] 1.2 对比 boot-assets 各版本固件、LUN 布局与 LFS 内容，确定钉住版本（1 小时）

## 2. 配置与框架

- [x] 2.1 新增 `bootloader.ufs_rawprogram` / `ufs_patch` schema 与语义校验及测试（1 小时）
- [x] 2.2 实现 UFS 固件包校验与暂存模块，bootloader 构建期校验（1.5 小时）
- [x] 2.3 boot 组件产出 dtb.bin，平台输出契约随配置声明（1 小时）
- [x] 2.4 flash-config 增加 `ufs_firmware`，QualcommFlashStrategy 单会话刷写与 preflight（1.5 小时）
- [x] 2.5 刷写与契约测试：LUN0 保护、LFS 指针、缺产物、扇区、命令编排、旧清单兼容（1.5 小时）

## 3. 板级内容

- [x] 3.1 新增 `thundercomm-rubikpi3` 板级配置，default/desktop × debug/release（1 小时）
- [x] 3.2 backport LT9611 DSI Port B 与 USB QMP PHY 供电两个 DTS 修复并在 7.0.2 上验证应用（0.5 小时）
- [x] 3.3 AP6256 brcmfmac/BT 固件与 bluez；Renesas USB3 固件服务 overlay（1 小时）
- [x] 3.4 README、wiki 板卡页、平台页、log 同步（1 小时）

## 4. 构建验证

- [x] 4.1 Docker 构建 `thundercomm-rubikpi3-default-release` 全部组件并检查产物（2 小时）
- [x] 4.2 Docker 构建 `thundercomm-rubikpi3-desktop-release` 并检查桌面包与镜像容量（2 小时）
- [x] 4.3 运行 config/platforms/builder 测试与 OpenSpec 严格校验（0.5 小时）

## 5. 实板验收（需硬件）

- [x] 5.1 EDL 全量刷写，记录固件版本；冷启动到 rootfs，UFS 无复位（1 小时）
- [ ] 5.2 HDMI + desktop GNOME、freedreno GPU（1 小时）
- [ ] 5.3 AP6256 Wi-Fi 扫描/连接、蓝牙扫描（1 小时）
- [ ] 5.4 Renesas USB3 口、以太网拓扑（`lsusb -t`）与 Type-C adb gadget（1 小时）
- [ ] 5.5 ADSP 音频、风扇温控、首启扩容；全部通过后同步主规格并归档（1.5 小时）
- [x] 5.6 修复 usbmoded 开机场景在 UDC 晚注册时不重试，实板复验开机自动进入 debug（1 小时）

实板记录（2026-09-26，default 产物）：00430 固件 + 7.0.2 启动到 rootfs，ADSP/CDSP up；
Renesas 固件自 `usb_fw` 加载，以太网为 USB3 下的 CDC-NCM；`wlan0`、`hci0` 出现；
usbmoded 8.7s 等待 UDC 超时、10.5s UDC 注册后重试、11.4s 进入 debug。
5.4 已确认 USB3 主控、以太网拓扑与 Type-C adb gadget，USB3 外设与以太网链路未测；
Type-C 口 dwc3 打印 `dr_mode forced to gadget`，不支持 host/role 切换。
按用户要求在 5.2-5.5 未完成时归档，剩余项记录在 `wiki/boards/thundercomm-rubikpi3.md`「待验收」。
