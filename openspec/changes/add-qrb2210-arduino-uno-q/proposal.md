## Why

flange 尚无 Arduino UNO Q 的 QRB2210/eMMC 启动与刷写模型，现有 Q6A 的 UFS/GRUB/SPI 策略不能复用为板级配置。
用户已有实板，要求首阶段完整覆盖 Linux、STM32U585 MCU（微控制器）、Bridge（通信桥）与 App Lab，建立可构建、可恢复、可验收的系统支持。

## What Changes

- 新增 `qualcommqrb2210` 平台、`qrb2210` SoC 与 `arduino-uno-q` 板卡，提供 default debug/release 目标。
- 固定 Arduino kernel、设备树、U-Boot 与官方救援固件；Docker 内编译并发布准确的组件产物。
- 实现 Android 格式 U-Boot 容器、EFI 系统分区、Ubuntu rootfs（根文件系统）与 userdata 产物。
- 新增 eMMC/QDL 刷写计划，验证 XML、文件摘要、容量和分区边界，保护设备持久化数据。
- 按自有 DEB 功能包移植固件、板级初始化、MCU 上传与 Router、App CLI/App Lab/Bricks，验证 Ubuntu 兼容性。
- 将平台新增产物与依赖声明接入现有计划、缓存和清单机制；通用扩展保持其他平台行为不变。
- 增加离线回归测试、构建验证及完整实板验收记录，完成后同步规格并归档。

## Capabilities

### New Capabilities

- `arduino-uno-q-platform`: QRB2210 配置、内核、启动镜像、固件及系统构建。
- `arduino-uno-q-flash`: QDL/eMMC 完整与组件刷写、产物验证、设备数据保护。
- `arduino-uno-q-runtime`: Ubuntu 上的 MCU、Bridge、App Lab、Bricks 及硬件运行时。

### Modified Capabilities

- `platform-abstraction`: 平台可声明额外必需产物与组件依赖，避免新增平台在通用计划内硬编码。

## Impact

- 代码：`builder/platforms/`、平台契约、组件计划、flash 计划/执行接口及必要 schema 扩展。
- 内容：`components/platform/qualcommqrb2210/`、`components/board/arduino-uno-q/`、Arduino 功能包。
- 工具：Docker 内 ARM64 交叉编译与 EFI 打包；宿主 QDL；MCU 的 OpenOCD/remoteocd 工具链。
- 测试与文档：配置发现、依赖/缓存、恶意或不完整 XML 拒绝、刷写命令编排、完整实板验收。
- 不宣称当前官方源码已通过 Ubuntu 全功能验证；实际失败与环境缺口必须保留在任务及验收记录。

## 非目标

- 本轮不改变现有 Q6A 启动和刷写行为，不引入 Debian APT 整仓混装 Ubuntu。
- 不改写 Qualcomm 闭源前级固件，不绕过设备安全机制，不实现 OTA 槽位升级产品。
- 不承诺未连接的任意 CSI/DSI 扩展板或 VENTUNO Q 的 NPU 能力；实际配件单独验收。
- 不以文档完成替代编译、实板验证，也不在未完成验收时自动归档。
