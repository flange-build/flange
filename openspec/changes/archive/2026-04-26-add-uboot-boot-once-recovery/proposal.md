## Why

当前 `flange recovery enter` 曾通过修改 `/boot/extlinux/extlinux.conf` 的
`DEFAULT` 行进入 recovery，语义是持久切换；如果用户忘记切回 normal，设备会
持续进入 recovery。recovery 进入本质上是一次性的 boot reason，应由 kernel 和
U-Boot 消费，不应写成 extlinux 配置文件中的持久状态。

## What Changes

- boot 分区生成两份 extlinux 配置：
  - `/extlinux/extlinux.conf`：normal 系统；
  - `/extlinux/recovery.conf`：recovery 系统。
- `recoveryctl recovery` 默认调用 Linux `reboot(2)` 的 `RESTART2` 形式传递
  `"recovery"`；`recoveryctl loader` 同理传递 `"loader"`。
- Rockchip U-Boot 读取 reboot reason 后选择本次 sysboot 使用
  `extlinux.conf` 或 `recovery.conf`；读取到 recovery boot reason 后由
  Rockchip 既有逻辑清除寄存器，保持 one-shot 语义。
- 可选支持 `flange_boot_once=recovery` 作为断电保持兜底；U-Boot 读取后立即
  清理该变量，并选择 `recovery.conf`。
- `flange recovery enter/reboot` 改为调用新的设备端入口，不再依赖修改
  `extlinux.conf` 的 `DEFAULT` 行。

## Non-Goals

- 不引入 misc 分区、OTA、A/B 分区切换或自动回滚策略。
- 不把 extlinux 文件变成模式判断脚本；extlinux 只描述如何启动对应系统。
- 不要求所有平台立即完成实机验证；首版以 Rockchip RK3566 路径为主要落地对象，
  A733 记录为待补齐 boot reason 与实机验证。

## Capabilities

### Modified Capabilities

- `recovery-boot`: recovery 启动入口从持久修改 extlinux 默认项改为
  U-Boot 根据 reboot reason 选择 extlinux 配置文件。
- `recovery-usb-flash`: `flange recovery enter` 与 `flange recovery reboot`
  的模式切换语义改为传递 Linux reboot reason，并保留 boot-once env 作为可选
  持久兜底。

## Impact

- 影响 `builder/platforms/*/boot.py` 的 boot 分区 extlinux 文件生成。
- 影响 `components/app/recoveryctl/` 的 reboot 实现与测试。
- 影响 Rockchip bootloader 补丁，需要在 U-Boot 启动选择阶段设置
  `flange_extlinux_conf`。
- 影响 `docs/recovery.md`、`README.md` 与 `ProjectSpec.md` 对 recovery
  进入/退出机制的描述。
