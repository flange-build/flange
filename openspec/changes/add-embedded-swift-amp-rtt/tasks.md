## 1. 工具链 spike

- [x] 1.1 在容器内临时验证候选 Swift 工具链能运行 `swift --version`
- [x] 1.2 编写最小 `Package.swift`，通过 SwiftPM 构建 Embedded Swift static archive
- [x] 1.3 用 `file` / `readelf -h` 确认 archive 内 object 架构、ABI 与 hard-float 属性
- [x] 1.4 用 `nm -u` 记录最小 archive 的未定义符号集合
- [x] 1.5 把 archive 链入一个最小 RT-Thread staged BSP 构建，验证 `scons` 链接通过
- [x] 1.6 在 `design.md` 中记录最终 SwiftPM target triple、必要 flags 和工具链版本

## 2. Docker 构建环境

- [x] 2.1 `docker/Dockerfile` 安装固定版本 Swift 工具链并校验 SHA256
- [x] 2.2 将 `swift` / `swiftc` 暴露到容器 PATH，并在 Docker build 中执行 `swift --version`
- [x] 2.3 增加 Dockerfile 静态测试或构建环境测试，确认工具链安装命令存在校验值
- [x] 2.4 更新 `openspec/specs/docker-build-env/spec.md` 对应实现后的基线说明

## 3. app.yaml 与脚手架

- [x] 3.1 `builder/app_spec.py` 为 `BuildConfig` 增加 `swift` 子配置结构
- [x] 3.2 校验 `build.swift` 只允许用于 `app.type=amp` 且 `build.system=scons`
- [x] 3.3 校验 `build.swift.package_path` 相对 app 根目录且不得逃逸
- [x] 3.4 校验 `build.swift.product` 非空，`build.swift.c_header` 若声明也不得逃逸
- [x] 3.5 `builder/scaffold.py` 支持生成 amp+scons+SwiftPM 骨架
- [x] 3.6 `builder/templates/amp/scons-swift/` 增加 `Package.swift`、Swift 示例文件与 C bridge header 模板
- [x] 3.7 增加 `test_app_spec` / `test_scaffold` 覆盖合法与非法声明

## 4. RT-Thread AMP 构建器

- [x] 4.1 `RockchipAmpBuilder._amp_app_dir` 保持现有 scons overlay 校验，并加载 `AppSpec`
- [x] 4.2 `_compile_rtthread` 在 overlay copy 后检测 `build.swift.enabled`
- [x] 4.3 新增 SwiftPM 构建辅助函数，生成或定位 `lib<product>.a`
- [x] 4.4 构建前删除旧 archive，避免旧 object 残留
- [x] 4.5 生成 staged `applications/SConscript`，把 Swift archive 注入 `Applications` group
- [x] 4.6 若 app 自带 `applications/SConscript` 且启用 Swift，报明确错误
- [x] 4.7 移除 Swift archive 级未定义符号白名单拦截，改由最终 SCons 链接暴露真实 unresolved 符号
- [x] 4.8 增加 builder 单元测试：无 Swift app 行为不变，Swift app 生成正确 `swift build` 与 SConscript

## 5. Orange Pi CM4 demo

- [x] 5.1 `components/app/rk3568_amp_uart7_rtt_demo/app.yaml` 增加 `build.swift` 声明
- [x] 5.2 新增 `Package.swift`，定义 Embedded Swift static library product
- [x] 5.3 新增 Swift 源文件实现 echo 回复或等价状态机逻辑
- [x] 5.4 新增 C bridge header，声明 Swift 导出的 C ABI 函数
- [x] 5.5 修改 `applications/main.c`：保留 GIC/rpmsg/thread 初始化，仅把回复内容委托给 Swift
- [x] 5.6 保持 `.config` 的 UART7_M2 与现有 rpmsg 协议不变
- [x] 5.7 拆出 `RtThreadShell` Swift target，封装 RT-Thread shell 参数与输出
- [x] 5.8 拆出 `RtThreadI2C` Swift target，封装 RT-Thread I2C transfer 接口
- [x] 5.9 新增 `swift_i2c` MSH 命令，支持指定 bus/address 的写、读、写后读
- [x] 5.10 demo `.config` 启用 RK3568-32 BSP 当前暴露的 I2C0

## 6. 验证

- [x] 6.1 运行相关 Python 单元测试
- [x] 6.2 `lunch orangepi-cm4-amp-rtt-debug`
- [x] 6.3 `flange build amp` 产出 `target/orangepi-cm4/amp-rtt/debug/amp/amp.img`
- [x] 6.4 检查 SwiftPM 产出的 archive 被链接进 `rtthread.elf`
- [ ] 6.5 检查 `rtthread.elf` 或 map 文件中存在 Swift 导出符号
- [x] 6.6 在有板环境下刷写并确认 UART7_M2 输出 `rpmsg: link up` 与 endpoint announce
- [x] 6.7 在 Linux 侧创建 `rpmsg-ap3-ch0` 端点，确认回复内容来自 Swift 实现

## 7. 文档与收尾

- [x] 7.1 更新 `components/board/orangepi-cm4/docs/amp.md`，说明 Swift demo 构建与限制
- [x] 7.2 更新相关 OpenSpec 基线 spec
- [x] 7.3 `openspec validate add-embedded-swift-amp-rtt --strict`
