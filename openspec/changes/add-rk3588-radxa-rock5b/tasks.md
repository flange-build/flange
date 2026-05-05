## 1. 前置排查与重构（mkimage_chip 字段）

- [x] 1.1 阅读 `builder/config/validate.py`，确认 `rkbin` 块字段约束；判断新增 `mkimage_chip` 是否需要在 schema/validator 处显式声明
- [x] 1.2 在 `components/platform/rockchip/rk3566/config.py` 的 `SOC["rkbin"]` 字段中新增 `"mkimage_chip": "rk3568"`
- [x] 1.3 修改 `builder/platforms/rockchip/bootloader.py`：将 `compile()` 中 `["-n", "rk3568", "-T", "rksd", ...]` 改为读取 `config["rkbin"]["mkimage_chip"]`；缺失字段抛出含字段名的明确错误
- [x] 1.4 写或更新单元测试覆盖 `mkimage_chip` 缺失场景与正常读取场景（`tests/test_rockchip_bootloader.py` 或新建文件）
- [ ] 1.5 运行 `flange build bootloader` 分别构建 `radxa-zero3w-default-debug`、`tspi-rk3566-default-debug`、`radxa-cubie-a7z-default-debug`、`orangepi-cm4-default-debug`，比对重构前后 `idbloader.img` 与 `u-boot.itb` SHA256 byte-identical（B 路线推迟到任务组 6 一并实测）
- [ ] 1.6 提交单 commit `refactor(platforms/rockchip): 把 mkimage chip 标签提到 SoC config`，确保 git diff 不混入后续 SoC 文件（B 路线跳过：用户最终统一 commit）

## 2. 新增 RK3588 SoC 配置

- [x] 2.1 创建目录 `components/platform/rockchip/rk3588/`
- [x] 2.2 编写 `components/platform/rockchip/rk3588/config.py`，导出 `SOC` 字典，字段包含：`platform="rockchip"`、`soc="rk3588"`、`arch="aarch64"`、`vendor="rockchip"`、`rkbin.{ini_prefix="RK3588", trust_ini_prefix="RK3588", mkimage_chip="rk3588"}`、`bootloader.{repo="https://github.com/radxa/u-boot", branch="next-dev-v2026.01", defconfig="rk3588_defconfig"}`、`kernel.{repo, branch, defconfig, dts_dir}` 与 RK3566 完全相同、`boot.{dtb_overlays=[], vendor_overlays=[], default_overlays=[], kernel_args="console=ttyS2,1500000 loglevel=7"}`、`partitions.entries` 沿用 RK3566 布局
- [x] 2.3 写单元测试覆盖 `_load_soc_config("rk3588")` 与 `_discover_soc_configs()`，验证 SoC 自动发现与字段值
- [ ] 2.4 提交 commit `feat(platform/rockchip): 新增 rk3588 SoC 配置`（B 路线跳过：用户最终统一 commit）

## 3. 新增 RK3588S SoC 配置（通路占位）

- [x] 3.1 创建目录 `components/platform/rockchip/rk3588s/`
- [x] 3.2 编写 `components/platform/rockchip/rk3588s/config.py`，导出 `SOC` 字典，字段与 `rk3588/config.py` 100% 相同（含 `defconfig="rk3588_defconfig"`），仅 `soc="rk3588s"` 不同
- [x] 3.3 写单元测试覆盖 `_load_soc_config("rk3588s")`，验证 SoC 自动发现与 `rkbin.mkimage_chip == "rk3588"`
- [ ] 3.4 提交 commit `feat(platform/rockchip): 新增 rk3588s SoC 通路占位`（B 路线跳过：用户最终统一 commit）

## 4. 新增 board radxa-rock5b 配置

- [x] 4.1 创建目录 `components/board/radxa-rock5b/` 与子目录 `overlay/etc/`
- [x] 4.2 编写 `components/board/radxa-rock5b/config.py`，导出 `BOARD` 字典：`board="radxa-rock5b"`、`soc="rk3588"`、`platform="rockchip"`、`kernel.dts="rk3588-rock-5b"`
- [x] 4.3 写 `components/board/radxa-rock5b/overlay/etc/hostname`，内容 `radxa-rock5b`
- [x] 4.4 写 `components/board/radxa-rock5b/overlay/etc/usbdevice.conf`，参考 `components/board/radxa-zero3w/overlay/etc/usbdevice.conf` 格式
- [x] 4.5 写单元测试覆盖 `get_board_config("radxa-rock5b")` 三层合并结果
- [ ] 4.6 提交 commit `feat(board): 新增 radxa-rock5b 板级配置`（B 路线跳过：用户最终统一 commit）

## 5. 知识库与文档

- [x] 5.1 创建 `wiki/boards/radxa-rock5b.md`，参考 `wiki/boards/radxa-zero3w.md` 的结构，记录 SoC、存储、串口、首版验证范围
- [x] 5.2 在 `wiki/boards/index.md` 增加 ROCK 5B 索引项
- [ ] 5.3 提交 commit `docs(wiki): 新增 radxa-rock5b 板子条目`（B 路线跳过：用户最终统一 commit）

## 6. 构建验证（容器内）

- [ ] 6.1 `lunch radxa-rock5b-default-debug`，确认 lunch target 自动出现
- [ ] 6.2 `flange build bootloader`：成功生成 `idbloader.img`（实测体积，对比 `0x4000 - 0x40 = 8128 sectors ≈ 4 MiB`）与 `u-boot.itb`
- [ ] 6.3 若 6.2 实测 idbloader 体积超过 0x4000 偏移：在本变更内调整 `rk3588/config.py` 的 `partitions.entries` 中 uboot 偏移与 boot/recovery 偏移；否则继续
- [ ] 6.4 `flange build kernel`：成功生成 Image + DTB（含 `rk3588-rock-5b.dtb`）+ modules
- [ ] 6.5 `flange build rootfs`：成功生成 rootfs.tar.zst
- [ ] 6.6 `flange build recovery`：成功生成 recovery.img（recovery 维护系统已在 platform 默认开启）
- [ ] 6.7 `flange build image`：成功生成完整 raw 镜像，5 个分区分别可见

## 7. 实板验证（ROCK 5B 实机）

- [ ] 7.1 准备 ROCK 5B 板 + USB-C OTG 线 + USB-TTL 串口转换器（接 UART2，1500000bps）
- [ ] 7.2 按住 MASKROM 按键上电，确认 `flange flash detect` 识别到 Rockchip Maskrom 设备
- [ ] 7.3 `flange flash all radxa-rock5b-default-debug`：完成 idbloader / uboot / boot / recovery / rootfs 五分区刷写，无错误
- [x] 7.4 断开 MASKROM 重新上电，串口观察：依次出现 U-Boot SPL banner、U-Boot proper banner、Linux kernel banner（`Linux version 6.1.x ...`）
- [x] 7.5 systemd 启动至 multi-user.target，登录提示符出现
- [x] 7.6 板载 GbE 连网线，`ip addr show` 显示 eth0 已分配 IP
- [ ] 7.7 主机端 `ssh root@<rock5b-ip>` 登录成功，`uname -r` 输出与 BSP 一致
- [ ] 7.8 `recoveryctl recovery` 触发进入 recovery 模式；recovery 模式下能 ADB 连接

## 9. u-boot 分支统一调整（实施期间补加，详见 design Decision 1.5）

- [x] 9.1 `components/platform/rockchip/rk3566/config.py` 的 `bootloader.branch` 切到 `"next-dev-v2024.10"`
- [x] 9.2 `components/platform/rockchip/rk3588/config.py` 与 `rk3588s/config.py` 的 `bootloader.branch` 同样设为 `"next-dev-v2024.10"`
- [x] 9.3 `components/board/tspi-rk3566/config.py` 删除 `bootloader.commit` 字段
- [x] 9.4 `components/board/radxa-rock5b/config.py` 增加 `bootloader.defconfig="rock-5b-rk3588_defconfig"`（board 层覆盖 SoC generic）
- [x] 9.5 同步更新 `tests/config/test_rk3588_soc.py` 与 `tests/config/test_radxa_rock5b.py` 中 branch 与 defconfig 断言
- [x] 9.6 同步更新 `proposal.md` / `design.md` / `specs/rockchip-platform/spec.md` / `wiki/boards/radxa-rock5b.md`
- [ ] 9.7 清空 `.build/sources/bootloader/` 缓存目录（现网已有 v2026.01 / next-dev-buildroot 残留），用户操作

## 8. 收尾

- [x] 8.1 运行 `openspec validate add-rk3588-radxa-rock5b --strict`，所有校验通过
- [ ] 8.2 在本变更分支创建 PR，描述链接 proposal.md / design.md / spec.md，标注实板验证截图或串口日志片段
- [ ] 8.3 PR 合并后执行 `/opsx:archive add-rk3588-radxa-rock5b`，把 spec deltas 归档到 `openspec/specs/rockchip-platform/`
