## Context

本次 rootfs APT 记录中的实际错误是 sudo 解包时无法创建 `/etc/sudoers.d/README.dpkg-new`。
`/tmp/flange-rootfs-apt-failure.log` 的 4037–4038 行保留该证据。
现有 RootfsBuilder 在持久化 `self._work_dir` 下建立活树，这个目录可能由 macOS 文件共享承载。

对照实验 `/tmp/flange-rootfs-storage-semantics-probe.log` 使用同一个特权容器、UID 0，
确认 CAP_DAC_OVERRIDE 与 CAP_FOWNER 存在：原生 overlayfs 可在 0550 目录创建文件、覆写 0400 文件，
并保留 `chown 1000` 的 UID；当前共享 fuseblk 两次写入均返回 EACCES，chown 返回成功后 stat 仍为 UID 0。
宿主卷是 Case-sensitive APFS，因此内核源码的大小写要求与 rootfs 的权限/所有权要求必须分别处理。

另外，当前输出服务在每个命令开始时重置活动诊断缓冲。APT 异常穿过 ChrootContext 清理时，
后续 rm、ln、umount 可以替换缓冲，导致最终摘要失去失败命令的详细上下文。

## Goals / Non-Goals

**Goals:**

- 所有平台的 rootfs 与 recovery 活树具备包管理、用户配置和成像所需的 Linux 文件系统语义。
- 保留现有工作区、目标锁、持久化镜像/报告路径和经过校验的基础快照契约。
- 主操作异常保留自己的命令上下文，清理命令保留完整日志且不覆盖原异常诊断。
- 成功、失败、取消和部分初始化失败均有明确的挂载与临时目录清理行为。

**Non-Goals:**

- 不放宽 sudo、sudoers 或目标目录的预期权限，不禁用 sudo 安装或校验。
- 不迁移用户源码目录，不引入 named volume（命名卷）配置或受内存上限影响的 tmpfs 工作树。
- 不更改公共命令和系统包集合，不把最小包安装验证当作完整固件或设备验收。

## Decisions

### 1. 活树与持久化产物分离

RootfsBuilder.compile 保留 `self._work_dir` 作为镜像、包清单及平台辅助输出目录；
解包、基础快照恢复、APT、Phase 2 定制、平台钩子和最终成像读取同一个容器原生活树。
活树使用 `/var/tmp/flange-<component>-<random>` 的有作用域临时目录，忽略外部 TMPDIR，
不会重新落回宿主共享的 `.build/work`。各调用使用独立名称，并保持既有目标锁。

原生目录只用于可变 Linux 文件树；最终镜像、manifest 和快照归档作为普通文件保存在工作区，
继续供宿主检查和刷写。没有必要为本轮新增持久卷配置，也不通过更大 tmpfs 掩盖磁盘容量问题。

### 2. 公共编排覆盖 rootfs、recovery 和平台钩子

目录切换在公共 RootfsBuilder 编排完成，所有消费 `rootfs_dir` 的阶段沿用同一路径。
Rockchip UBI 的 ubifs/ubi 输出、Qualcomm 辅助产物及其他持久化输出仍写 `self._work_dir`，
不能在作用域退出后留下指向临时活树的产物路径。

基础缓存仍以归档文件存储在工作区 cache；恢复必须写到原生活树。
存储作用域独立放在 `builder/rootfs_storage.py`，与内核使用的通用文件系统检查保持职责分离。
`rootfs_storage.py` 与 `snapshot.py` 纳入 Phase 1 输入指纹，使旧存储和归档行为生成的快照不会在新配方下被误复用。
既有产物清单和原子发布保持有效，不因临时目录随机名称改变语义缓存身份。

### 3. 清理不得遍历仍挂载的子树

chroot 生命周期先恢复临时文件并卸载本次建立的挂载，再结束活树作用域。
初始化完成前的异常同样需要回滚已建立的挂载；正常 Python 上下文不会自动为失败的 `__enter__` 调用 `__exit__`。
临时目录删除必须确认本次挂载已退出，不能沿 `/dev` 等仍生效的 bind mount（绑定挂载）递归删除。
删除前通过 `/proc/self/mountinfo` 检查本次树中的剩余挂载；若仍有挂载，保留目录并报告清理问题。
已有主操作异常时，将清理问题附加到主异常诊断，不能替换它；只有清理失败时独立抛出失败。
磁盘不足、挂载或清理故障保留真实诊断，不能因此发布成功结果。

### 4. 诊断快照绑定异常实例

输出缓冲继续按当前命令重置，失败时将该命令的错误行和有限尾部绑定到实际异常实例。
实现由 `BuildOutput.command_failed(error)` 保存不可变的 `CommandDiagnostic(command, lines)`，
Docker 与通用进程通道在离开命令边界前调用它。
后续成功清理不修改这份诊断；被业务捕获并恢复的旧异常也不会成为后来配置错误的原因。
不采用永久保留“第一条失败”的全局缓冲，因为第一次命令失败可能是可恢复探测。

如果清理另有失败，各异常保留自己的快照；清理层保留主异常，用 `add_note` 附加次级错误，
终端将其显示为补充信息，完整 traceback 进入日志。
没有主操作失败时，清理自身的失败仍必须可见。

### 5. 归档保留完整 Linux 权限元数据

真实 Docker 对照已确认普通 tar 保存/恢复会丢失 `security.capability`、POSIX ACL 与 user xattr，
而数字所有权和模式位相同不能证明行为等价。显式元数据选项恢复后，与原树和直接生成的 ext4 元数据逐项一致。

`snapshot.py` 统一定义 `TAR_METADATA_OPTIONS`：`--numeric-owner --xattrs --xattrs-include=* --acls`，
用于快照创建、快照恢复和 ubuntu-base 原始归档解包。包括 `security.*` 的完整命名空间不能依赖 tar 的默认提取规则。
快照代码进入 Phase 1 指纹；本轮修复后旧配方快照自然失效，不要求用户手工清空全部缓存。

## Risks / Trade-offs

- [容器原生磁盘空间不足] → 保留真实空间诊断和清理行为，指南区分 Docker 磁盘与宿主产物卷容量。
- [退出前仍有子挂载] → 回滚部分初始化，先卸载再删除临时树，不沿挂载点删除内容。
- [平台产物引用临时路径] → 覆盖 rootfs/recovery、ext4/UBI 和平台钩子，检查 collect 返回的路径均为持久化文件。
- [旧快照包含错误权限/所有者] → 将存储实现纳入 Phase 1 指纹，新的快照恢复和打包验证检查元数据。
- [异常快照粘连到后续无关错误] → 按异常实例保存，只呈现实际传播异常及其明确异常链。

## Migration Plan

公共调用方式不变。新构建自动使用容器原生临时活树，最终产物位置不变。
基础快照由新的配方指纹自然重新构建，不要求用户先清空全部缓存或重新编译内核。
待实现与验证完成后，指南说明 Docker 磁盘容量、日志恢复与完整镜像验收边界。

## Open Questions

没有未决实现接口。原生存储、挂载事务与异常快照接口已按实际代码核对；
最终全量、Khadas 完整目标、镜像与实际基础快照的元数据复验已通过，范围和证据见 validation.md。
