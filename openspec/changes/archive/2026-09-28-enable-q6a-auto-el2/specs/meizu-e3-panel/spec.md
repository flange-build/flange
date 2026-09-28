## MODIFIED Requirements

### Requirement: radxa-dragon-q6a 启用 meizu-e3-bringup product

`components/board/radxa-dragon-q6a/config.jsonnet` MUST 在 `products` 列表中追加 `meizu-e3-bringup`（与既有 `default` 并列），并 MUST 在该 product 条件键下注入 `packages: ["meizu-e3-panel"]`。`default` product MUST 不引入本包，使 `radxa-dragon-q6a-default-{debug,release}` 产物与本变更前**字节等价**。lunch target `radxa-dragon-q6a-meizu-e3-bringup-{debug,release}` MUST 由现有 product/variant 机制自动生成。

#### Scenario: default product 字节等价

- **WHEN** lunch `radxa-dragon-q6a-default-debug`，build 出 raw.img
- **THEN** 与本变更前同一 lunch target 的产物字节等价（cache 命中，hash 不变）

#### Scenario: meizu-e3-bringup product 引入包

- **WHEN** lunch `radxa-dragon-q6a-meizu-e3-bringup-debug`，build
- **THEN** `config["packages"]` 含 `"meizu-e3-panel"`
- **AND** kernel oot_modules 含 `sec_ts` / `sgm37604a` / `panel_meizu_e3`
- **AND** `boot.overlays.package` 含 `qcom-qcs6490-radxa-dragon-q6a-meizu-e3-panel.dtbo`
- **AND** rootfs `/boot/qcs6490-radxa-dragon-q6a-kvm.dtb` 是 KVM 组合 DTB（base dtb 叠加 Radxa KVM overlay）与该 dtbo 经 `fdtoverlay` 合并的产物（见 [[build-time-dtb-overlay-merge]]）
