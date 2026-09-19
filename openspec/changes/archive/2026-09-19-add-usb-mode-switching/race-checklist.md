# 平台竞态知识迁移验收表

本表是 [design.md](./design.md) D2 决策的展开，作为 L1 实现与验收的双向依据。

**状态：13 项全部已迁移并在 Radxa ROCK 5B 实板验证通过**（2026-09-19，验证脚本见本目录同名记录与 field-findings.md）。

**使用方式**：实现某项时勾选「已迁移」，实板验证通过后勾选「已验证」。验收 MUST 逐项确认，不得以「USB 能用」整体代替 —— 本变更采用一次性全量重写，遗漏不会在实现期暴露，只在特定硬件时序下浮现且无法二分定位。

原实现：`components/app/adbd/scripts/usbdevice`（本变更中移除）。行号对应移除前的版本，commit `ab59c1a18` 之前的 `main`。

---

## #1 UDC 就绪等待

- [x] 已迁移　- [x] 已验证
- **原位置**：`usb_wait_udc()` L173，调用于 `usb_prepare()` L676
- **知识**：读取 `/sys/class/udc/` 取 UDC 名之前，先轮询等待该目录非空
- **硬件现象**：controller 走 deferred probe 时，gadget 初始化早于 controller 注册，此时目录为空，取到空 UDC 名后续全部失败
- **迁移目标**：L1 UDC 探测
- **验证方法**：冷启动（非重启）观察日志中 UDC 名非空；在 UDC 尚未就绪时触发一次初始化，确认等待而非取空值

## #2 UDC 绑定回读校验

- [x] 已迁移　- [x] 已验证
- **原位置**：`usb_start()` L744–751
- **知识**：写入 UDC 属性后回读文件内容与目标比对，不符则判定失败退出
- **硬件现象**：写 sysfs UDC 属性时 shell 的退出码不反映 kernel 端写失败，DWC2/DWC3 均如此；不校验会静默运行在未绑定状态
- **迁移目标**：L1 UDC 绑定
- **验证方法**：构造绑定失败场景（如占用 UDC 后再绑），确认返回失败并报出期望值与实际值

## #3 枚举状态校验

- [x] 已迁移　- [x] 已验证
- **原位置**：`usb_wait_state()` L183，调用于 `usb_start()` L771
- **知识**：轮询 `/sys/class/udc/<udc>/state` 直至达到目标状态或超时
- **硬件现象**：UDC 回读成功只能确认 gadget 已 bind，确认不了主机侧枚举完成
- **迁移目标**：L1 枚举校验
- **验证方法**：连接主机后确认状态达到 configured；日志中能看到状态轮询过程

## #4 枚举恢复（soft_connect bounce）

- [x] 已迁移　- [x] 已验证
- **原位置**：`usb_bounce_connection()` L196，调用于 `usb_start()` L770
- **知识**：向 `/sys/class/udc/<udc>/soft_connect` 依次写 `disconnect` / `connect` 翻转 D+ 上拉，强制主机重新枚举。**此过程不触碰 configfs 链接与 FunctionFS**
- **硬件现象**：QCS6490 开机首次 bind 后主机枚举撞 dwc3 ep0 竞态（dmesg `request was not queued to ep0out`），state 卡在非 configured、adb 上不来，原需手动 restart
- **禁止操作**：以 stop+start 代替 bounce。清理 configfs 链接会触发 `functionfs_unbind`，`private_data` 置空后 `ffs_ready` 永久返回 `-EINVAL`，adbd 持有的 endpoint fd 彻底失效
- **迁移目标**：L1 枚举恢复
- **验证方法**：QCS6490 类平台冷启动后 adb 直接可用、无需手动 restart；bounce 前后确认 configfs 链接与 FFS 挂载未变

## #5 无主机连接识别

- [x] 已迁移　- [x] 已验证
- **原位置**：`usb_start()` L773–782
- **知识**：枚举未达 configured 时读取实际状态，为 `not attached` 则判定为「无主机连接」，保持 bind 正常返回；其他状态才判定失败
- **硬件现象**：不区分会导致没插线的设备被判为故障，触发 systemd 无限重启
- **迁移目标**：L1 枚举校验
- **验证方法**：不接 USB 线冷启动，确认服务正常就绪、无重启循环、gadget 保持 bind

## #6 幂等写

- [x] 已迁移　- [x] 已验证
- **原位置**：`usb_write()` L232
- **知识**：写 configfs/sysfs 属性前先读取比对，值相同则跳过写入
- **硬件现象**：无谓的属性写入会触发 gadget soft-disconnect 与重新枚举
- **迁移目标**：L1 configfs 原语
- **验证方法**：重复触发配置流程，确认无多余写入、无重新枚举

## #7 idProduct 写入时机

- [x] 已迁移　- [x] 已验证
- **原位置**：`usb_prepare()` L688–699
- **知识**：仅在 UDC 未绑定时写 `idProduct`
- **硬件现象**：UDC 已绑定时写 idProduct 触发 soft-disconnect 与重新枚举；配合「每次 USB 状态变化都触发 update」的 udev 规则，形成无限重置环
- **迁移目标**：L1 描述符管理
- **验证方法**：gadget 已绑定状态下触发重复 update，确认不写 idProduct、不重新枚举

## #8 断连恢复不拆 ConfigFS

- [x] 已迁移　- [x] 已验证
- **原位置**：`usb_prepare()` L673–686
- **知识**：UDC 意外解绑而能力集合未变时，只停止相关 daemon 并清空启动状态，**不调用完整 stop 流程**
- **硬件现象**：同 #4。完整 stop 会移除 configfs 链接触发 `functionfs_unbind`，永久破坏 FFS
- **迁移目标**：L1 断连恢复
- **验证方法**：拔插 USB 线后 adb 能自动恢复；恢复过程中 configfs 链接保持存在

## #9 能力变化先停后启

- [x] 已迁移　- [x] 已验证
- **原位置**：`usb_prepare()` L668–672
- **知识**：检测到目标能力集合与已启动集合不同时，先执行完整 stop 再走 start
- **硬件现象**：不先 stop 会在已 bind 的 gadget 上追加 function 并向非空 UDC 写入，绑定失败
- **迁移目标**：L3 切换编排
- **验证方法**：运行时切换能力组合，确认先解绑再重配、切换后主机枚举到新组合

## #10 守护循环（不迁移，改由 systemd 承担）

- [x] 已替换　- [x] 已验证
- **原位置**：`usb_start_daemon()` L254、`usb_reap_daemon_loop()` L300、`usb_stop_daemon()` L312
- **知识**：原实现用 per-daemon TAG_FILE 控制保活循环活性，并在每次 spawn 前回收上一轮遗留循环
- **硬件现象**：**ROCK 5B 雪崩**。旧实现 spawn 守卫读「文件内容非空」而循环退出条件读「文件存在」，disconnect recovery 只清空不删除该文件，导致守卫失效而旧循环永不退出；每次 disconnect 净泄漏一个永生循环。实测开机 11 分钟堆积 360+ 循环，多循环并发争抢同一 FunctionFS ep0，USB 每 2 秒断连一次，adbd 被反复 kill，adb 完全不可用
- **迁移目标**：**不迁移**。改为每个带 daemon 的能力对应一个 systemd unit，start/stop 即 `systemctl start/stop`，保活由 unit 的 `Restart=` 声明
- **验证方法**：连续多次启停同一能力，确认进程数始终不超过 1；长时间运行后无循环堆积；这是本变更唯一的全新运行时行为，须单独验收（tasks 8.3）

## #11 并发互斥

- [x] 已迁移　- [x] 已验证
- **原位置**：脚本尾部 L827–828（`flock -x`）、L861（`flock -u`）
- **知识**：整个操作流程持有排他文件锁
- **硬件现象**：udev 在每次 USB 状态变化时异步触发，与手动/程序触发并发进入会导致 configfs 状态错乱
- **迁移目标**：L1 或服务层单例（见 design Open Questions —— 常驻服务下互斥形态可能变化）
- **验证方法**：切换过程中反复插拔 USB，确认操作被串行化、gadget 状态不错乱

## #12 内核要求的 function 排序

- [x] 已迁移　- [x] 已验证
- **原位置**：`usb_funcs_sort()` L614，调用于 `usb_prepare()` L640，顺序为 `rndis uac uvc adb ntb ums mtp acm`
- **知识**：function 实例的创建与链接顺序由内核约束，不能按用户输入顺序
- **硬件现象**：顺序错乱导致描述符排列不符合主机预期
- **迁移目标**：L2 各能力声明自身排序权重；L1 按权重排序，**不得硬编码能力名顺序表**
- **验证方法**：以乱序声明多能力场景，确认实例创建顺序符合上述内核顺序

## #13 启动幂等守卫

- [x] 已迁移　- [x] 已验证
- **原位置**：`usb_start()` L708–714
- **知识**：UDC 已绑定且已启动能力集合与目标一致时，直接返回不做任何操作
- **硬件现象**：udev 在每次 USB 状态变化（CONNECTED / CONFIGURED / DISCONNECTED）都触发 update，不加守卫会在 UDC 已绑定时反复重跑 prepare 并写 configfs 属性，造成 soft-disconnect 与无限重置环
- **迁移目标**：L1 或 L3（状态存放位置见 design Open Questions）
- **验证方法**：连接主机后观察日志，确认后续 udev 事件被守卫短路、无重复配置
