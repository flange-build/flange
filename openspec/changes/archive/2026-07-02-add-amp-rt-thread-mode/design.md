## Context

flange 的 AMP 已落地 `mode=hal`（裸机固件，上板验证过 Linux↔AMP rpmsg echo）。`config.amp.mode` 的第二枚举 `rt-thread` 在 `amp.py:_compile_rtthread`（L223-233）仍是 `NotImplementedError`。RT-Thread RTOS SDK 已随仓入库（`components/amp/rockchip/rt-thread`），其 `bsp/rockchip/rk3568-32` 是 HAL `project/rk3568` 的孪生 BSP：同 die、同 `tools/mkimage`、同 `amp_linux.its` 骨架、同一套 rpmsg-lite、同一组内存宏。本变更把 rt-thread 编译路径补齐，并以 tspi-rk3566 的第二个 product 验证。

唯一与 HAL 不同的是**编译步**：RT-Thread 用 scons + Kconfig（工程在 SDK 树内），而非 HAL 的 CMake-of-app。下游（mkimage / collect / 分区 / 刷写 / dtb amp 节点 / U-Boot `CONFIG_AMP` / stock 内核 rpmsg 驱动）全部 mode 无关，已现成。

## Goals / Non-Goals

**Goals**
- `_compile_rtthread` 落地：scons 构建 RT-Thread BSP，产 `amp.img`，SDK 树零写入。
- 内存布局单一事实源（`config.amp.memory`）经环境变量驱动 rt-thread 固件链接，与 hal 同值。
- amp app 形态按 mode 二分：rt-thread = 轻量 BSP overlay；脚手架支持 `--mode rt-thread`。
- tspi-rk3566 新增 rt-thread product，上板验证 `/dev/rpmsg` echo。

**Non-Goals**
- 不改 HAL 路径行为、不改 default product。
- 不 patch 内核 rpmsg 驱动（两 mode 共用 stock 驱动）。
- 不在本变更支持 rt-thread 多从核（仍单从核 cpu3，与 hal 一致）。
- 不重新 vendor / 升级 RT-Thread SDK 本体。

## Decisions

### D1. 构建单元 = stage 一个可写 RTT_ROOT 镜像到 tmpdir（内核树 symlink、bsp/rockchip copy）

**初始设计「只 stage 单个 BSP 目录、RTT_ROOT 指只读 SDK」在上机构建中被证伪**，实测暴露三点，最终收敛为「可写 RTT_ROOT 镜像」：

1. **BSP 依赖兄弟目录**：`rk3568-32` 的 SConstruct/SConscript 相对引用 `../tools`（`sys.path` 导入 `buildutil`）与 `../common`（`HalSConscript`）；单目录 stage 缺它们。
2. **RT-Thread SDK 未 vendor `common/hal` 子模块**：`HalSConscript` 期望 `<common>/hal/lib/` 提供 `hal_base.h` 等，树内不存在（无 `.gitmodules`）。复用 flange 已有的**同款 Rockchip HAL**（`_HAL_ROOT`，HAL 模式所用；`lib/` 布局与 `HalSConscript` 期望逐一匹配），`common/hal` symlink 之。
3. **rpmsg-lite 逃逸 variant_dir**：`bsp/rockchip/common/drivers/rpmsg-lite/SConscript` 用 `GetCurrentDir()+绝对 Glob`，scons 就地生成 `.o`——若 `common/drivers` 源在只读 SDK 则污染 SDK。

**最终 staging**（`_compile_rtthread`）：mkdtemp 建 `staged_root` 作 RTT_ROOT；顶层除 `bsp` 外全 symlink 到真 SDK（含 `examples/` 等被 SConscript 引用者），`bsp` 除 `rockchip` 外全 symlink，`bsp/rockchip` 仅 `common` + 本板 `rk3568-32` **copy 成可写**（承接 rpmsg-lite in-source `.o` 与 `.config`/`rtconfig.h`/`build/` 写入）、其余（`tools`/其它板）symlink，`common/hal` symlink 到 `_HAL_ROOT`。scons 在 `staged_root/bsp/rockchip/rk3568-32` 跑，`PYTHONDONTWRITEBYTECODE=1` 兜 `__pycache__`。**上机实测：产合法 amp.img 且 SDK 树 `git status` 全净（零 `.o`/`__pycache__`）。**

- *备选*：拷整个 RT-Thread SDK 到 tmpdir。否决：树庞大、慢。symlink 内核树 + copy 仅 `bsp/rockchip`(~11MB) 是「保 SDK 只读」与「拷贝量」的平衡。

### D2. 内存布局经 scons 环境变量注入（与 hal 的 CMake -D 对等）

`config.amp.memory` 同一组值，按 mode 走不同注入腿但落到**同名下游宏**：`cpu_base→RTT_PRMEM_BASE`、`dram_size→RTT_PRMEM_SIZE`、`shmem_base/size→RTT_SHMEM_BASE/SIZE`、`rpmsg_base/size→LINUX_RPMSG_BASE/SIZE`、`cpu→CUR_CPU`。`rtconfig.py:44-95` 读这些 env 组出 `-DFIRMWARE_BASE/DRAM_SIZE/SHMEM_BASE/SHMEM_SIZE/LINUX_RPMSG_BASE/LINUX_RPMSG_SIZE`（与 hal 同名）并预处理 `gcc_arm.ld.S`。`cpu_base=0x07000000` 覆盖 BSP `build.sh` 的默认 `0x02800000`（与大内核冲突）。

### D3. app 形态 = 轻量 overlay，`_amp_app_dir` 按 mode 分叉

rt-thread app（`components/app/<name>`）只含 `applications/main.c` + `app.yaml`（`build.system: scons`）+ 可选 `.config`。构建时 stage BSP 模板 → tmpdir，再把 overlay 的文件叠上去（同名覆盖）。`amp.py:_amp_app_dir`（L152-155）现对所有 mode 硬检 `CMakeLists.txt`，SHALL 按 `_mode()` 分叉：hal 检 `CMakeLists.txt`，rt-thread 检 overlay 必备（`applications/` 或 `app.yaml`）。

### D4. rpmsg 启用 = app `.config` 加两行；三约束 BSP 默认已满足

grounding 钉死：BSP 自带 `.config` 已 `CONFIG_RT_USING_RPMSG_LITE=y` + `CONFIG_RT_USING_LINUX_RPMSG=y`，但把 `MBOX0_CH3_A2B(222)` 路由到 cpu3 的 `board_base.c:129-131` gated 在 `RT_USING_COMMON_TEST_LINUX_RPMSG_LITE`，其父 `RT_USING_COMMON_TEST` 默认 not set。故 rt-thread app 的 `.config` 覆盖 SHALL 加 `CONFIG_RT_USING_COMMON_TEST=y` + `CONFIG_RT_USING_COMMON_TEST_LINUX_RPMSG_LITE=y`。

rpmsg 三约束（见 amp-runtime-bringup）在 RT-Thread BSP **默认即对**：(b) `board_base.c` 的 `irqConfig.cpuAff/defRouteAff = CPU_GET_AFFINITY(0,0)`（gicInit=0）；(c) `rpmsg_base.h` 的 `MASTER_ID=1`/`REMOTE_ID_0=0` → link-id `0x10`，与现有 board dts 的 `rockchip,link-id=<0x10>` 已一致。这正是我们在 HAL 上手摸出的解——RT-Thread 是厂商参考默认。

### D5. `_mkimage_fit` 参数化

`amp.py:_mkimage_fit`（L207-208 读 HAL `project/<soc>/Image/amp_linux.its`、L215 改名 `hal<cpu>.bin`）SHALL 加形参 `(its_path=None, incbin_name=None)`，默认保持 hal 行为；rt-thread 传 BSP 的 `amp_linux.its` 路径 + `rtt<cpu>.bin`。L196 hal 调用处对应更新。

### D6. BSP 解析：`soc_project` + `-32` 后缀

hal 用 `project/<soc_project>`（rk3568）；rt-thread BSP 目录是 `rk3568-32`（-32 = AArch32）。构建器 SHALL 由 `soc_project` 拼 `<soc_project>-32` 定位 rt-thread BSP（数据放配置、规则在代码，与现有约定一致）。

### D7. 增量哈希：BSP 模板 + app overlay，不含 RTOS 内核树

参照 hal（lib/middleware 稳定不入哈希）：rt-thread 把 **BSP 模板目录（rk3568-32）+ app overlay 目录** 纳入 `amp_source_dirs`/哈希；庞大且稳定的 RTOS 内核树（`src/`/`components/`/`libcpu/`）不入哈希，改动罕见时 `flange build -f amp`。BSP 模板入哈希因其链接脚本/Kconfig/board 直接决定产物。

### D8. 容器零写入加固 + 补 scons

scons 缺失（Dockerfile 未装）SHALL 在 `docker/Dockerfile` 补 `scons`（python3/arm-none-eabi-gcc10 已就绪）。stage BSP 时设 `PYTHONDONTWRITEBYTECODE=1`，防 import RTT_ROOT 下 SConscript 时在只读 SDK 留 `__pycache__`。

### D9. board 接线 = 第三个 product `amp-rtt`

`tspi-rk3566/config.py` 现 `products=['default','amp']`，amp 经 `:amp` 条件键隔离。新增 `amp-rtt`：`products` 加项；`enabled:amp-rtt=True`、`mode:amp-rtt='rt-thread'`、`app:amp-rtt='<rtt-app>'`；`+defconfig:amp-rtt` 复用 U-Boot `CONFIG_AMP`；kernel dts 复用现有 `tspi-rk3566-amp.dts`（link-id 0x10 已与 rt-thread 默认一致）；分区复用 SoC 基线 amp 布局。

## Risks / Trade-offs

- **scons 不在镜像** → 补 Dockerfile 装 scons；docker rebuild。
- **import 在 SDK 留 `__pycache__`** → `PYTHONDONTWRITEBYTECODE=1`（grounding 陷阱②）。
- **Kconfig 嵌套依赖**：`COMMON_TEST_LINUX_RPMSG_LITE` 须先 `RT_USING_COMMON_TEST=y` → app `.config` 两行都加，构建后核对 `rtconfig.h` 生效。
- **两 product 若共用同一 app/内存** → 各 mode 独立 app；`amp-rtt` 指向独立 rt-thread app，避免固件源冲突。
- **rt-thread 默认 `cpu_base=0x02800000`**（build.sh）与大内核冲突 → `config.amp.memory.cpu_base=0x07000000` 经 env 覆盖（D2），且 `_assert_dts_consistency` 仍交叉校验 shmem/rpmsg。
- **scons 增量**：多板复用同一 BSP 模板可能哈希失效偏频 → 接受（amp 构建相对少）。

## Migration Plan

1. `docker/Dockerfile` 补 scons → `flange docker rebuild`。
2. `amp.py`：`_mkimage_fit` 参数化 → `_amp_app_dir` mode 分叉 → 实现 `_compile_rtthread`（stage BSP / env 注入 / scons / `rtt<cpu>.bin`）。
3. `app_spec.py`/`scaffold.py`：`VALID_BUILD_SYSTEMS` 加 `scons`、`_VALID_COMBINATIONS` 加 `("amp","scons")`、补 `templates/amp/scons/`；CLI 复用既有 `--build-system=scons`（不新造 `--mode`）。
4. `flange create app rk3568_amp_rtt_demo --type=amp --build-system=scons` 生成 overlay；填 `applications/main.c`（echo）+ `.config`（COMMON_TEST 两行）。
5. `tspi-rk3566/config.py` 加 `amp-rtt` product。
6. `lunch tspi-rk3566--amp-rtt`（或对应 target）→ `flange build` → 刷写 → 上板 `/dev/rpmsg` echo 验证。
7. *回滚*：rt-thread 为新增可选路径，删 `amp-rtt` product / 不选该 target 即回到现状；hal product 不受影响。

## Resolved Decisions（本轮确定）

- **app 命名 = `rk3568_amp_rtt_demo`**（`components/app/` 下，与 HAL 的 `rk3568_amp_demo` 对称、SoC 命名风格一致）。
- **首版 = 完整 echo（自写，link-id 0x10）**：`applications/main.c` 自实现 rpmsg echo（`rpmsg_lite_remote_init(0x10)` → `wait_for_link_up` → `rpmsg_ns_announce("rpmsg-ap3-ch0")` → `rpmsg_queue_recv`/`rpmsg_lite_send` 回环）。**弃用厂商 `rpmsg_test.c`**（其 link-id 0x03 与 stock 驱动/我们的 dts 0x10 不匹配）。详见 D10。
- **dts/分区 = 与 hal product 完全复用**：共用 `tspi-rk3566-amp.dts`（`rockchip,link-id=0x10`）与同一 amp 分区布局，不新建。

### D10. rt-thread rpmsg 三约束**不**由 BSP 默认满足（上板 bring-up 修正）

初判「rt-thread BSP 默认满足 rpmsg 三约束」被上板证伪，实测三处：

1. **link-id 须 0x10（非 BSP 默认）**：`rpmsg_base.h` 的 `MASTER_ID=1` 只是非 Linux-rpmsg 路径；**Linux-rpmsg 测试 `rpmsg_test.c` 自定义 `MASTER_ID=0`、`remote_id=cpu3` → `SET_LINK_ID(0,3)=0x03`（R=3）**，与 stock 内核驱动（新消息通道 rpmsg-rx=ch0）及我们 dts 的 0x10 都不符 → 卡 `wait_for_link_up`。故自写 `main.c` 取 `SET_LINK_ID(1,0)=0x10`。
2. **222 须由 app 补进 AMP GIC 白名单（根因，最难找）**：AMP 模式（gicInit=0）下 `HAL_GIC_Enable(irq)` 被 `GIC_AmpCheckIrqValid()` 门控——仅 `HAL_GIC_Init` 时经 `irqsCfg` 进过 `ampValid` 白名单的 IRQ 才能本核使能。`board_base.c` 仅在 `RT_USING_COMMON_TEST_LINUX_RPMSG_LITE` flag 下把 222 放进 `irqsConfig[]`，而该 flag 会让厂商测试在 0x03 抢跑。**解法**：`main.c` 在 rpmsg init 前再调一次 `HAL_GIC_Init(&amp_extra_gic)`（`irqsCfg` 只含 222）——`GIC_AMPGetValidConfig` 增量、无 memset（不冲 UART4）；`cpuAff` 取非本核 → gicInit=0 不重初始化分发器；仅把 222 补白名单。之后 rpmsg-lite 的 `HAL_GIC_Enable(222)` 放行。决定性证据：devmem 读到 `MBOX0 A2B_STATUS ch3=0x8` latch 不消费（Linux kick 在、222 未使能）。
3. **gicInit=0（约束 b）真由 BSP 默认满足**：`board_base.c` 的 `irqConfig.cpuAff=cpu0` 是顶层默认（不在 flag 下）——三约束里唯一一条 BSP 默认就对的。

- *备选*：开 COMMON_TEST + patch `rpmsg_test.c` link-id 到 0x10 用厂商 echo。否决：需 patch 只读 SDK 测试源，且 D10-2 的白名单可在 app 内自足，更干净。

## Open Questions

- （无）rt-thread Linux↔AMP rpmsg 端到端 echo 已上板验证通过（写 `hello` 读回 `Rockchip rpmsg linux test!`）。
