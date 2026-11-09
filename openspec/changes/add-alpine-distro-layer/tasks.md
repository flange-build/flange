## 1. 技术验证（spike）

- [x] 1.1 `apk.static mkpkg` 为 armv7 生成包，并在 armv7 minirootfs chroot 中 `apk add --allow-untrusted` 成功（≤2小时）
- [x] 1.2 clang + Alpine armv7 sysroot 编译 C/C++ 动态链接程序，在 QEMU chroot 中运行（≤2小时）

## 2. 核心 init 抽象（flange-layer）

- [x] 2.1 `InitSystem`（systemd/openrc）与 `DistroBackend.init_system/package_format`，Ubuntu 默认不变（≤2小时）
- [x] 2.2 AppSpec `openrc:` 段、`openrc/` 安装约定、按目标 init 校验服务文件（≤2小时）
- [x] 2.3 App 报告记录 init；deploy run/log/debug 经 InitSystem 生成命令（≤2小时）
- [x] 2.4 App 默认包格式随发行版，`packaging.depends` 按格式声明；rootfs App 安装归 distro（≤2小时）
- [x] 2.5 usbmoded 服务后端（systemctl / rc-service）与 sd_notify 条件化，adbd/usbmoded OpenRC 脚本（≤2小时）

## 3. Alpine 层：rootfs

- [x] 3.1 层骨架、`layer.toml`、发行版基线配置与 overlay（inittab、网络、sshd）（≤2小时）
- [x] 3.2 `ApkDistro` 基础系统、apk 缓存隔离、账号复用、OpenRC 启用、包清单（≤2小时）
- [x] 3.3 luckfox-pico-pro-max 追加 `alpine` product，生成 UBI rootfs（≤2小时）

## 4. Alpine 层：环境、SDK 与包格式

- [x] 4.1 构建环境 Dockerfile（apk.static、clang/lld、armv7 SDK、元数据）与环境策略（≤2小时）
- [x] 4.2 工具链策略与包装脚本，CMake/Meson/Make 目标编译（≤2小时）
- [x] 4.3 `ApkPackageBackend`：规划、生成、导入、设备命令（≤2小时）

## 5. 验证与文档

- [x] 5.1 C/C++ 与 Python 示例 App：构建、装入 rootfs、QEMU 运行（≤2小时）
- [ ] 5.2 实机：启动、SSH、adb 连接、`flange app deploy/run/log`，记录 verification.md（≤2小时）
- [ ] 5.3 ProjectSpec、`docs/layers.md`、Alpine 层 README 与 wiki 同步（≤2小时）
