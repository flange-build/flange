# Recovery 实机验收清单（任务 9.7–9.12）

由用户在真实 RK3566 设备（默认 tspi-rk3566 / radxa-zero3w）上执行。完成
每一步后在 tasks.md 中勾选对应任务。命令均假设：

- 已经 `source envsetup.sh` 并 `lunch tspi-rk3566` 或同等板子
- `flange build` 已完成（详见 §9.6）
- 设备 USB 线连到宿主机；宿主机 `adb` 在 PATH 中

## 9.7 全量刷写后 normal 系统启动成功

```bash
# 上电进入 maskrom（按住 maskrom 键再插 USB），然后：
flange flash
# 刷写完成后设备会自动重启
```

**期望**：

- 串口/HDMI 看到正常 kernel boot 日志（不是 recovery）
- `dmesg | head` 无明显错误
- `cat /proc/cmdline` 包含 `root=LABEL=rootfs`，**不**包含 `flange.mode=recovery`
- ADB 可连接：`adb devices` 列出设备
- 设备端：`recoveryctl mode` 输出 `normal`

通过后勾选 `tasks.md` §9.7。

## 9.8 `flange recovery enter` 进入 recovery

```bash
# 宿主机
flange recovery enter
```

**期望输出**：

```
正在请求设备切换到 recovery 模式...
等待设备重启进入 recovery...
✓ 已进入 recovery 模式
```

**验证**：

- 串口/HDMI 看到 recovery rootfs 启动（hostname/login 与 normal 不同；
  没有 normal 系统的应用 service）
- `adb shell recoveryctl mode` 输出 `recovery`
- `adb shell cat /proc/cmdline` 包含 `flange.mode=recovery` 与
  `root=LABEL=recovery`

通过后勾选 §9.8。

## 9.9 `flange recovery list` 输出真实分区状态

```bash
flange recovery list
flange recovery list --json
```

**期望**：

- mode 行为 `recovery`
- 6 个分区（idbloader / uboot / boot / rootfs / recovery / userdata）
- recovery 行 `prot` 列为 `Y`
- raw 类（idbloader / uboot）`prot` 列为 `Y`
- recovery 自身 `mount` 列显示 `/`（recovery 当前作为根挂载）
- boot `mount` 列显示 `/boot`

通过后勾选 §9.9。

## 9.10 `flange recovery backup rootfs ...` 生成备份

```bash
flange recovery backup rootfs ~/rootfs-backup-$(date +%F).img.zst
ls -lh ~/rootfs-backup-*.img.zst
```

**期望**：

- 命令输出 `recoveryctl backup rootfs ...` 与 `拉取备份至 ...`，最后
  `✓ 备份完成：...`
- 文件存在；大小约 200–500MB（zstd 压缩后）
- 可通过 `zstd -t ~/rootfs-backup-*.img.zst` 校验完整性
- 可通过 `zstd -d -c ~/rootfs-backup-*.img.zst | file -` 看到 ext4
  filesystem data

通过后勾选 §9.10。

### 进阶（可选）：未压缩备份

```bash
flange recovery backup rootfs ~/rootfs-backup-raw.img --compress none
file ~/rootfs-backup-raw.img   # 应直接是 ext4 filesystem data
```

## 9.11 `flange recovery flash rootfs ...` 成功刷写 rootfs

> **强烈建议先做完 9.10 备份再执行本步骤**：刷错可由备份恢复。

```bash
flange recovery flash rootfs .build/target/tspi-rk3566/default/debug/rootfs/rootfs.img
```

**期望输出**：

```
上传 rootfs.img ...
recoveryctl flash rootfs ...
✓ rootfs 已刷写
```

**验证**：

- 设备端无报错；写入过程中无中断
- 设备端 `recoveryctl list --json` 显示 rootfs `device_size_bytes` 仍正常
- 命令耗时合理（取决于镜像大小，通常 30s–2min）

如果 `--sha256` 不匹配或镜像过大，flash 应直接被设备端拒绝并打印中文错误。

通过后勾选 §9.11。

### 故意失败路径（手动验证错误处理）

可选：把镜像故意挪个名字再 flash，确认报错友好：

```bash
flange recovery flash rootfs /tmp/no-such-file.img    # 应报"镜像文件不存在"
flange recovery flash rootfs /etc/hostname            # 应报 sha256/大小相关错误
```

## 9.12 `flange recovery reboot` 返回 normal

```bash
flange recovery reboot
```

**期望**：

- 命令输出 `recoveryctl reboot normal ...` 与 `✓ 已请求重启`
- 设备重启后串口看到 normal kernel boot 日志
- ADB 重新可连接（normal 系统下）
- `adb shell recoveryctl mode` 输出 `normal`
- `adb shell cat /proc/cmdline` 不再包含 `flange.mode=recovery`
- 9.11 刷入的新 rootfs 内容生效（例如 hostname / 用户文件已更新）

通过后勾选 §9.12。

## 失败时的回滚

任一阶段出问题，常见恢复路径：

1. **设备无法启动 normal 也无法启动 recovery**：U-Boot 控制台手动选 label
   或 `bootcmd_extlinux`（参考 docs/recovery.md "排障"小节）。
2. **rootfs 损坏**：进 recovery，用 9.10 的备份 `flange recovery flash
   rootfs ~/rootfs-backup-...img`（zst 备份需要先 `zstd -d`）。
3. **bootloader/分区表损坏**：宿主机 `flange flash`（USB upgrade_tool）
   全量刷回。

完成全部 6 步后整个 add-recovery-boot 变更进入 done 状态，可执行
`/opsx:archive add-recovery-boot` 归档。
