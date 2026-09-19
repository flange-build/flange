## 1. 基线与验收依据

- [x] 1.1 把 design 中 13 项竞态知识整理为独立的可勾选验收表，每项含「原实现位置 / 知识内容 / 对应硬件现象 / 迁移目标 / 验证方法」，作为实现与验收的双向依据
- [ ] 1.2 采集迁移前基线：在可实测的板子上记录默认 function 组合、枚举到的 VID/PID/产品名/序列号、`lsusb -v` 描述符输出，作为「行为等价」的判据
- [x] 1.3 清点现有 12 份板级 `usbdevice.conf` 的全部键值差异，产出迁移对照表

## 2. L1 Gadget 核心层

- [x] 2.1 configfs 原语：目录管理、symlink、幂等写（写前先读比较，值相同则跳过 —— 知识 #6）
- [x] 2.2 UDC 探测与就绪等待，避免 deferred probe 竞态下取到空 UDC（知识 #1）
- [x] 2.3 UDC 绑定与回读校验，不以写入调用返回值判定成功（知识 #2）
- [x] 2.4 枚举状态校验，并区分「无主机连接」与真实故障（知识 #3、#5）
- [x] 2.5 枚举恢复：翻转 D+ 上拉强制重新枚举，实现中确保不触碰 configfs 链接与 FunctionFS（知识 #4）
- [x] 2.6 设备描述符管理，idProduct 仅在 UDC 未绑定时写入（知识 #7）
- [x] 2.7 断连恢复：UDC 意外解绑而能力集合未变时只重启 daemon，不清理 configfs 链接（知识 #8）
- [x] 2.8 启动幂等守卫：已绑定且能力集合未变时跳过重配（知识 #13）
- [x] 2.9 并发互斥，串行化 udev 触发与控制接口下发的操作（知识 #11）
- [x] 2.10 gadget 启用/停用/重配的完整流程编排，按能力声明的排序权重创建实例（知识 #12）
- [x] 2.11 层间隔离自查：确认 L1 中不存在任何具体 function 名称的判断分支

## 3. L2 原子能力层

- [x] 3.1 定义统一能力接口：实例名、排序权重、互斥集合、参数模型、prepare/start/stop/status
- [x] 3.2 实现能力注册与互斥检查，启用前拒绝互斥组合并报告冲突能力对
- [x] 3.3 实现基于 systemd unit 的 daemon 管理设施，替代既有自制守护循环（知识 #10 不迁移而是消灭）
- [x] 3.4 adb 能力：FunctionFS 挂载 + adbd unit；就绪判定基于 adbd 实际持有 endpoint 文件描述符，不依赖 inode 存在性
- [x] 3.5 ums 能力：backing file 创建与格式化、lun 管理、停用后按策略本地挂载
- [x] 3.6 uvc 能力：yuyv / mjpeg / h264 描述符与各速度等级 class 链接；保持取流 daemon 的既有缺口不变
- [x] 3.7 uac1 与 uac2 能力：feature unit 使能
- [x] 3.8 网络能力 ncm 与 rndis，二者互斥；rndis 保持走 configfs 标准 function 通用路径
- [x] 3.9 mtp 能力：OS descriptor 设置与清理 + mtp-server unit
- [x] 3.10 hid 能力：protocol / subclass / report 长度 / 二进制 report descriptor
- [x] 3.11 ntb 能力：FunctionFS 挂载
- [x] 3.12 能力清单核对：逐一对照既有 shell 实现支持的 function，确认无遗漏

## 4. Role 抽象层

- [x] 4.1 平台探测：按序检查 mainline `usb_role` 节点与 Rockchip `otg_mode` 节点，探测表结构化便于扩展
- [x] 4.2 角色查询，将各平台原始取值归一化为 host / device / none
- [x] 4.3 角色切换原语：翻译为平台写入值、写入后回读校验、不符时报告期望值与实际值
- [x] 4.4 不支持平台的显式报错路径，列出已尝试的节点路径，确保不出现静默失败
- [x] 4.5 自查：确认切换原语中不含任何 gadget 启停逻辑

## 5. L3 场景层

- [x] 5.1 场景模型与 YAML 定义加载，实现 App 层与板级的按键合并（非整文件覆盖）
- [x] 5.2 场景切换编排 —— 仅能力集合变更的路径：先停用当前集合再启用目标集合
- [x] 5.3 场景切换编排 —— 含 role 变更的路径：切 host 先停 gadget 后写 role，切 device 先写 role 后启 gadget
- [x] 5.4 切换失败时的状态报告：指明失败步骤与当前中间状态，不谎报成功
- [x] 5.5 自锁保护：识别会切断当前控制通道的切换，超时回滚计时器与确认命令
- [x] 5.6 持久化与复位：临时切换只改运行时状态，持久化切换跨重启保持，复位清除两者
- [x] 5.7 开机自动进入场景：持久化场景优先于板级默认场景

## 6. 控制接口

- [x] 6.1 unix socket 服务端与行分隔 JSON 协议，非法输入不致进程崩溃且不影响 USB 当前状态
- [x] 6.2 `SO_PEERCRED` 分级授权：查询开放，变更要求 uid 0 或属于 `usbmode` group
- [x] 6.3 `usb-mode` CLI：列举、查询、临时切换、持久化切换、复位、确认
- [x] 6.4 CLI 的 adb 通道检测与自锁警告

## 7. 打包与配置迁移

- [x] 7.1 服务 systemd unit：`local-fs.target` 与 `sys-kernel-config.mount` 之后启动，`sysinit.target` 与 `usb-gadget.target` 双链路拉起，含失败重启与限流
- [x] 7.2 各带 daemon 能力的 unit（adbd、mtp-server），含重启策略
- [x] 7.3 udev 规则改造：`android_usb` change 与 `udc` add/change 事件改为异步通知常驻服务
- [x] 7.4 `app.yaml` 调整：install 映射、`depends` 加 `python3`（metapackage，非 `python3-minimal`）与 `python3-yaml`、systemd unit 声明
- [x] 7.5 特权 group `usbmode` 由服务启动时幂等创建（`groupadd -r -f`）。**不加入 `components/rootfs/config.jsonnet` 的顶层 `groups`** —— 该字段的第二职是「作为每个 user 的默认入组集合」，加入会使所有普通用户自动获得切换权限、分级授权失效；`maintainer_scripts` 又仅对 `app.type=vendor` 开放，故由服务承担
- [x] 7.6 App 层默认 gadget 配置与通用场景定义（YAML）
- [x] 7.7 板级配置迁移（第一批）：可实测的板子，按 1.3 对照表逐项迁移，以行为等价为准
- [x] 7.8 板级配置迁移（第二批）：无法实测的板子，迁移后明确标注「已迁移未验证」
- [x] 7.9 移除 `scripts/usbdevice`、`conf/usbdevice.conf` 及各板级 `overlay/etc/usbdevice.conf`

## 8. 验证

> 前置约束：任何一块板子的首次验证都必须在有串口可用的条件下进行 —— 本服务处于开机关键路径，失败会导致 adb 通道消失、设备完全失联。

- [ ] 8.1 逐项验证 1.1 的 13 项竞态 checklist，每项独立确认，不以「USB 能用」整体代替
- [ ] 8.2 行为等价验证：对照 1.2 基线，确认 VID/PID/产品名/序列号与 `lsusb -v` 描述符输出与迁移前一致
- [ ] 8.3 adbd 交由 systemd 管理的专项验证：FunctionFS endpoint 文件描述符生命周期与 systemd 重启退避的配合，含反复启停不累积进程；此为本变更唯一的全新运行时行为，单独验收
- [ ] 8.4 场景切换验证：能力集合变更、参数生效、未定义场景被拒、互斥组合被拒
- [ ] 8.5 role 切换验证：支持平台上的 device↔host 切换与编排顺序、切到 host 后无残留 UDC 绑定；不支持平台上确认报错明确
- [ ] 8.6 权限分级验证：普通用户可查询、切换被拒；`usbmode` group 成员可切换
- [ ] 8.7 自锁回滚验证：经 adb 切换到自锁场景，超时后自动回滚且通道恢复；收到确认后场景保持
- [ ] 8.8 并发验证：切换过程中触发 USB 插拔，确认操作被正确串行化且 gadget 状态不错乱
- [ ] 8.9 开机路径验证：冷启动进入默认场景、持久化场景优先、启动失败有明确日志
- [ ] 8.10 逐板验证：对每块可实测的板子跑完 8.1–8.2，记录结果

## 9. 文档

- [ ] 9.1 更新 `components/app/adbd/README.md`：三层架构说明、能力清单与参数、场景定义格式、CLI 用法、socket 协议、持久化的失联风险
- [ ] 9.2 在 `wiki/` 记录板级支持矩阵：各板已验证的能力组合、role 切换支持情况（已验证 / 已迁移未验证 / 不支持）
- [ ] 9.3 在 `wiki/` 记录 13 项竞态知识及其对应的硬件现象，作为独立于代码注释的知识备份
