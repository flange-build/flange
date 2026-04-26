# Recovery 维护系统

flange 在 boot 分区中提供 normal 与 recovery 两条启动路径，并预留一个独立
的 `recovery` 分区，搭载基于 Ubuntu base 的维护系统。设备进入 recovery 后
可以通过 USB ADB 通道执行分区级线刷、备份与简单维护，不依赖网线或 Wi-Fi。

> Debian/Ubuntu 上 GPT 工具集对应的包名是 `gdisk`（而非项目名 gptfdisk）；
> recovery rootfs 默认安装 `parted` + `gdisk`。

本文聚焦于"用户视角的怎么用"和"出问题怎么查"。架构与设计取舍参见
[OpenSpec change `add-recovery-boot`](../openspec/changes/add-recovery-boot/)。

## 为什么需要 recovery

- **normal rootfs 损坏时仍能启动维护**：recovery 是独立分区与独立 rootfs，
  不与 normal 共享运行时状态。
- **在线刷写 rootfs 不破坏当前系统**：在 recovery 内 dd 写入 rootfs 时，
  normal rootfs 处于未挂载状态。
- **不依赖网络**：维护通道是 USB ADB；现场维护人员只需一根 USB 线缆。

## 分区与启动布局

启用 recovery 的 RK3566 板子默认分区布局：

| 名称 | 偏移 (sectors) | 大小 | 类型 | 备注 |
|------|----------------|------|------|------|
| idbloader | 0x40 | 4MB | raw | bootloader stage1 |
| uboot | 0x4000 | 4MB | raw | u-boot |
| boot | 0x8000 | 64MB | ext4 | 内核 + DTB + extlinux 配置 |
| **recovery** | **0x28000** | **512MB** | **ext4** | **维护系统** |
| rootfs | 0x128000 | remaining | ext4 | normal 系统（拉到 emmc 末尾） |

设计要点：

- recovery 紧贴 boot 之后、rootfs 之前 —— 维护工具按 GPT 顺序固定查找。
- rootfs 用 ``remaining`` 占满末尾，最大化容量；不再单独划 userdata 分区。
- 首次部署该布局必须整盘刷写（`flange flash`），不能从旧布局热升级。

boot 分区中有两份 extlinux 配置。正常启动读取
`/boot/extlinux/extlinux.conf`：

```
DEFAULT flange

label flange
  kernel /Image
  fdt /dtb/rockchip/<dts>.dtb
  append root=PARTLABEL=rootfs rootfstype=ext4 rootwait rw <kernel_args>
```

recovery 启动读取 `/boot/extlinux/recovery.conf`：

```
DEFAULT flange-recovery

label flange-recovery
  kernel /Image
  fdt /dtb/rockchip/<dts>.dtb
  append root=PARTLABEL=recovery rootfstype=ext4 rootwait rw flange.mode=recovery <kernel_args>
```

进入 recovery 时，`recoveryctl recovery` 直接调用 Linux `reboot(2)` 的
`RESTART2` 形式传递 `"recovery"`。kernel reboot-mode driver 写入平台
boot reason；U-Boot 读取并清除该 one-shot 状态后，本次把 sysboot 目标从
`extlinux.conf` 改为 `recovery.conf`。extlinux 只描述"怎么启动"，不负责
判断"这次进哪里"。如需断电保持的兜底路径，可显式使用
`flange_boot_once=recovery`。

## 关闭 recovery（特殊场景）

如某个板子存储紧张需要关闭 recovery，在 board 配置中覆盖：

```python
# components/board/<your-board>/config.py
BOARD = {
    ...
    "recovery": {"enabled": False},
}
```

关闭后构建图自动跳过 recovery 阶段，分区表中也不应有 `recovery` 条目（否则
配置校验会因为 `recovery.enabled=True` 时缺分区报错——倒过来不会冲突）。

## 构建

```bash
lunch radxa-zero3w-default-release       # 选择板子（recovery 默认开启）
flange build recovery                    # 仅构建 recovery 镜像
flange build                             # 构建整盘镜像（含 recovery 分区）
flange flash                             # 全量刷写到设备
```

构建产物位置：

```
.build/target/<board>/<product>/<variant>/
  recovery/
    recovery.img            # ext4 文件系统镜像，label=recovery
  flash-config.json         # 含 recovery 分区映射与 protected 标记
```

`/etc/flange/recovery-config.json`（recovery rootfs 内）冻结了构建时的 board /
product / variant、分区表与保护策略，是设备端 `recoveryctl` 与宿主机
`flange recovery` 的唯一事实源。

## 宿主机命令一览

| 命令 | 作用 |
|------|------|
| `flange recovery enter` | 让设备从 normal 进入 recovery |
| `flange recovery list [--json]` | 列出分区清单与挂载状态 |
| `flange recovery flash <part> <img>` | 上传镜像并写入分区 |
| `flange recovery backup <part> <out>` | 备份分区到本机文件（默认 zstd 压缩） |
| `flange recovery shell` | 打开 ADB 交互式 shell |
| `flange recovery reboot [normal\|recovery\|loader]` | 请求目标模式并重启（默认 normal） |

前提：宿主机 PATH 中可执行 `adb`，设备通过 USB 连接并启用了 USB gadget
（`adbd` 服务正常运行）。

## 设备端 `recoveryctl`

`recoveryctl` 在 normal 与 recovery 系统中均会被安装。`flash` / `backup`
子命令在 normal 模式下硬性拒绝（依据 `/proc/cmdline` 中的 `flange.mode`
标记），仅 `mode` / `list` / `recovery` / `loader` / `normal` / `reboot`
可在 normal 模式下使用。

```bash
recoveryctl mode                                   # 输出 normal 或 recovery
recoveryctl list --json                            # 分区清单（合并 recovery-config 与实时状态）
recoveryctl flash <part> <img> --sha256 <hash>     # 校验并写入
recoveryctl backup <part> <out> --compress zstd    # 读取分区并压缩备份
recoveryctl recovery                               # 一次性进入 recovery 并重启
recoveryctl loader                                 # 进入 loader/download 模式
recoveryctl normal                                 # 回 normal 系统
```

## 安全策略

### 分区保护

`recovery-config.json` 的每个分区有 `protected` 标记：

- 所有 `type == "raw"` 的分区（idbloader/uboot/boot0 等）→ True
- 所有出现在 `recovery.protected_partitions` 列表中的分区 → True
- recovery 自身分区 → 始终 True（设备端不允许从 recovery 内重写自己）

### --force 双重确认

要写入受保护分区必须同时满足：

1. **宿主机交互确认**：`flange recovery flash --force <p> <img>` 触发提示，
   必须输入字面量 `YES`（区分大小写）才放行。
2. **设备端二次校验**：`recoveryctl flash --force <p> <img>` 在 protected
   分区上要求同时提供 `--sha256`，避免误写损坏镜像。

### 写入前校验链

- 分区在 `recovery-config.json` 中存在
- 镜像文件存在
- sha256 匹配（如提供）
- 镜像大小不超过分区大小（`blockdev --getsize64`）
- 目标分区当前未挂载（`/proc/self/mountinfo` 检查）

写入流程：`dd if=img of=/dev/disk/by-partlabel/<part> bs=4M conv=fsync` →
`sync` → 若提供 sha256，做读回校验。

## 典型工作流

### 在线升级 rootfs

```bash
# 在宿主机
flange build                     # 编译新 rootfs
flange recovery enter            # 设备从 normal 切换到 recovery（自动重启）
flange recovery list             # 确认分区状态：rootfs 应显示未挂载
flange recovery backup rootfs ~/rootfs-backup-$(date +%F).img.zst
flange recovery flash rootfs .build/target/<board>/<p>/<v>/rootfs/rootfs.img
flange recovery reboot           # 切回 normal 启动
```

### 备份用户数据

```bash
flange recovery enter
flange recovery backup userdata ~/userdata.img.zst
flange recovery reboot
```

### 应急：从损坏的 rootfs 恢复

如果 normal 系统启动失败，可在 U-Boot 控制台手动选择 recovery（按住串口
输入打断 distro_bootcmd，进入 U-Boot prompt 后用 `printenv` 查看 boot
入口；具体方法因板子而异）。进入 recovery 后：

```bash
recoveryctl flash rootfs /tmp/flange-upload/rootfs.img --sha256 <hash>
recoveryctl normal
```

## 排障

### `flange recovery enter` 卡在 "等待 ADB 设备超时"

**症状**：宿主机执行 `flange recovery enter` 后长时间无响应直到超时。

**排查**：

1. 确认宿主机 PATH 中有 `adb` 可执行：

   ```bash
   which adb
   adb version
   ```

   未安装则：`brew install android-platform-tools`（macOS）或
   `apt install adb`（Debian/Ubuntu）。

2. 确认 USB 已连接，且设备在 normal 系统启动并完成开机：

   ```bash
   adb devices
   ```

   应当出现类似 `0123456789ABCDEF  device` 的行。如果是 `unauthorized` 状
   态，在设备端确认 USB 调试授权（normal 系统）。

3. 检查设备端 `adbd` 服务：

   ```bash
   flange recovery shell    # 或直接 adb shell
   systemctl status usbdevice
   ```

4. USB gadget 未启动：常见于内核未加载 `g_ether` / configfs gadget；
   查 `dmesg | grep -i gadget` 与 `/sys/class/udc/` 目录是否非空。

### 无法进入或退出 recovery

**症状**：`flange recovery enter` 后仍回到 normal，或设备一直停在
recovery，无法自动切换。

**排查**：

- 新版流程不依赖持久修改 `DEFAULT`：`recoveryctl recovery` 传递
  `reboot("recovery")`，U-Boot 读取并清除 boot reason 后只在本次选择
  `recovery.conf`；再次普通重启应回到 `extlinux.conf`。
- 若仍反复进入 recovery，先检查 `fw_printenv flange_boot_once` 是否残留为
  `recovery`。这是可选断电保持路径，正常 recovery 进入不依赖它。
- 从串口能进入 U-Boot 时，可手动启动 normal：

  ```
  => sysboot mmc 0:1 any ${scriptaddr} /extlinux/extlinux.conf
  ```

- 如果曾使用旧版流程导致 boot 分区的 `extlinux.conf` 被改成
  `DEFAULT flange-recovery`，用 `flange recovery shell` 手动修复：

  ```bash
  mount -o remount,rw /boot
  cat /boot/extlinux/extlinux.conf
  # 把 DEFAULT 行改成 'DEFAULT flange'
  sync && systemctl reboot
  ```

### `flash` 报 "分区当前已挂载"

**原因**：要写入的分区被挂载了。在 recovery 内通常不会自动挂载 normal
rootfs/userdata；如出现，多半是 systemd-mount 或某个手动挂载脚本。

**处理**：

```bash
flange recovery shell
findmnt /dev/disk/by-partlabel/rootfs   # 找出挂载点
umount /dev/disk/by-partlabel/rootfs
exit
flange recovery flash rootfs ...
```

### `flash` 报 "sha256 不匹配"

宿主机会在上传前算 sha256，设备端再次校验上传后的镜像。任一环节不一致
都会拒绝写入。常见原因：上传中断、重复上传相同文件名但不同内容、镜像
文件被实时修改。重新构建 → 重试 `flange recovery flash` 即可。

### `flash` 报 "受保护"

bootloader / raw / recovery 类分区默认受保护，避免误操作让设备 brick。
确认确需要写入这些分区时，加上 `--force`：

```bash
flange recovery flash recovery <recovery.img> --force
```

宿主机会要求输入 `YES` 确认，设备端会要求同时提供 `--sha256`。

### A733 平台 recovery 行为

首版主要在 RK3566 上完成 recovery 全链路验证。A733 平台的 partition 表与
flash-config 已包含 recovery 分区，整盘 dd 时也会写入；U-Boot 适配已接入
Allwinner RTC reboot flag：

- `recoveryctl recovery` 通过 `reboot("recovery")` 写入
  `SUNXI_BOOT_RECOVERY_FLAG`，A733 U-Boot 读取并清除后本次选择
  `recovery.conf`。
- `recoveryctl loader` 在 Allwinner/sunxi compatible 下会传递
  `reboot("bootloader")`，匹配 Allwinner 既有 loader / fastboot 语义。
- 可选的 `flange_boot_once=recovery` 会在 U-Boot 读取后先清理并保存 env；
  若清理或保存失败，本次不会进入 recovery，避免反复进入。

A733 的 recovery → flash → reboot 端到端通路仍需做实机验证后再作为量产
流程使用。

## 不在范围

下列内容不属于本机制，需要时另行设计：

- **OTA / A/B 分区切换**：recovery 不做后台升级；它是手工维护通道。
- **网络烧录**：首版仅 USB ADB；不支持 Wi-Fi/Ethernet/HTTP UI。
- **recovery 自升级**：在 recovery 内不允许写自身 recovery 分区；如需要
  升级 recovery 镜像，回到 normal 系统从宿主机 `flange flash recovery`。
