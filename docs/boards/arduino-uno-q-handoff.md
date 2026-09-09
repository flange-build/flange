# UNO Q 本轮交付与验收

本轮交付 default-debug 成套镜像，包含 Wi-Fi 用户态依赖、时间同步、Avahi、LightDM、
zram 压缩算法、Venus 固件、Docker containerd 身份识别及 App CLI 版本约束修复。
U-Boot 优先从 ABL 交付的设备树捕获唯一合法槽位，在 EFI 修正时传给 Linux；
不根据 GPT 优先级或默认 A 猜测。该通道已编译和离线检查，实际启动成功标记仍须烧入后确认。

本次最终包 manifest SHA256：
`d558f55bf37af6619fe6c58c3dda15193f7c2c2f64a92b3779ba95a75317013f`。
已通过本地预检（34 个分区），尚未烧入或执行最终实板验收。

## 1. 烧入

在本仓库选择目标并查看发布内容：

```bash
source envsetup.sh
lunch arduino-uno-q-default-debug
flange flash --list
```

本次需要成套更新启动固件、EFI、rootfs 和 userdata。全量刷写会替换现有 rootfs 和 userdata，
包括用户应用、Arduino 资源、文件及网络连接配置。
先备份自己需要保留的文件。Linux 刷写本身不自动覆盖 MCU sketch。

只连接目标 UNO Q，短接 JCTL 的 EDL 跳线并重新上电，再执行：

```bash
flange flash --yes
```

读取 GPT 后会有一次设备重新枚举，保持跳线直至显示刷写完成。完成后移除跳线并重新上电。
发布包位于 `.build/target/arduino-uno-q/default/debug/image/flash-bundle/`，
刷写记录位于同一目标的 `flash-records/`。不要混用旧发布包中的 boot、rootfs 或 userdata。

## 2. 首次启动与只读报告

首次启动需要载入预装容器，请等待相关服务完成。使用 `adb devices` 取得序列号，在宿主执行：

```bash
python3 tests/hardware/arduino_uno_q/collect_runtime.py \
  --serial <UNO_Q_SERIAL> \
  --output .build/verification/arduino-uno-q/after-flash.json
```

脚本不会刷写、重启或修改网络。重点检查：

- `slot` 为 `_a\0` 或 `_b\0`（十六进制 `5f 61 00` / `5f 62 00`），qbootctl 为 active。
- Router、App CLI、容器加载、无线相关服务正常，App CLI 版本 API 返回 JSON。
- `/home/arduino` 独立挂载、容量扩展正常，内核与 modules/initrd 对应。
- 配置测试 Wi-Fi 后具备地址、默认路由、DNS、HTTPS 和时间同步；断电重启后能恢复。

若槽位仍缺失，保留本次报告及 U-Boot 启动日志；不要手工指定 `qbootctl -m a` 绕过问题。
完整硬件清单见[板卡文档](arduino-uno-q.md#实板验收清单)。

## 3. MCU 与 App Lab

先确认允许替换现有 MCU 程序，再通过 App Lab 或已确认的 Arduino 上传入口部署
`tests/hardware/arduino_uno_q/bridge_validation/bridge_validation.ino`。
固定工具链编译已通过；官方上传脚本可能在 Zephyr 基础固件不匹配时一并更新它，
不能将普通 sketch 上传视为绝对只写 sketch 区。

在运行中的 Arduino Python App 容器里运行 `verify_bridge.py`，例如先将脚本推至设备 `/tmp/`，
再由设备 shell 执行以下命令，将容器名替换为实际 Python App 容器：

```bash
docker exec -i <PYTHON_APP_CONTAINER> python - < /tmp/verify_bridge.py
```

通过条件是三次 Linux → MCU 回显与至少三个连续 MCU → Linux 通知，随后重复重启再测。
脚本需 msgpack 与 `/run/arduino-router.sock`，预装 Arduino Python 容器已具备这些条件。
继续通过 App Lab 创建包含 Python、MCU 与 Brick 的 App，验证运行、停止、日志、数据保留和恢复。

Bluetooth 配对、USB Host、外接显示、实际音频输入输出及所连接的摄像头，按实际配件分别验收。
本轮不会把驱动节点、服务 active 或离线检查替代这些功能结果，也不会提前归档 OpenSpec。
