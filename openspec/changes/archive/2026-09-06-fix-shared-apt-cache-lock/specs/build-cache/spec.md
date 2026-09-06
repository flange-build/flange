## ADDED Requirements

### Requirement: APT 互斥 SHALL 跟随真实共享目录

App、rootfs/recovery 及内置模板下载的 APT 访问 SHALL 按实际缓存源目录协调互斥，
MUST NOT 仅使用工作区 ID 决定共享缓存锁。APT 命令参数、bind mount 源与锁身份 SHALL 一致。
共享索引的读取 SHALL 与更新互斥，独立目录 MUST NOT 因无关工作区而被全局串行化。

#### Scenario: 两个外部工作区共用工具缓存
- **WHEN** 两个工作区同时准备 App 的 APT 依赖
- **THEN** 同一共享缓存的 update/install 事务串行完成，不因工作区锁互不相见而抢占 APT 锁

#### Scenario: App 与 rootfs 共用下载缓存
- **WHEN** App 安装依赖，rootfs/recovery 正在使用同一真实下载目录
- **THEN** 双方通过同一资源锁串行访问，即使其容器内路径不同

### Requirement: APT 锁 SHALL 保持稳定身份和固定顺序

所有 APT 目录 SHALL 先规范化、去重并按固定顺序加锁；锁文件 MUST 位于 APT 清理范围外，
MUST NOT 删除或替换 APT 自己的锁。异常、取消及部分加锁失败 SHALL 释放已取得的资源锁。
目标和资源构建锁 SHALL 位于 APT 锁外层，APT 锁 MUST NOT 跨越无关编译操作。

#### Scenario: 清理与失败恢复
- **WHEN** APT clean 清空下载缓存，或 APT 命令失败退出
- **THEN** Flange 锁节点保持不变，后续请求可在前一事务释放后正常进入

#### Scenario: 多资源获取顺序不同
- **WHEN** 两个请求以不同参数顺序描述相同目录集合
- **THEN** 实际加锁顺序相同，避免逆序等待
