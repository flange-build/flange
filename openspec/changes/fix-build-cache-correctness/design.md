## Context

现有缓存判定在源码同步前执行，却把同步后的 git HEAD 作为哈希输入。为规避未知 HEAD，代码又把所有未固定 commit/tag 的 branch 强制判为未命中；仓库内 vendor 包因通过 `external_apps.local_path` 注册，也被误当成开发者目录。另一方面，缓存哈希在判定时被记忆化，构建完成后直接复用旧值写入，且若干实际构建输入和动态产物未进入缓存契约。

修复必须保留 `local_path` 下层构建系统增量语义、Docker 构建模型和现有命令接口，并避免引入第三方依赖。

## Goals / Non-Goals

**Goals:**

- 无源码和配置变化时，跟踪 branch 的组件及仓库内 vendor App 可稳定命中。
- 任一实际构建输入变化都使对应组件及 Merkle 下游失效。
- 缓存只在已声明产物完整存在后写入，并记录构建完成时的输入身份。
- rootfs 下载可原子恢复且按配置 SHA256 校验，Phase 1 输入覆盖实际软件源配置。

**Non-Goals:**

- 不实现远程缓存、并行构建锁或 apt 仓库快照服务。
- 不改变外部 `local_path` 每次进入底层增量构建的行为。
- 不保证未固定的远端 apt 仓库在不同时间可字节级复现；需要该能力时应另行引入 snapshot/lockfile。

## Decisions

### 1. 缓存判定前统一准备源码输入

`BuildEngine` 在每个组件判定前调用 `SourceManager` 的缓存输入准备入口，同步该组件声明的直接仓库、OOT 仓库、firmware 仓库和 App git 来源。随后 `BuildCache` 读取本地 HEAD，不再把 branch 本身视为强制未命中条件。同一组件准备阶段与实际构建阶段复用已完成的 ensure，避免重复 fetch；切换到下一个组件时清空该短期状态，保持共享仓库原有 reset 语义。

备选方案是在 `BuildCache` 内执行网络访问，但这会破坏缓存类的只读职责，也使单纯哈希查询产生外部副作用，因此不采用。

### 2. 仅仓库外 local_path 强制失效

路径解析后位于项目 `components/` 内的 App 来源属于受版本控制的构建输入，递归按内容哈希；项目外 `local_path` 和 `external_app_dirs` 继续强制当前组件及下游进入构建。共享库 `.so` 是合法发布载荷，不再作为派生文件排除。

### 3. 缓存写入使用构建后新哈希

`store()` 在计算前清空本次记忆化哈希，并使用临时文件加原子替换写入 `.build_hash`。引擎收集产物后必须校验声明的动态必需产物；缺失时构建失败且不得写缓存。

### 4. 用显式组件输入契约补齐哈希

保留现有组件特化函数，补齐它们实际消费的顶层配置：kernel 的 BSP/device 与 OOT 输入、bootloader 的 rkbin、boot 的 recovery 开关、rootfs 的完整子树与 storage、image 的 storage/rkbin 等。构建逻辑统一加入一次性计算的 `builder/` 与 Docker 定义指纹，避免构建脚本变化复用旧产物。

备选方案是所有组件哈希完整 FINAL_CONFIG；它实现更短，但会让 hostname 等 rootfs 变化无故重编 kernel，违背降低增量成本的目标，因此不采用。

### 5. rootfs 外部基线按可信摘要缓存

stock 配置为 ubuntu-base 声明 `rootfs.sha256`。下载先写 `.download`，校验成功后原子替换；URL、SHA256、packages、extra APT sources、arch 与 emulator 共同决定 Phase 1 hash。已存在但摘要不符的 tarball 必须重新下载。

## Risks / Trade-offs

- [branch 每次判定需要 fetch，离线时无法确认远端是否变化] → 保留明确失败，不把未知远端状态伪装成缓存命中；固定 commit/tag 可避免网络请求。
- [全局构建逻辑指纹可能使无关 builder 修改触发额外重建] → 该事件频率远低于普通源码迭代，先以正确性优先；有数据证明成本显著后再拆分到组件级脚本映射。
- [首次升级后旧哈希全部失效] → 这是一次性迁移，完成一次构建后进入新契约。

## Migration Plan

1. 更新 stock rootfs 配置的 SHA256，并先落测试。
2. 修改源码准备、哈希和产物门禁；旧 `.build_hash` 因输入契约变化自然失效。
3. 对当前 Q8B target 连续执行缓存判定，确认第二次无变化命中。
4. 回滚时恢复代码即可；旧产物仍可重建，不需要转换缓存文件。

## Open Questions

无。
