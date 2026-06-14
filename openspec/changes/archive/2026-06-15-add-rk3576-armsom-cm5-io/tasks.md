## 1. kernel-rockchip 仓库改动（独立提交）

- [x] 1.1 核实 dts：`rk3576-armsom-cm5-io.dts` 及依赖 dtsi 完整在树内；
  `rk3576-armsom-cm5.dtsi` 已含 `&gpu { mali-supply = ...; status = "okay"; }`
  （GPU 已使能，故 1.3 无需改 dts）
- [x] 1.2 `Makefile` 增 `dtb-$(CONFIG_ARCH_ROCKCHIP) += rk3576-armsom-cm5-io.dtb`
  （字母序插在 ebook 前）
- [x] 1.3 N/A — GPU 节点已在 `rk3576-armsom-cm5.dtsi` 使能（`status="okay"` +
  `mali-supply`），compatible `arm,mali-bifrost` 与 panfrost 对位，无需板级改动
- [x] 1.4 kernel-rockchip 提交（commit 3d55028，分支 linux-6.1-stan-rkr5.1）

## 2. builder：panfrost GPU fragment

- [x] 2.1 `builder/platforms/rockchip/kernel.py` 新增 `_write_panfrost_fragment`，
  结构对齐 `_write_panthor_fragment`：仅 `soc=="rk3576"` 写实质内容，其余写空
- [x] 2.2 fragment 内容：关 mali_kbase（`# CONFIG_MALI_BIFROST/MIDGARD/...`）+
  关 mali400/450 utgard + `CONFIG_DRM_PANFROST=m`（与 panthor 同用 =m）
- [x] 2.3 `configure()` 接入 `_write_panfrost_fragment`（panthor 之后、panel 之前）
- [x] 2.4 验证：rk3588 上 `rk3576_panfrost.config` 为空、`rk3588_panthor.config`
  不变（test_rockchip_kernel_panfrost_fragment + test_rk3588_soc 全过）

## 3. RK3576 SoC 数据层

- [x] 3.1 新建 `components/platform/rockchip/rk3576/config.py`（导出 `SOC`）
- [x] 3.2 `rkbin`：`ini_prefix/trust_ini_prefix="RK3576"`、`mkimage_chip="rk3576"`
- [x] 3.3 `kernel`：repo/branch（`linux-6.1-stan-rkr5.1`）/base defconfig 对齐
  rk3588；`defconfig` list 追加 `"rk3576_panfrost.config"`
- [x] 3.4 `bootloader`：radxa u-boot `next-dev-v2026.01` + generic
  `rk3576_defconfig`（注释：bring-up 若该分支无 generic，board 层覆盖板级
  defconfig）
- [x] 3.5 `boot.kernel_args=console=ttyS0,1500000 loglevel=4`（UART0，
  rk3576-linux.dtsi serial-id=0）；`partitions` 对齐 rk3588
- [x] 3.6 验证 `_load_soc_config("rk3576")`（test_rk3576_soc 全过）

## 4. armsom-cm5-io board 数据层

- [x] 4.1 新建 `components/board/armsom-cm5-io/config.py`（导出 `BOARD`）
- [x] 4.2 `board="armsom-cm5-io"`、`soc="rk3576"`、`platform="rockchip"`、
  `kernel.dts="rk3576-armsom-cm5-io"`；不覆盖 SoC GPU/bootloader
- [x] 4.3 N/A（首版裸机）— 不携带板级 overlay，与 radxa-rock5b 最小形态一致；
  `rootfs.root_password="1234"` 保证 bring-up ssh 登录
- [x] 4.4 验证 `get_board_config("armsom-cm5-io")` 合并 + lunch target
  （test_armsom_cm5_io 全过，含 `armsom-cm5-io-default-{debug,release}`）

## 5. 测试

- [x] 5.1 `tests/config/test_rk3576_soc.py`（20 项）：SoC 发现、rkbin、kernel
  对齐 rk3588、panfrost fragment 引用、UART0、无 mali-csf
- [x] 5.2 `tests/config/test_armsom_cm5_io.py`（12 项）+
  `tests/builder/test_rockchip_kernel_panfrost_fragment.py`（5 项）：board 合并、
  lunch、不覆盖 SoC GPU、fragment 行为
- [x] 5.3 增量回归：test_rk3588_soc（34）+ panel fragment（4）全过，
  `rk3588_panthor.config` 与 rk3588 defconfig 不变
  （注：test_radxa_rock5b 的 root_password 用例为既有红，HEAD 版 rock5b 即
  `root_password=None`，与本变更无关）

## 6. 构建与上板验证（待执行 — 需 Docker 构建 + 实板）

- [ ] 6.1 lunch `armsom-cm5-io-default-debug`，`flange build`，确认产出镜像
  （含 `rk3576-armsom-cm5-io.dtb`，GPU 节点 okay）
- [x] 6.2 panfrost 内核驱动实测（adb）：`panfrost 27800000.gpu: mali-g52
  id 0x7402`、`shader_present=0x7`（G52 MC3 三核）、`Initialized panfrost
  1.2.0 for 27800000.gpu`；模块 panfrost/gpu_sched/drm_shmem_helper 加载、
  绑定 27800000.gpu；`/dev/dri/renderD130`+card2；无 mali kbase（闭源确被关）
- [x] 6.3 panfrost 用户态实测（adb，装 mesa-utils-extra）：eglinfo
  `EGL driver name: panfrost`、`renderer: Mali-G52 r1 (Panfrost)`、
  OpenGL 3.1 core + **OpenGL ES 3.1**（Mesa 25.2.8）；GL context 创建成功、
  无 GPU fault；devfreq simple_ondemand 正常（idle 300MHz）。**panfrost 全栈
  通过。** 板已正常启动（OP-TEE 打包生效）
- [ ] 6.4 更新板级 wiki/文档

## 7. bootloader OP-TEE 打包（bring-up 实测发现，决策 6）

- [x] 7.1 定位根因：generic rk3576_defconfig 开 OPTEE_CLIENT 但 SPL 未加载
  OP-TEE + make_fit_atf.sh 注释了 gen_bl32_node → u-boot halt
  "Please RESET the board"
- [x] 7.2 全平台 OP-TEE 普查：rk3566/68/82/88/88s 均走 Direction 2（0003/0005
  关 client）；rk3576 按用户决策走 Direction 1（打包 OP-TEE）
- [x] 7.3 板级补丁 `components/board/armsom-cm5-io/patches/bootloader/`：
  0002（make_fit_atf.sh 取消注释 gen_bl32_node）；`git apply --check` 通过
- [x] 7.4 修正 bring-up 编译失败：首次加的 0001（CONFIG_SPL_OPTEE=y）会拉入
  armv7 专用 spl_optee.S，arm64 编不过 → 删除。fit_args.sh 在 CONFIG_ARM64=y
  时令生成器 ARCH=arm64，gen_bl32_node 跳过 SPL_OPTEE 门槛，仅需
  TEE_LOAD_ADDR（自动算）即生成 optee 节点 + LOADABLE_OPTEE 接入 loadables
- [x] 7.5 rk3576 上板复测：build 通过、启动成功（OP-TEE 打包生效）
- [x] 7.6 按用户决策**提升为平台级**：删板级 0002，新增平台
  `0006-rockchip-fit-uncomment-bl32-node.patch`，全 rockchip SoC
  （rk3566/3568/3576/3582/3588/3588s）统一打包 OP-TEE；`--reverse --check`
  验证 0006 与已应用态匹配
- [ ] 7.7 全平台复测（用户）：rk3566/3568/3588/3582/3588s 各板 rebuild+flash，
  确认新增 optee 节点后仍正常启动（OP-TEE 由 BL31 加载）
- [x] 7.8 按用户决策（Option B）删除 0003/0005 → 恢复 OPTEE_CLIENT，全平台
  full Direction 1（client 开 + OP-TEE 打包）。平台 bootloader 补丁集现为
  0002/0004/0006
- [ ] 7.9 wiki 同步（`/sync-wiki`）：`platforms/rockchip-平台.md` OPTEE 段与
  `log.md` 仍描述"0003/0005 关 OPTEE_CLIENT"，已过时
- [ ] 7.10 全平台复测（用户）：rk3566/3568/3582/3588/3588s 各板 rebuild+flash，
  确认 client 重启用 + OP-TEE 打包后正常启动
