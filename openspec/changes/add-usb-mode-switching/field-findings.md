# 实板验证发现

设备：Radxa ROCK 5B，172.17.10.177，Ubuntu 24.04.4，内核 6.1.115-g847bc9cd7ecd。
经 **SSH 带外通道**验证 —— SSH 走网络不走 USB，USB gadget 挂掉不影响连接，
这让「首次验证必须有串口」的约束在本次得以豁免。

首轮验证发现 8 个缺陷，其中 4 个严重。**全部是伪 configfs 测试无法暴露的类型**
（依赖内核真实语义、真实时序或真实 udev 事件），这是实板验证不可替代的直接证据。

## 严重

### F1 configfs 写空值必须是换行符，0 字节写入静默失效

`unbind()` 写 `""` 后回读仍是原 controller 名，**gadget 根本没解绑**。

configfs 的 store 回调按写入长度解析内容，0 字节写入不触发回调。旧 shell
实现用 `echo ""`（输出一个换行符）恰好绕开了它。

影响面远不止解绑：`disable()` 失效 → 场景切换的「先停后启」失效 →
切 host 前的解绑失效 → **正是 design 反复强调要避免的悬空绑定**。
ums 清空 lun 同属此类。

修复：`configfs._payload()` 统一把空字符串转成 `"\n"`。

### F2 停用时删除 function 实例会破坏 FunctionFS

我在 `_disable_locked()` 里加了 `remove_dir(instance_dir)`，**旧 shell 实现
从不删除实例**，只删 configuration 下的链接。

删除 configfs 里的 function 实例会销毁底层对象，而 FunctionFS 挂载点仍在：
adbd 随后能成功打开 ep0，却在写描述符时得到 EINVAL，陷入
`failed to write USB strings: Invalid argument` 重启循环，USB 完全不可用。

这是 race-checklist 知识 #4/#8 那条禁令的另一个面 —— 我在停用路径上违反了它。

修复：停用只解除链接，保留实例供复用。

### F3 切换失败停在中间状态，USB 彻底消失且不恢复

能力集合变化走「先停后启」，启用失败时旧能力已被停掉、UDC 已解绑。
实测切到内核不支持的能力后，adb 直接断了且不会自己回来。

**若当时没有 SSH 这条带外通道，设备就失联了。**

修复：`_recover()` 在失败后尽力恢复原场景，恢复走 `_apply` 而非 `switch`
以避免递归与嵌套保护。

### F4 自锁回滚被 udev 触发的重新评估取消，保护完全失效

`reevaluate` 调 `switch(current, force=True)`，而 `switch` 开头无条件
`_cancel_rollback()`。**一次切换本身必然引起 USB 状态变化并触发 udev**，
于是刚装好的保护计时器被自己引发的事件取消。

实测：提示了「60 秒内未确认将回滚」，**70 秒后回滚从未发生**，设备一直
停在无 adb 的场景。自锁保护是设备失联的最后一道防线，design R1 的缓解
措施在真实环境下根本不成立。

修复：新增 `SceneManager.reevaluate()`，不碰回滚计时器、不改场景、不持久化。

## 一般

### F5 失败步骤上报错误，误导排查方向

`_apply` 抛异常时 `step = self._apply(...)` 这条赋值根本没执行，调用方看到
的永远是初值。实测一个发生在 `启用 gadget` 的失败被报成 `解析场景`。

修复：`_ApplyFailure` 携带已到达的步骤。

### F6 能力不被内核支持时错误信息无指向性

原始错误是 `No such file or directory: .../functions/ncm.gs0`，实际含义是
内核没有编入/加载该 function。

修复：包装为「能力 X 在本平台不可用……内核可能未启用对应的 USB_F_* 配置」。

### F7 NOTIFY_SOCKET 泄漏给子进程

`systemctl` 等子进程继承 `NOTIFY_SOCKET` 后也往里发消息，systemd 因
`NotifyAccess=main` 拒收并刷警告日志。

修复：`_sd_notify` 用 `os.environ.pop` 而非 `get`。

### F8 改了场景定义没有便捷的生效方式

`systemctl reload` 发的 SIGHUP 只触发 gadget 重新评估，不重载场景定义；
而 `config.reload` 这个 RPC 方法存在，CLI 却没暴露对应子命令。

修复：CLI 补 `usb-mode reload`。SIGHUP 保持只做重新评估 —— 那是 udev 的
高频路径，不该每次都重读配置。

## 非缺陷，但影响判据

### bcdUSB 在绑定时被内核提升

用户设置 `0x0200`，绑定后读到 `0x0210`：Linux composite 框架在 controller
支持 LPM 时会提到 USB 2.1（BOS descriptor 需要），解绑后恢复。

实验确认：`绑定=0x0210 → 解绑=0x0200 → 重新绑定=0x0210`。

等价性判据须排除该项，或注明它随绑定状态变化。基线采集时读到 `0x0200`
说明当时 gadget 实际未真正 bind（UDC 文件 stale 会骗人）。

### dpkg overwrite 冲突（拆包的已知限制）

文件归属从 adbd 迁到 usbmoded 后，已装旧版的设备增量升级会报
`trying to overwrite ... which is also in package adbd`。flange 的 app.yaml
不支持 `Replaces`/`Breaks`。rootfs 全新构建不受影响。

## 平台事实（写入支持矩阵）

- **ROCK 5B 的 role 切换被内核藏起来了，不是硬件不支持**（初判有误，已修正）：

  DT 实际是 `dr_mode = "otg"` 且声明了 `usb-role-switch`，fusb302 Type-C
  控制器正常工作，`/sys/class/usb_role/fc000000.usb-role-switch` 节点也确实
  存在 —— 但该目录下**没有 `role` 属性文件**。

  根因在内核：`role` 属性受 `usb_role_switch_is_visible()` 控制，仅当注册方
  设置了 `allow_userspace_control` 才可见。mainline 的 dwc3 自 v5.9 起设置了
  它，而 Rockchip BSP 6.1 的 `drivers/usb/dwc3/drd.c` 注册时没带这个字段：

  ```c
  struct usb_role_switch_desc dwc3_role_switch = {NULL};
  dwc3_role_switch.fwnode = dev_fwnode(dwc->dev);
  dwc->role_sw = usb_role_switch_register(dwc->dev, &dwc3_role_switch);
  ```

  **补一行 `dwc3_role_switch.allow_userspace_control = true;` 即可开启。**

  探测逻辑已据此改进：区分「usb_role 下有设备但无 role 属性」（内核未暴露，
  可 patch）与「完全没有节点」（多半 dr_mode 被固定），两者解法完全不同，
  混为一谈会让排查者误以为硬件不支持而放弃。
- **内核支持的 function 类型**（实测逐个 mkdir 探测）：
  `ffs`、`mass_storage`、`acm`、`uvc` 可用；
  `mtp`、`ncm`、`rndis`、`hid`、`uac1`、`uac2`、`eem`、`ecm` 不可用。
  因此 `media`（含 mtp）与 `net`（含 ncm）两个通用场景在本板不可用。
- 系统缺 `mkfs.vfat`（无 dosfstools），`storage` 场景的默认 vfat 参数在本板
  不可用，需改 ext4 或补装 dosfstools。

### F9 卸载后 __pycache__ 残留，包已 purge 仍可 import

`dpkg --purge usbmoded` 后 `/usr/lib/python3/dist-packages/usbmoded/` 仍在，
里面是 16 个 `.pyc`。目录存在使 Python 3 把它当作命名空间包（PEP 420），
`import usbmoded` 依然成功（`__file__` 为 None）。

标准 Debian Python 包由 `dh_python3` 在 postrm 清理 `__pycache__`，flange 的
deb 生成器没有这一步；而 `maintainer_scripts` 只对 `app.type=vendor` 开放，
App 层无法自行补 postrm。

功能影响有限（Python 不会用没有对应 `.py` 的 `.pyc`），但卸载不干净，且会让
「包是否可用」的探测失效。修复需要改 `builder/deb.py`：为含 Python 文件的包
自动生成清理 `__pycache__` 的 postrm。**超出本变更范围，单独记录。**

### 升级流程（实测可行）

拆包后在已装旧版的设备上：

```
dpkg --purge adbd usbmoded     # 或 dpkg -r adbd，保留 conffiles
rm -rf /usr/lib/python3/dist-packages/usbmoded   # 清 __pycache__ 残留（见 F9）
dpkg -i usbmoded_*.deb adbd_*.deb                # 一次装两个，依赖在批内解决
```

板级配置 `/etc/usbmode/gadget.d/20-<board>.yaml` 来自 rootfs overlay、不属于
任何包，purge 不会删它 —— 这是正确行为，全新安装后仍然生效（实测确认）。
