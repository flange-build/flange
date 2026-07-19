## 1. OOT AMP 构建闭环

- [x] 1.1 `RockchipAmpBuilder._amp_app_dir` 改用 `SourceManager.ensure_app`
- [x] 1.2 校验 app.name、app.type 与 hal/rt-thread build.system
- [x] 1.3 `amp_source_dirs` 解析 local/git/search-dir OOT 源
- [x] 1.4 local OOT App 使 app/amp 及下游缓存失效
- [x] 1.5 外层 compose 自动挂载 OOT git worktree
- [x] 1.6 增加 OOT 解析、缓存、product 单元测试

## 2. RK3506 Fluxion product

- [x] 2.1 保留 default，新增 `atk-rk3506b-fluxion-{debug,release}`
- [x] 2.2 fluxion product 选择 `rk3506_amp_fluxion_foc`
- [x] 2.3 fluxion product 安装 `fluxion-rpmsg-bridge`
- [x] 2.4 文档说明 checkout、构建、安全和实板边界

## 3. CPU2 OOT App

- [x] 3.1 定义 app.yaml、RT-Thread config、SwiftPM static product
- [x] 3.2 定义 FXT1 线协议、type-6 原子 D/Q 与 host 编解码/CRC/interop 测试
- [x] 3.3 实现固定容量 SPSC command queue 与 Runtime 单一所有者
- [x] 3.4 实现 lease/heartbeat/disarm 与超时 force-safe
- [x] 3.5 实现 Runtime C ABI、FOC ports 和静态 generated plan
- [x] 3.6 实现有界 telemetry latest snapshot 与非阻塞 RPMsg worker
- [x] 3.7 定义 production fail-closed board hooks 与显式 loopback profile

## 4. Linux bridge

- [x] 4.1 自动按 channel/sysfs 精确唯一发现 rpmsg char，不硬编码 ctrl0
- [x] 4.2 独占 endpoint，完成 hello/capabilities/lease/command/ACK
- [x] 4.3 把 telemetry 映射为 `fluxion.telemetry/v1`
- [x] 4.4 提供 `/healthz`、只读 `/telemetry` 和独立 `/control`
- [x] 4.5 增加 systemd、Deb 安装、控制 token 和 host mock 测试

## 5. 构建与验证

- [x] 5.1 运行 Fluxion Swift/C/Embedded Swift host 门禁
- [x] 5.2 运行 Flange OOT/AMP/board/cache 单元测试
- [x] 5.3 `lunch atk-rk3506b-fluxion-debug`
- [x] 5.4 Docker 构建 AMP，确认 `amp.img`、符号、map 和 1 MiB carveout 门禁
- [x] 5.5 Docker 构建 armhf bridge deb，并确认安装进 UBI rootfs
- [x] 5.6 host mock 完成 lease → calibrate/start → type-6 D/Q → telemetry → stop/timeout
- [x] 5.7 `openspec validate add-rk3506-fluxion-foc-amp --strict`
- [x] 5.8 Swift archive/最终 ELF hard-float + enum ABI 双阶段门禁；最终 ELF heap
      符号/section/配置下限门禁（实测 653 KiB，可用余量 141 KiB）
- [x] 5.9 Docker 构建完整 image，确认 bootloader、boot、amp、rootfs 分区及
      `flash-config.json`/`mtd-bundle.json` 产物闭环

## 6. 真机门禁（需要功率板资料与设备）

- [ ] 6.1 明确 PWM/ADC/encoder/EN/FAULT 接线和 Linux DTS 所有权
- [ ] 6.2 先不接功率级验证 CPU2 boot、RPMsg、bridge 和 Web 遥测
- [ ] 6.3 接入硬件 break，验证上电、租约超时、RPMsg 断开和 fault 同周期安全
- [ ] 6.4 实测快环 WCET、抖动、deadline miss、queue/drop counter
- [ ] 6.5 HIL/限流电源下完成校准、空载低压 current-FOC 与故障注入
