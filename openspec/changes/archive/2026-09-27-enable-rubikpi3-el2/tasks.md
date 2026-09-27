## 1. 实现

- [x] 1.1 新增 `bootloader.ufs_file_overrides` schema、语义校验与 flash-config 字段（1 小时）
- [x] 1.2 固件包校验与刷写暂存支持文件替换，拒绝未引用、组件产物与 LFS 指针（1 小时）
- [x] 1.3 新增 `rubikpi3-el2.dtso` 并在两个 product 构建期合并（1 小时）
- [x] 1.4 配置、校验与刷写单元测试（1 小时）
- [x] 1.5 按上游 kodiak-el2 补 ADSP/CDSP SMMU 流与 watchdog（0.5 小时）
- [x] 1.6 backport LT9611 单 Port B 输入驱动补丁（0.5 小时）

## 2. 构建与实板验收

- [x] 2.1 Docker 构建 default/desktop，核对 DTB 合并结果与 flash-config（1 小时）
- [x] 2.2 全量刷写后确认 `/dev/kvm` 出现、启动到 rootfs、UFS 无复位（1 小时）
- [x] 2.3 验证 venus 硬件编码 H.264/HEVC 与解码不回退（1 小时）
- [x] 2.4 复验 usbmoded、Wi-Fi、蓝牙、Renesas USB3 在 EL2 下正常（1 小时）
- [x] 2.5 验证 ADSP/CDSP 在 EL2 下 running、LT9611 探测成功且 msm DRM 初始化（1 小时）——LT9611 与 msm DRM 通过；DSP 受 TZ 限制在 EL2 下离线，改由 `el1` product 提供（见 3.1–3.5）

## 3. 固件实验与 product 拆分

- [x] 3.1 实测 qli2.0（TZ 00146，保留 LUN3 usb_fw）：启动与 USB3 正常，EL2 下 DSP 仍 `-5`（1 小时）
- [x] 3.2 实测 Qualcomm 00142（TZ 00187）+ main XML/CDT：进入内核即停，放弃（1 小时）
- [x] 3.3 固件校验增加分区容量检查及测试（0.5 小时）
- [x] 3.4 新增 `el1` product，EL2 配置仅作用于 default / desktop（1 小时）
- [x] 3.5 实板验证 `el1`：无 `/dev/kvm`、ADSP/CDSP running、硬件解码可用（1 小时）

实板记录（2026-09-26，default）：EL2 启动、`/dev/kvm`、venus H.264/HEVC 硬编与回解、LT9611 +
msm DRM + Adreno 初始化、usbmoded、蓝牙 hci0、Renesas USB3 与以太网枚举均通过。2.4 中 Wi-Fi 仅确认
驱动与固件加载，未连网；2.5 中 ADSP/CDSP 因 TZ 00126.1 不支持 `PAS_GET_RSCTABLE` 仍离线（待决）。

实板记录（2026-09-27，el1-release，main 固件）：EL1 启动、无 `/dev/kvm`，ADSP/CDSP running，
LT9611 + msm DRM 正常，usbmoded 自动进入 debug。Type-C UCSI 端口在 EL1 下同样未注册，与 EL 无关，
另行排查。

实板记录（2026-09-27，EL2）：Wi-Fi 连网与蓝牙由用户在实板复验通过。
