## ADDED Requirements

### Requirement: Rockchip 平台支持 RK3576 SoC 配置发现

`components/platform/rockchip/rk3576/config.py` 必须（SHALL）作为合法 SoC 配置
文件存在并导出 `SOC` 字典，使 `builder/config/registry.py:_load_soc_config("rk3576")`
成功返回该字典。该 SoC 配置 MUST 至少声明：`platform="rockchip"`、`soc="rk3576"`、
`arch="aarch64"`、`vendor="rockchip"`、`rkbin.{ini_prefix,trust_ini_prefix,mkimage_chip}`、
`bootloader.{repo,branch,defconfig}`、`kernel.{repo,branch,defconfig,dts_dir}`、
`boot.kernel_args`、`partitions.entries`。其中内核仓库、分支与 base defconfig
必须（SHALL）与 RK3588 一致（同 argon BSP 全 SoC 树）。

#### Scenario: 自动发现 rk3576

- **WHEN** `components/platform/rockchip/rk3576/config.py` 存在并导出 `SOC` 变量
- **THEN** `_discover_soc_configs()` 返回结果包含 key `"rk3576"`
- **AND** `_load_soc_config("rk3576")` 返回字典中 `rkbin.ini_prefix == "RK3576"` 且 `rkbin.trust_ini_prefix == "RK3576"` 且 `rkbin.mkimage_chip == "rk3576"`

#### Scenario: rk3576 内核配置对齐 rk3588

- **WHEN** 比较 `_load_soc_config("rk3576")` 与 `_load_soc_config("rk3588")` 的 `kernel` 块
- **THEN** 两者 `kernel.branch` 相同，均为 `"linux-6.1-stan-rkr5.1"`
- **AND** 两者 `kernel.defconfig` 的 base（list 首项）均为 `"rockchip_linux_defconfig"`
- **AND** rk3576 的 `kernel.defconfig` list 含 `"rk3576_panfrost.config"`（rk3588 对应位置为 `"rk3588_panthor.config"`）

#### Scenario: rk3576 与 rk3588 不互相污染

- **WHEN** 同时解析 RK3576 板与 RK3588 板的合并配置
- **THEN** 两者 `rkbin.mkimage_chip` 分别为 `"rk3576"` 与 `"rk3588"`
- **AND** 两者 GPU fragment 分别为 `"rk3576_panfrost.config"` 与 `"rk3588_panthor.config"`

### Requirement: Rockchip GPU 开源驱动 fragment 按 SoC GPU 架构选型

`builder/platforms/rockchip/kernel.py` 的 `RockchipKernelBuilder` 必须（SHALL）
按 SoC 的 GPU 架构提供独立的开源 GPU config fragment 生成函数：RK3576
（Mali-G52，Bifrost）走 `_write_panfrost_fragment` 生成 `rk3576_panfrost.config`，
RK3588/RK3588S（Mali-G610，Valhall-CSF）走 `_write_panthor_fragment` 生成
`rk3588_panthor.config`。每个 fragment 函数对非目标 SoC 必须（SHALL）写空
fragment（满足 `make <name>.config` 合并要求，且不影响其他 SoC）。
`_write_panfrost_fragment` 对 RK3576 生成的内容 MUST 关闭闭源 mali_kbase
（`CONFIG_MALI_BIFROST`/`CONFIG_MALI_MIDGARD` 等）与 utgard（mali400/450），
并启用 `CONFIG_DRM_PANFROST=m`。

#### Scenario: rk3576 启用 panfrost fragment

- **WHEN** 为 RK3576 SoC 生成 kernel config fragment
- **THEN** `arch/arm64/configs/rk3576_panfrost.config` 含 `CONFIG_DRM_PANFROST=m`
- **AND** 含 `# CONFIG_MALI_BIFROST is not set`（闭源 kbase 被关闭）
- **AND** RK3576 SoC 的 `kernel.defconfig` list 引用了该 fragment

#### Scenario: panfrost fragment 对 RK3588 为空、不污染 panthor

- **WHEN** 当前构建 SoC 为 `rk3588`
- **THEN** 生成的 `rk3576_panfrost.config` 为空 fragment（仅注释）
- **AND** RK3588 的 GPU 路线仍由 `rk3588_panthor.config` 决定，行为不变

#### Scenario: 合并后闭源 kbase 在 RK3576 上确被关闭

- **WHEN** RK3576 完成 `rockchip_linux_defconfig` + 各 fragment 合并
- **THEN** 最终 `.config` MUST NOT 含 `CONFIG_MALI_BIFROST=y`
- **AND** 含 `CONFIG_DRM_PANFROST=m`
