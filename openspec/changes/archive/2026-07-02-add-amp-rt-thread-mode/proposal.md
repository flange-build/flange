## Why

flange 的 AMP 协处理器支持当前只落地了 `mode=hal`（裸机固件）；`config.amp.mode` 的另一枚举 `rt-thread`（带 RTOS 的从核）在 `amp.py:_compile_rtthread` 仍是 `NotImplementedError`。`components/amp/rockchip/rt-thread` 的 RTOS SDK 已随仓入库，且其 `rk3568-32` BSP 与已打通的 HAL 路径同 die、同 mkimage、同 `amp_linux.its` 骨架、同一套 rpmsg-lite 与内存布局约定——接入成本低、价值明确：让需要任务调度/驱动框架/文件系统的从核应用也能进 flange 的端到端构建与刷写。

## What Changes

- **amp 构建器补齐 rt-thread 编译路径**：`_compile_rtthread` 落地——把 RT-Thread BSP 模板（`rk3568-32`）stage 到 tmpdir、叠加 app overlay、用 `config.amp.memory` 注入 scons 环境变量（`RTT_PRMEM_BASE/SIZE`、`RTT_SHMEM_*`、`LINUX_RPMSG_*`、`CUR_CPU`）、在容器内跑 `scons` 出 `rtthread.bin` → `rtt<cpu>.bin`；`RTT_ROOT` 指向只读 SDK 根，scons 的 `variant_dir` 保证零写入 SDK 树。
- **mkimage 腿参数化**：`_mkimage_fit` 从写死 HAL 的 `project/<soc>/Image/amp_linux.its` + `hal<cpu>.bin`，改为吃 `(its_path, incbin_name)`，使 rt-thread 复用同一打包逻辑（rt-thread 用 BSP 自带 `amp_linux.its` + `rtt<cpu>.bin`）。
- **amp app 形态按 mode 分叉**：HAL app = 引用 SDK 的 CMake 工程；rt-thread app = **轻量 BSP overlay**——只含 `applications/main.c`（用户代码）+ `app.yaml`（声明 `amp.mode=rt-thread`）+ **可选** `.config`（覆盖 SDK BSP 的 Kconfig 默认）。`_amp_app_dir` 不再硬性要求 `CMakeLists.txt`。
- **脚手架支持 rt-thread**：`flange create app --type amp --mode rt-thread <name>` 产出轻量 overlay（区别于 HAL 的 CMake 工程模板）；app_spec 接受 rt-thread amp app 形态。
- **tspi-rk3566 新增 rt-thread product**：以 `amp.mode=rt-thread` + 指向新 rt-thread app 的第二个 product 接线，复用现有 amp 的全部下游（分区/刷写/dtb amp 节点/U-Boot `CONFIG_AMP`/stock Linux rpmsg 驱动）。
- **非破坏**：默认 product 与现有 HAL amp product 行为不变；rt-thread 为新增可选路径。无 **BREAKING**。

## Capabilities

### New Capabilities

（无。rt-thread 是对既有 amp 能力的扩展，全部以 delta 表达。）

### Modified Capabilities

- `amp-firmware-build`: 新增 rt-thread 编译路径（scons-in-staged-BSP、env 注入内存布局、`rtt<cpu>.bin`），`_mkimage_fit` 参数化；「rt-thread 模式当前未实现」场景反转为已实现；内存单一事实源在 rt-thread 下经环境变量（而非 CMake `-D`）注入同一组 6 个值。
- `amp-app-scaffold`: amp app 形态按 mode 二分——CMake 工程（hal）或轻量 BSP overlay（rt-thread）；`flange create app --type amp --mode rt-thread` 脚手架；app_spec/scaffold 接受 rt-thread amp app 的 `build.system` 与 overlay 文件集。
- `amp-runtime-bringup`: rpmsg 三约束的措辞由「HAL amp app 固件」泛化为「amp 从核固件（HAL app 或 rt-thread BSP）」；新增场景——rt-thread 厂商 BSP 默认即满足约束(b)(c)（`board_base.c` 的 `cpuAff=cpu0`、`rpmsg_base.h` 的 `MASTER_ID=1/REMOTE_ID_0=0` → link-id `0x10`），无需手改；约束(a) 与 U-Boot/分区 mode 无关，直接复用。

## Impact

- **代码**：`builder/platforms/rockchip/amp.py`（`_compile_rtthread`、`_amp_app_dir`、`_mkimage_fit`、`build` 分派）；`builder/app_spec.py` / `builder/scaffold.py`（rt-thread amp app 形态与模板）；`builder/templates/amp/`（新增 rt-thread overlay 模板集）。
- **配置数据**：`components/board/tspi-rk3566/config.py`（新增 rt-thread product）；可能补 `components/platform/rockchip/rk3566/config.py` 的 amp 段（rt-thread 的 BSP 标识，如沿用 `soc_project` 映射到 `rk3568-32`）。
- **新增内容**：一个 rt-thread amp app（`components/app/<name>`，轻量 overlay）。
- **构建环境**：依赖容器内具备 `scons` + `arm-none-eabi-gcc`（`/opt/arm-none-eabi-gcc10`）；若缺则补 `docker/Dockerfile`（待 grounding 确认）。
- **下游零改动**：dtb amp 节点、U-Boot `CONFIG_AMP`、amp 分区与刷写、内核 stock rpmsg 驱动均 mode 无关，直接复用。
