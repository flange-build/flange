## 1. 板级配置与 overlay

- [x] 1.1 `components/board/orangepi-cm4/config.jsonnet` 的 `rootfs+` 追加 `packages+: ['bluez']`，并注释说明 base 包集合不含它、desktop 只是被 ubuntu-desktop 顺带拉入
- [x] 1.2 新增 `overlay/etc/systemd/system/bluetooth-orangepi-cm4.service`：`Type=simple` 执行 `btattach -B /dev/ttyS1 -P bcm`，`ExecStartPre` 调用解除脚本，`Restart=on-failure`；注释写明为何不是 oneshot、为何内核不自动 attach
- [x] 1.3 新增 `overlay/usr/lib/flange/bt-unblock.sh`（0755）：按 `name` 匹配 `bt_default` 直接写 `soft`；注释写明 `rfkill unblock` 为何无效、索引为何不能写死
- [x] 1.4 新增 `overlay/etc/systemd/system/multi-user.target.wants/bluetooth-orangepi-cm4.service` 符号链接（相对目标 `../bluetooth-orangepi-cm4.service`），确认 git 存为 mode 120000
- [x] 1.5 验证四个 product 求值后 `rootfs.packages` 均含 `bluez`

## 2. 构建验证

- [ ] 2.1 `flange build rootfs` 成功
- [ ] 2.2 核对产物镜像：unit、`wants` 符号链接、`bt-unblock.sh`（含可执行位）均落到正确路径，`bluez` 已安装
- [ ] 2.3 `flange build` 产出完整镜像

## 3. 实机验收

- [x] 3.1 按 overlay 形态部署到实机（符号链接 enable，非 `systemctl enable`），确认 `systemctl is-enabled` 返回 `enabled`
- [x] 3.2 清除 `/var/lib/systemd/rfkill/*` 模拟刷写后首启并重启，确认 `hci0` 自动就位、服务 active、`bt_default` soft=0
- [x] 3.3 确认 `dmesg` 含 `BCM4345C5 'brcm/BCM4345C5.hcd' Patch` 与 `BT 5.2 [Version: 1039.1086]`
- [x] 3.4 确认开机就位的 `hci0` 可 BLE 扫描
- [ ] 3.5 刷写正式镜像后复验上述各项，并回归确认 WiFi `wlan0` 仍正常

## 4. 文档与归档

- [x] 4.1 更新 `wiki/boards/orangepi-cm4.md` 的 BT 章节：attach 机制、rfkill 踩坑、验收命令
- [x] 4.2 `wiki/log.md` 追加 sync 条目
- [ ] 4.3 `openspec validate` 通过后归档，确认 spec delta 落地
