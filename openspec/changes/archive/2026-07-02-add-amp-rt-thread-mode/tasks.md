# Tasks — add-amp-rt-thread-mode

## 1. 构建环境（容器补 scons）

- [x] 1.1 `docker/Dockerfile`：apt 安装块（python 组，L35-38 附近）加 `scons`。验证：`flange docker rebuild` 后 `flange shell` 内 `scons --version` 有输出（rebuild 待 §7）。
- [x] 1.2 容器内 `/opt/arm-none-eabi-gcc10/bin`（Dockerfile L122）与 amp.py `_RTT_EXEC_PATH`（L53）一致（grounding 已确认就绪）。

## 2. amp.py：mkimage 参数化 + app 解析分叉

- [x] 2.1 `amp.py:_mkimage_fit`：加形参 `its_path=None, incbin_name=None`，缺省保持 hal 行为（HAL `amp_linux.its` + `hal{cpu}.bin`）；hal 调用处依赖缺省。**hal 回归构建通过**（CMake 路径产出 amp.img 87KB，无回归）。
- [x] 2.2 `amp.py:_amp_app_dir`：按 `self._mode(config)` 分叉——hal 检 `CMakeLists.txt`；rt-thread 检 `applications/` 目录，缺则报明确错误。

## 3. amp.py：实现 _compile_rtthread

- [x] 3.1 `amp.py:_rtt_bsp_dir(soc)` —— 由 `soc_project`（rk3568）拼 `{_RTT_ROOT}/bsp/rockchip/{soc}-32` 定位 BSP 模板，缺 SConstruct 则报错。
- [x] 3.2 `amp.py:_compile_rtthread`（替换 `NotImplementedError`）：stage BSP→tmpdir（`ignore_patterns` 滤构建残留）；叠 `applications/` + 可选 `.config` **片段**（`_merge_kconfig_fragment` 按符号合并进 BSP .config，app 只需声明 Kconfig 增量、不带整份）；env 注入 `RTT_ROOT`/`RTT_EXEC_PATH`/`PYTHONDONTWRITEBYTECODE=1` + 6 内存宏 + `CUR_CPU`；带 `.config` 则先 `scons --useconfig=.config` 重生成 rtconfig.h；`scons -jN` 出 `rtthread.bin`→`_mkimage_fit(..., its_path=<BSP>/Image/amp_linux.its, incbin_name=f"rtt{cpu}.bin")`。合并逻辑单测通过；FIT 校验待 §7。
- [x] 3.3 `docker.run` 支持 `env` 形参（`{**os.environ, **env}` 合并，docker.py:64/106）—— 直接用，无需适配。
- [x] 3.4 **上机构建验证通过**：`flange build -f amp`(amp-rtt) 产出合法 FIT `amp.img`(load=0x07000000)，且 SDK 树零写入(`git status` 干净、无 `.o`/`__pycache__`/`.sconsign`)。构建中暴露并修复 3 处 staging 问题：① 只 stage 单 BSP 目录 → 缺兄弟 `../tools`(buildutil)/`../common`；② RT-Thread SDK 未 vendor `common/hal` 子模块 → symlink 复用 `_HAL_ROOT`(布局逐一匹配)；③ rpmsg-lite SConscript 绝对 Glob 逃逸 variant_dir 就地写 `.o` → 改**全量镜像**(内核树 symlink、`bsp/rockchip` 整段 copy 可写)。

## 4. 增量哈希

- [x] 4.1 `builder/platforms/rockchip/__init__.py:amp_source_dirs`：rt-thread 模式追加 BSP 模板目录（`components/amp/rockchip/rt-thread/bsp/rockchip/{soc}-32`）；app overlay 目录已在（`components/app/<app>`）；RTOS 内核树不纳入（D7）。

## 5. app_spec / scaffold：rt-thread overlay 形态与脚手架

> 复用现有 `--build-system` 机制承载 mode（不新造 `--mode`）：rt-thread = `--build-system=scons`。

- [x] 5.1 `app_spec.py:VALID_BUILD_SYSTEMS`（L18）加 `"scons"`。验证：`build.system: scons` 的 amp app.yaml 通过 `load_spec`（§7 建 app 后连带验证）。
- [x] 5.2 `scaffold.py:_VALID_COMBINATIONS`（L48-50）：加 `("amp", "scons")`；保留既有 `("amp","amp")`（hal）。
- [x] 5.3 新增 `builder/templates/amp/scons/applications/main.c.tpl`（从核入口，含 `${name}` 与 rpmsg 提示注释）；SConscript 由 BSP 模板提供；app.yaml 由共享 `templates/app.yaml.tpl` 渲染（build.system=scons）；`.config` 不入脚手架（按需在 demo app 加，见 §6）。
- [x] 5.4 CLI 复用 `envsetup.sh` 既有 `--build-system=<sys>`（L684）→ `flange create app <name> --type=amp --build-system=scons`，无需改 CLI。
- [ ] 5.5（可选，本变更跳过）补全 hal 的 `templates/amp/amp/`（现缺 CMakeLists/app.yaml 模板）——与 rt-thread 无关，留待独立整理。

## 6. 新建 rt-thread amp app（rk3568_amp_rtt_demo，完整 echo）+ tspi-rk3566 product

- [x] 6.1 **调研**（Explore agent）：Linux-rpmsg 模式下从核 rpmsg 初始化由 app 自管。初判「用厂商 `rpmsg_test.c` 现成 echo（开 COMMON_TEST flag）」——**上板证伪**：① 厂商测试硬编码 link-id `SET_LINK_ID(0,3)=0x03`（R=3，与 stock 内核驱动 rpmsg-rx=ch0 不匹配、且与我们 dts 的 0x10 不一致 → 卡 wait_for_link_up）；② 该 flag 才让 `board_base.c` 把 222 放进 GIC 白名单,但它同时会让厂商测试在 0x03 抢跑。故**弃用厂商测试,改自写 echo（link-id 0x10）+ 自行补 222 白名单**（见 6.2、design D10）。
- [x] 6.2 `flange create app rk3568_amp_rtt_demo --type=amp --build-system=scons` 生成 overlay,`applications/main.c` 落**自写 rpmsg echo**：`rpmsg_lite_remote_init(link_id 0x10=SET_LINK_ID(1,0))` → `wait_for_link_up` → `rpmsg_ns_announce("rpmsg-ap3-ch0")` → `rpmsg_queue_recv` 回 `rpmsg_lite_send` echo。**关键：init 前先 `HAL_GIC_Init(&amp_extra_gic)` 增量把 `MBOX0_CH3_A2B_IRQn`(222) 补进 AMP GIC 白名单**（否则 gicInit=0 下 `HAL_GIC_Enable(222)` 被 `GIC_AmpCheckIrqValid` 挡回、从核收不到 kick）。**无 `.config` 覆盖**（不开 COMMON_TEST；RT_USING_RPMSG_LITE/LINUX_RPMSG BSP 默认已开）。验证：app_spec 加载 OK、`_amp_app_dir(rt-thread)` 接受、编译通过。
- [x] 6.3 `components/board/tspi-rk3566/config.py`：`products` 加 `'amp-rtt'`；amp 段加 `enabled/mode/app:amp-rtt`；`bootloader.+defconfig:amp-rtt` + `kernel.dts:amp-rtt`（复用 `tspi-rk3566-amp`）+ `kernel.+defconfig:amp-rtt`（RPMSG）；分区抽成 `_AMP_PARTITIONS` 常量、`partitions:amp` 与 `:amp-rtt` 各引用一次（条件键单值匹配、不支持多 product）。验证：`resolve_config('tspi-rk3566','amp-rtt','release')` → mode=rt-thread/app=rk3568_amp_rtt_demo/soc_project=rk3568/cpu_base=0x7000000/含 amp 分区；amp(hal) 与 default product 不受影响。

## 7. 构建与上板验证

- [x] 7.1 `flange docker rebuild`(装 scons) + `lunch tspi-rk3566-amp-rtt-release` + `flange build -f amp`：amp 组件走 rt-thread 路径产合法 FIT `amp.img`(344KB, load=0x07000000, amp3 firmware 节点)。整盘 image 集成（amp.img → amp 分区）为 mode 无关既有逻辑，随 §7.2 全量 `flange build` 验证。
- [x] 7.2 **上板通过**：从核 UART4 打印 `rk3568_amp_rtt_demo: cpu3 up` → `rpmsg: remote init (link_id 0x10)` → `link up!` → `ept 'rpmsg-ap3-ch0' announced`。（注:本板 adb 触发不了 maskrom、`flange flash` 远程不可用,用 `adb dd` 写未挂载的 amp 分区刷入,与 flange flash 对该分区等价;修复在源码,后续正常 `flange build` 自带。）
- [x] 7.3 **上板通过**：Linux `dmesg` 出现 `creating channel rpmsg-ap3-ch0 addr 0x3003`；`/sys/bus/rpmsg/devices/` 有 `virtio0.rpmsg-ap3-ch0.-1.12291`。
- [x] 7.4 **端到端 echo 通过**：经 `/dev/rpmsg_ctrl0` 的 `RPMSG_CREATE_EPT_IOCTL` 建 `/dev/rpmsg0`，写 `hello from linux` → 读回从核 echo `Rockchip rpmsg linux test!`。

## 8. 文档与归档

- [x] 8.1 更新 wiki：`amp-构建器`（补 rt-thread 路径：可写 RTT_ROOT 镜像 + env 注入）、`AMP-协处理器与rpmsg`（**订正**：rt-thread 侧三约束**不**由 BSP 默认满足——link-id 需 0x10、222 需 app 自行 `HAL_GIC_Init` 补进白名单）、`tspi-rk3566`（amp-rtt product）。
- [ ] 8.2 `openspec archive add-amp-rt-thread-mode -y`，提交。
