# rootfs-build-storage Specification

## Purpose

定义 rootfs/recovery 可变文件树的 Linux 原生存储、持久化产物与快照边界、权限元数据保留，
以及 chroot 挂载和临时目录的安全生命周期，使首次构建与基础快照恢复保持目标文件系统语义一致。

## Requirements

### Requirement: rootfs 活树 SHALL 使用 Linux 原生构建存储

rootfs 与 recovery 的解包、APT 安装、系统定制及成像读取的可变文件树 MUST 位于具备 Linux 权限、
所有权和链接语义的容器原生存储。构建 MUST NOT 仅根据宿主目录大小写敏感或容器拥有 root 身份，
推断宿主共享目录满足这些条件；MUST NOT 通过修改目标包预期权限绕开存储差异。

#### Scenario: macOS 共享构建目录

- **WHEN** 工作区与持久化产物根由 macOS 文件共享挂载到容器
- **THEN** rootfs 与 recovery 活树建立在容器 `/var/tmp` 的独立临时目录，APT 不在宿主共享活树中解包
- **AND** 不受指向共享路径的 TMPDIR 影响

#### Scenario: sudo 与目标所有权

- **WHEN** 包管理器安装 sudo 并设置普通用户所有的目录或文件
- **THEN** 活树保留目标要求的权限与 UID/GID，Linux root 能完成具备能力时的目录写入
- **AND** 不通过放宽 sudoers 权限或删除 sudo 包完成构建

### Requirement: 临时活树 SHALL 保持持久化产物与缓存契约

镜像、包清单与平台辅助产物 MUST 继续保存在工作区的组件输出目录，collect 返回结果 MUST NOT 指向即将删除的临时活树。
基础快照 SHALL 以归档文件持久化，并在容器原生活树中恢复；存储实现 SHALL 纳入 Phase 1 指纹，
临时目录随机名称 MUST NOT 成为语义缓存输入。

#### Scenario: ext4 与 UBI 产物

- **WHEN** 任意支持平台的 rootfs 或 recovery 完成 ext4/UBI 成像
- **THEN** 成像过程使用原生活树，最终镜像和清单在作用域结束后仍可通过工作区产物路径读取与验证

#### Scenario: 基础快照迁移

- **WHEN** 存储配方从宿主共享活树迁移为容器原生活树
- **THEN** 新 Phase 1 指纹不会误用旧配方的快照，新快照恢复时保留原生文件系统元数据

### Requirement: 活树生命周期 SHALL 安全清理临时资源

每次构建 SHALL 使用独立活树并遵守既有目标锁。成功、失败、取消和部分初始化失败 MUST 清理本次资源；
删除临时目录前 MUST 退出其中的 chroot 子挂载，MUST NOT 递归遍历仍生效的绑定挂载。
清理失败 MUST 保留诊断且不得发布新成功状态。

#### Scenario: 初始化中途失败

- **WHEN** chroot 已建立部分挂载但后续初始化失败
- **THEN** 已建立的挂载被回滚，临时树清理不遍历仍挂载的 `/dev` 等子树

#### Scenario: 构建失败或取消

- **WHEN** APT、定制或成像失败，或者用户取消
- **THEN** 本次挂载与临时树按安全顺序收尾，已存在的有效最终产物不被伪造为本次成功

#### Scenario: 相邻目标构建

- **WHEN** 同一容器执行相邻或不同目标的 rootfs/recovery 构建
- **THEN** 各次活树路径独立，不共享可变 Linux 文件树

### Requirement: 根文件系统归档 SHALL 保留 Linux 权限元数据

原始 ubuntu-base 解包与基础快照保存/恢复 MUST 保留归档提供的数字 UID/GID、模式位、符号链接、硬链接、
扩展属性、文件 capability 与 POSIX ACL。归档层 MUST 显式处理包括 `security.*` 在内的属性命名空间，
不能只根据普通文件内容与模式位判断首次构建和快照恢复等价。快照实现 SHALL 纳入 Phase 1 配方指纹。

#### Scenario: capability 与 ACL 经过快照恢复

- **WHEN** 原生活树包含 `security.capability`、POSIX ACL、user xattr 和非 root 所有者的文件
- **THEN** 保存并恢复基础快照后上述元数据与原树一致，文件的硬链接和符号链接关系仍正确

#### Scenario: ubuntu-base 提供扩展权限

- **WHEN** ubuntu-base 原始归档带有扩展属性或 ACL
- **THEN** 解包使用与快照恢复一致的元数据选项，不能在首次输入边界静默丢失

#### Scenario: 归档语义更新使旧快照失效

- **WHEN** 快照配方增加扩展权限保留行为
- **THEN** Phase 1 输入身份改变，旧配方快照不再误命中
