## Context

recovery 进入路径应表达"下一次启动进入哪里"，而不是把 boot 分区里的
`extlinux.conf` 改成长期默认 recovery。用户态触发 `reboot("recovery")` 后，
kernel reboot-mode driver 将 boot reason 写入平台寄存器或 SRAM；U-Boot 是读取
并清除该状态的正确位置。

本变更采用职责拆分：

- Linux：通过 `recoveryctl recovery/loader/normal` 触发 reboot reason。
- U-Boot：读取 boot reason 或可选 `flange_boot_once`，选择本次 extlinux 配置。
- extlinux：只描述 kernel、dtb、rootfs 和 cmdline。

## Goals / Non-Goals

**Goals:**

- `flange recovery enter` 不再修改 boot 分区的 `extlinux.conf`。
- boot 分区同时提供 `extlinux.conf`（normal）与 `recovery.conf`（recovery）。
- Rockchip U-Boot 根据 `BOOT_MODE_RECOVERY` 或 `flange_boot_once=recovery`
  本次选择 `recovery.conf`。
- `recoveryctl loader` 预留同类 loader/download 入口。
- 回 normal 时清理可选 boot-once env，普通启动回到 `extlinux.conf`。

**Non-Goals:**

- 不实现 OTA、A/B 或自动回滚。
- 不新增 misc 分区。
- 不要求 A733 在本变更中完成 boot reason 驱动和 U-Boot 实机适配。

## Decisions

### D1: U-Boot 选择 extlinux 配置文件，而不是 extlinux label

normal 使用 `/extlinux/extlinux.conf`，recovery 使用 `/extlinux/recovery.conf`。
U-Boot 通过环境变量 `flange_extlinux_conf` 改变 distro boot 中的 sysboot 路径：

```text
sysboot ... ${prefix}extlinux/${flange_extlinux_conf}
```

默认值是 `extlinux.conf`；当 Rockchip boot mode 为 `BOOT_MODE_RECOVERY` 或
`flange_boot_once=recovery` 时改为 `recovery.conf`。

理由：boot reason 判断属于 U-Boot，extlinux 文件只保留启动配方；normal 与
recovery 可独立维护、独立测试。

### D2: 默认路径使用 Linux reboot reason

`recoveryctl recovery` 直接调用 `reboot(2)` 的 `LINUX_REBOOT_CMD_RESTART2`，
传入 `"recovery"`，避免依赖 BusyBox 或 systemctl 是否透传参数。

`flange_boot_once=recovery` 保留为可选断电保持兜底：只有显式请求持久路径时才写
U-Boot env，且 U-Boot 读取后立即清除并尝试 `saveenv`。

### D3: 不再保留 extlinux DEFAULT fallback

当平台缺少 reboot reason 或 boot-once 能力时，应补齐平台适配，而不是回退到修改
`extlinux.conf`。旧版遗留的 `DEFAULT flange-recovery` 只作为排障/手工修复场景
处理，不再作为正常进入 recovery 的 fallback。

## Risks / Trade-offs

- [Risk] 目标平台的 kernel 未启用 reboot-mode，`reboot("recovery")` 不会写入
  boot reason。→ Mitigation: Rockchip 先验证 DTS/config；A733 记录待适配。
- [Risk] U-Boot env 若配置为 `ENV_IS_NOWHERE`，持久 boot-once 不可用。
  → Mitigation: 默认路径不依赖 env，只把 env 作为显式持久兜底。
- [Risk] 直接 syscall 的架构号需要维护。→ Mitigation: recoveryctl 声明常见
  aarch64/arm/x86_64 编号，未知架构明确报错。

## Migration Plan

1. boot builder 生成 `extlinux.conf` 与 `recovery.conf` 两份配置。
2. Rockchip U-Boot 补丁根据 boot reason / `flange_boot_once` 设置
   `flange_extlinux_conf`。
3. `recoveryctl` 增加 `recovery`、`loader`、`normal` 入口，默认使用
   `reboot(2)` restart2。
4. 更新宿主机 CLI 文案和 recovery 文档，说明不再修改 extlinux DEFAULT。
5. 保留 RK3566 实机 normal → recovery → normal 验证任务。

## Open Questions

- A733 BSP 中应优先复用 workmode、RTC scratch register 还是已有 reboot-mode？
- 是否在后续 OTA 方案中单独设计持久状态区，而不是复用 boot-once env？
