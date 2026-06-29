## 1. Docker 裸机工具链

- [x] 1.1 `docker/Dockerfile` 解压官方 gcc-arm-none-eabi-10-2020-q4 tarball 到镜像（钉 gcc-10，不进 git）
- [x] 1.2 `flange docker rebuild` 后在容器内验证 `arm-none-eabi-gcc --version` 主版本为 10
- [x] 1.3 容器内用 `arm-none-eabi-gcc --specs=nosys.specs -mcpu=cortex-a55 -mfloat-abi=hard` 编一个最小裸机 C 程序，确认链接通过

## 2. amp 构建组件（产出 amp.img）

- [x] 2.1 `builder/cache.py`：`DEPENDENCY_GRAPH` 加 `"amp": []`，`"image"` 依赖追加 `"amp"`，`REQUIRED_ARTIFACTS` 加 `"amp": ["amp.img"]`
- [x] 2.2 `builder/engine.py`：`_component_disabled` 加 amp 分支（`config.amp.enabled` 为假则跳过，仿 recovery）
- [x] 2.3 `builder/platforms/rockchip/__init__.py`：`create_builder` 加 `component=="amp"` 分派，`ARTIFACT_NAMES` 加 `("amp","amp"):"amp.img"`
- [x] 2.4 新建 `builder/platforms/rockchip/amp.py`：`RockchipAmpBuilder` 骨架，覆写 `build()` 跳过 git 源码树（仿 `boot.py`），串 compile→collect
- [x] 2.5 `amp.py`：mode=hal 构建路径——再以 `amp_linux.its` 调 `tools/mkimage`（**覆盖** stock `mkimage.sh` 写死的 `-f amp.its`，否则产出 4 核无 Linux 镜像）。**注：2.5/2.6/2.9/2.11 的 build.sh/scons/staging 路线已被 CMake-app 模型取代**——hal 现走 `cmake` 构建引用 `rockchip-hal.cmake` 的 amp app 得 firmware.bin（见更新后的 spec `amp-firmware-build` 与 `amp-app-scaffold`）；rt-thread 路径预留未实现
- [x] 2.6 `amp.py`：mode=rt-thread 构建路径——容器内跑 `rt-thread/bsp/rockchip/<soc_project>-32` 的 `scons` + `mkimage.sh`（已默认 `amp_linux.its`），用 `RTT_EXEC_PATH` 覆盖写死的 prebuilts 路径
- [x] 2.7 `amp.py`：`collect()` 返回 `{"amp": <amp.img 路径>}`；**读取** `config.amp.soc_project` 定位工程（不在代码内硬编码 rk3566→rk3568 映射），从核 `arch=arm`
- [x] 2.8 `builder/cache.py`：`compute_hash` 加 `_mix_amp_sources`（`components/amp/rockchip/<mode>` 工程目录 + `amp.app` 指向的源码内容哈希）+ 混入内存布局常量
- [x] 2.9 `amp.py`：从 SoC config 读取内存布局常量并 **重写** `build.sh` 的地址赋值行（或绕过 build.sh 直接给 `make`/`scons` 传值）与 `.its` 的 load 地址——SHALL NOT 用环境变量（build.sh 内部 `export` 会覆盖）
- [x] 2.10 验证 `flange build amp` 产出 `target/<...>/amp/amp.img`，`mkimage -l amp.img` 识别为 FIT 且含 `linux`(arm64,cpu=0) + 单从核 firmware 节点（非 4 核全裸机，证明用了 amp_linux.its）
- [x] 2.11 ~~`amp.py`：按 `config.amp.app` 把指定 amp app 源码 stage 进 SDK 应用槽位再构建~~ **已取代**：无 staging。amp app 是引用 `rockchip-hal.cmake` 的独立 CMake 工程（`components/app/<name>`），`amp.py` 用 `cmake` 就地构建产 `firmware`/firmware.bin；`components/amp` 仅只读 SDK 引用。`amp.app` 必填（无"回退示例固件"）

## 3. 分区与刷写

- [x] 3.1 amp 分区为 **product 作用域**：在 `components/board/tspi-rk3566/config.py` 经 `"partitions:amp"` 整块覆盖提供含非 raw `amp` 分区（`ext4`，16MiB@0x128000，**排在 remaining rootfs 之前**，rootfs 上移到 0x130000）。**不改 rk3566 SoC 分区表**——否则 default product 也会被改、违背决策 12「default 不受影响」（实现暴露的细化）
- [x] 3.2 `builder/platforms/rockchip/image.py`：`PARTITION_IMAGES` 加 `"amp": "amp/amp.img"`
- [x] 3.3 `builder/flash.py`：`RockchipFlashStrategy.partition_image_map` 加 `"amp": "amp/amp.img"`（`amp.enabled` gate，仿 recovery）
- [x] 3.4 `builder/config/validate.py`：新增 `validate_amp`（`amp.enabled` 时断言 mode∈{hal,rt-thread}、entries 含非 raw amp 分区、且 amp 分区在 remaining rootfs 之前）并挂入校验链
- [x] 3.5 验证 `flange build` 产出含 amp 分区的 `raw.img`（GPT 含名为 amp 的条目），`flange flash --list` 含 amp

## 4. amp app 脚手架

- [x] 4.1 `builder/app_spec.py`：`VALID_APP_TYPES` 加 `"amp"`，`VALID_BUILD_SYSTEMS` 加 `"amp"`
- [x] 4.2 `builder/scaffold.py`：`_VALID_COMBINATIONS` 加 amp 的 `(type, build_system)` 组合
- [~] 4.3 新建 `builder/templates/amp/`：当前仅含 `README.md.tpl` + `src/main.c.tpl`（早期 staging 模型半成品）。**待补**：更新为 CMake 模型——补 `CMakeLists.txt.tpl`（引用 `rockchip-hal.cmake`、定义 `firmware` target）+ `app.yaml.tpl`（`type: amp`、`system: cmake`），使 `flange create app --type amp` 产出可直接 `flange build amp` 的 CMake 骨架（参考已交付的 `components/app/rk3568_amp_demo`）
- [x] 4.4 `builder/app.py`：`build_one` 顶部按 `spec.app.type=="amp"` early-return 到 `_build_amp()`（不调 collect_files/DebBuilder，不用 `_CONVENTION_MAP`/`_CROSS_COMPILE_PREFIX`）
- [x] 4.5 定义 `amp.app` 独立声明键收集 amp app（不进 `rootfs.custom_packages`、不被 `gather_custom_packages` 迭代成 deb）；由 amp 组件消费（任务 2.11）
- [x] 4.6 验证 `flange create app --type amp <name>` 生成骨架、`flange list apps` 显示 type=amp、构建产固件而非 deb

## 5. 配置开关与内核 config

- [x] 5.1 `components/platform/rockchip/config.py`：`PLATFORM` 加 `amp: {"enabled": False}`（全平台默认关）
- [x] 5.2 `components/board/tspi-rk3566/config.py`：`"products": ["default", "amp"]`；amp product 条件键——`"amp:amp": {"enabled": True, "mode": "hal"}`（如需用户工程加 `"app": "<name>"`）、覆盖 `kernel` 的 `"dts:amp": "tspi-rk3566-amp"`、追加 `"+defconfig:amp": ["CONFIG_RPMSG_CHAR=y", "CONFIG_RPMSG_CTRL=y"]`（仅 amp product 开 rpmsg 字符设备）
- [x] 5.3 `components/platform/rockchip/rk3566/config.py`：`amp` 段声明 `soc_project: "rk3568"` 与权威内存布局常量作为单一事实源。**注：从核 `cpu_base`/load 已由 SDK 默认 `0x02800000` 搬到 `0x07000000`**（避开 flange 大内核 Kernel data 区致 reserved-memory `failed to reserve`，见 §9.4）；SHMEM=0x07800000、LINUX_RPMSG=0x07c00000，对齐 amp_linux.its + board amp dts

## 6. 启动（U-Boot）

- [x] 6.1 ~~board 级 bootloader patch~~ **改为配置机制**：board `bootloader.+defconfig:amp` 追加 `["CONFIG_AMP=y", "CONFIG_ROCKCHIP_AMP=y"]`（仅 amp product），rk3566 SoC `bootloader.defconfig` 改 list 形态，bootloader builder 支持 raw inline option（append 进 .config + `make olddefconfig`，对齐 kernel.defconfig 机制）。配置增加走配置、不走 patch（删除原 0001-amp-enable-config.patch）。实测 `.config` 含成对 AMP 选项
- [x] 6.2 核对构建出的 u-boot `.config` 的 `CONFIG_FIT_SIGNATURE`，确认未签名 amp.img 可被加载（否则规划 dev key 签名）
- [x] 6.3 验证 u-boot `.config` 含成对 AMP 选项；上板确认 U-Boot 读 amp 分区、加载 FIT 并拉起 cpu3、Linux 正常启动（已上板：UART4 出现从核 banner、Linux 3 核正常起）

## 7. 通信（DTS + 内核）

- [x] 7.1 经 board kernel patch **新增**专用 amp dts 文件 `tspi-rk3566-amp.dts`：`#include` tspi 基础 dts + `#include "rk3568-amp.dtsi"` + `/delete-node/ &cpu3;` + 使能 `&mailbox`，并确保 uart4 不被 Linux 占用（AMP console）。仅 amp product 经 `kernel.dts`（任务 5.2）选用，**不改基础板主 dts**（避免污染 default product）
- [x] 7.2 amp dts 的 reserved-memory / amp-cpus entry 地址取自 SoC 内存布局常量（任务 5.3）；新增构建期/校验期交叉比对——dts 地址与 SoC 常量不一致即失败（DTS 第三腿一致性兜底）
- [x] 7.3 验证 amp product 编出的 dtb 含 `rockchip,rpmsg` + 四段 AMP reserved-memory + mailbox okay、**无 cpu3 节点**、内核 `.config` 含 `RPMSG_CHAR/CTRL`；`default` product dtb 不含 AMP 节点且 4 核齐全
- [x] 7.4 上板（amp product）验证 `nproc`=3、`/dev/rpmsg_ctrlN` 出现，用户态创建端点后 `/dev/rpmsgN` 可收发（rpmsg 回环/示例）（已上板：cpu online 0-2、/dev/rpmsg_ctrl0、`RPMSG_CREATE_EPT_IOCTL` 建 /dev/rpmsg0、写入读回从核 echo "Rockchip rpmsg linux test!"。需补三处 rpmsg 修复见 §9）

## 8. 端到端验证与文档

- [x] 8.1 全链路冒烟：`lunch tspi-rk3566-amp` → `flange build` → `flange flash` → 上板确认 Linux（3 核）与 cpu3 AMP 从核共存、rpmsg 通信正常（已验证：完整 `flange build image` 产 raw.img；端到端 rpmsg echo 通。本轮迭代经 adb 在线部署 amp.img/dtb/Image，整盘 flash 等价）
- [x] 8.2 验证 amp product 与 `default` product 互不影响（default 仍 4 核、无 amp 分区/节点）；验证 3 核 Linux 与 cpu3 AMP 的 GIC/IRQ 不互踩（GIC/IRQ 共存已验证 = §9 的 gicInit=0 + amp-irqs 修复；default 隔离由条件键结构保证、见 7.3 default dtb 无 AMP 节点）
- [x] 8.3 文档：在 README/docs 补 amp 用法（`lunch tspi-rk3566-amp`、`flange build amp`、`flange flash amp`、`flange create app --type amp`）、3 核 + UART4 console 行为、首次整盘重刷说明

## 9. rpmsg 链路打通（上板调试发现，三处修复缺一不可）

上板验证 7.4 时发现 Linux↔AMP rpmsg 不通，dynamic workflow 深挖出三个叠加的独立 bug，逐一修复并端到端验证（详见 spec `amp-runtime-bringup` 的「AMP↔Linux rpmsg 链路建立」需求）。

- [x] 9.1 link-up 邮箱中断路由（DTS）：board kernel patch `0003` 的 `&rockchip_amp` amp-irqs 覆盖追加 `GIC_AMP_IRQ_CFG_ROUTE(222, 0xd0, CPU_GET_AFFINITY(3,0))`（MBOX0_CH3_A2B/INTID 222 → cpu3）。否则 Linux `gic_dist_init` 把未列入 amp-irqs 的该 SPI 改回 cpu0，从核永久卡 `rpmsg_lite_wait_for_link_up`。验证：UART4 出现 `rpmsg: link up`
- [x] 9.2 从核不抢 GICD（app 固件）：`components/app/rk3568_amp_demo/src/main.c` 的 `irqConfig.cpuAff/defRouteAff` 设非本核 `CPU_GET_AFFINITY(0,0)`（gicInit=0），从核不重初始化 GIC 分发器。设本核 → gicInit=1 抢 GICD 致挂死（即"加 amp-irqs 就停打印"的真因）
- [x] 9.3 反向通道唤醒 vq[0]（内核）：board kernel patch `0004` 给 `rockchip_rpmsg_mbox.c` 的 `rk_rpmsg_tx_callback` 补 `vring_interrupt(0, rpvdev->vq[0])`。rpmsg-lite `platform_notify` 恒发同一 mailbox 通道（R_CPU_ID），新消息(NS 通告)也落 tx 通道(ch3)而非 rx 通道，原回调只唤醒 vq[1](consume)→ Linux 收不到 NS 通告。验证：`/sys/bus/rpmsg/devices` 出现 `rpmsg-ap3-ch0`、`/dev/rpmsg0` echo 通
- [x] 9.4 从核固件区地址搬迁：`config.amp.memory` 的 `cpu_base` 由 SDK 默认 `0x02800000` 改 `0x07000000`（避开 flange 约 37MB 大内核的 Kernel data 区，否则 reserved-memory `failed to reserve`、从核不运行）。四腿（CMake FIRMWARE_BASE / .its load / dts entry / dts reserved-memory）同步
