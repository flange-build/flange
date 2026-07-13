# ARM64 回归基线

记录日期：2026-07-11

## 仓库与运行环境

- 分支：`main`
- 基线提交：`bc16d4915d3cf3cbfd9d56e5d6afab44780f1fb2`
- 本机 Python：`3.11.8`（项目元数据要求 `>=3.12`，因此测试差异需要保留此环境信息）

## 代表 target 配置

### TSPI RK3566 default

- target：`tspi-rk3566-default-release`
- 架构：`aarch64`
- kernel：`Image` 隐式默认，DTS 目录 `rockchip`，DTS
  `tspi-rk3566-user-v10-ext39-linux`
- bootloader：Radxa U-Boot `next-dev-v2026.01`，`rk3568_defconfig`
- 分区：GPT、512 字节 sector、idbloader/uboot/boot/recovery/rootfs
- AMP：关闭

### TSPI RK3566 amp-rtt

- target：`tspi-rk3566-amp-rtt-release`
- kernel DTS：`tspi-rk3566-amp`
- U-Boot：`rk3568_defconfig + CONFIG_AMP=y + CONFIG_ROCKCHIP_AMP=y`
- AMP：RT-Thread、CPU3、`rk3568_amp_rtt_demo`
- 分区：GPT、512 字节 sector，amp 位于 recovery 与 rootfs 之间

### Radxa ROCK 4D / RK3576

- target：`radxa-rock-4d-default-release`
- 架构：`aarch64`
- kernel：DTS `rk3576-rock-4d`，DTS 目录 `rockchip`
- bootloader：`rock-4d-spi-rk3576_defconfig`，idbloader 走 `boot_merger`
- 存储选择：`SATA`（UFS）
- 分区：GPT、4096 字节 sector、boot/recovery/rootfs

### Radxa ROCK 5B / RK3588

- target：`radxa-rock5b-default-release`
- 架构：`aarch64`
- kernel：DTS `rk3588-rock-5b`，DTS 目录 `rockchip`，panthor fragment
- bootloader：`rk3588_defconfig`
- 分区：GPT、512 字节 sector、idbloader/uboot/boot/recovery/rootfs

## 当前产物契约

变更前 `builder.cache.REQUIRED_ARTIFACTS` 对 Rockchip 的关键要求为：

- kernel：`Image` 与至少一个 `*.dtb`
- bootloader：`u-boot.itb`、`idbloader.img`、`miniloader.bin`
- boot：`boot.img`
- rootfs：`rootfs.img`
- amp（启用时）：`amp.img`
- image：`raw.img`

## 测试基线

执行：

```text
python3 -m pytest \
  tests/config/test_registry.py \
  tests/config/test_rk3576_soc.py \
  tests/config/test_rk3588_soc.py \
  tests/builder/test_cache.py \
  tests/builder/test_rockchip_parameter.py \
  tests/builder/test_rockchip_image_sector.py \
  tests/builder/test_rockchip_storage_select.py \
  tests/builder/test_rockchip_amp_rtthread_config.py -q
```

结果：155 项中 140 passed、15 failed。失败全部来自既有 `tests/builder/test_cache.py`：

- 多个 fixture 用 `BuildCache.__new__()` 绕过 `__init__`，没有初始化 `_hash_cache`；
- 测试仍调用已更名的 `_hash_app_sources` 与 `_compute_rootfs_customize_hash`。

其余 registry、RK3576、RK3588、parameter、sector size、storage select 与 AMP RT-Thread 配置测试
均通过。后续回归需区分这些基线失败与本变更新增失败；若修改 cache，应同步修复这些陈旧 fixture。
