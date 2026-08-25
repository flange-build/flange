## Context

flange 当前在 Python 中加载 `ROOTFS`、`PLATFORM`、`SOC`、`BOARD` 字典，再依次执行 rootfs → platform → SoC → board 的 `deep_merge` 和条件键解析。该机制已经承载 56 个 lunch target，但配置表达与实际消费者发生了分裂：相同 Kconfig 动作存在三套入口，`defconfig` 同时表达 target、fragment 和 raw option；`dts`/`dtb`、组件内源码与 `repos` 引用也因平台而异；条件解析还会把 `product`/`variant` 注入每个嵌套字典。

配置是可信的仓库内容，但求值发生在宿主侧，必须满足 ProjectSpec 对代码/内容分离、确定性构建、内容哈希和外部下载 SHA256 的要求。迁移期间还必须证明 56 个现有 target 的实际构建输入没有发生非预期变化。

## Goals / Non-Goals

**Goals:**

- 用 Jsonnet 原生组合替代私有 merge DSL，并输出普通 Python `dict` 可消费的 canonical JSON。
- 让同一实际动作在平台、SoC、板和产品层只有一个字段路径、类型和解释器。
- 让不同实际动作使用不同字段，例如 defconfig target、Kconfig symbol 和设备树产物不再混装。
- 在配置求值边界完成 schema、层级、引用和安全校验；builder 不再兼容旧别名。
- 用自动化对照覆盖全部 target，并把配置 import 纳入增量哈希。

**Non-Goals:**

- 不改变组件构建顺序、平台策略类、镜像布局或刷写接口。
- 不提供通用 schema 生成器、Jsonnet 插件系统或第二种配置后端。
- 不在 Jsonnet 中执行文件系统探测、网络访问、编译或产物路径计算。
- 不为旧配置字段建立永久兼容层。

## Decisions

### 1. Jsonnet 是唯一配置源，Python 仍是求值边界

新增 `builder/config/jsonnet.py` 作为唯一适配器，通过固定版本的官方 Python Jsonnet binding 求值；`flange` 不调用用户 PATH 中的 `jsonnet` CLI。适配器返回普通 `dict`，现有 engine、cache 和 builder 不直接接触 Jsonnet 对象。

选择 Python binding 是因为注册表和 validator 已在 Python 中，避免引入额外进程协议和宿主 CLI 安装要求。备选的 go-jsonnet CLI 需要额外分发可执行文件且错误、依赖文件和求值结果还要重新跨进程解析，因此不采用。

### 2. 注册表决定层次顺序，Jsonnet 决定组合语义

文件布局保持现有内容归属，只替换扩展名：

```text
components/rootfs/config.jsonnet
components/platform/<platform>/config.jsonnet
components/platform/<platform>/<soc>/config.jsonnet
components/board/<board>/config.jsonnet
components/config/lib.libsonnet
```

每个文件是当前层的 overlay，不直接 import 父层。注册表先从 board overlay 的身份字段解析 `platform`、`soc`、`products` 和 `variants`，再生成一个只包含以下组合的 Jsonnet snippet：

```jsonnet
rootfs + platform + soc + board + {
  product: std.extVar('product'),
  variant: std.extVar('variant'),
}
```

字段追加使用 Jsonnet 的 `+:`，条件使用 `std.extVar('product')` / `std.extVar('variant')`。这样既复用 Jsonnet 原生语义，又保留注册表自动发现和 platform → SoC → board 的层级审计能力；配置文件不因硬编码父路径而耦合。

### 3. Canonical JSON 不携带操作符

`+:`、`super`、条件和数组过滤只存在于 Jsonnet 源文件。求值后的 JSON 必须只包含最终值，不得出现 `+packages`、`:debug`、删除标记或其他操作字段。

标量数组追加使用原生 `field+: [...]`。减少标量数组使用 `lib.without(super.field, removed)`；对象数组直接用 comprehension 按稳定身份字段过滤。公共库只提供实际重复使用的 `without`，不建立自定义运算符框架。

### 4. Kconfig 使用一个 symbol → value 对象

Kernel 与 Bootloader 采用相同结构：

```json
{
  "defconfig": ["base_defconfig", "vendor.config"],
  "config": {
    "CONFIG_NET": "y",
    "CONFIG_DRIVER": "m",
    "CONFIG_UNUSED": "n",
    "CONFIG_CMDLINE": "\"console=ttyS0\""
  }
}
```

`defconfig` 始终是字符串数组，只允许 make target 或 fragment 名；`config` key 必须是完整 `CONFIG_` symbol，value 是合法 Kconfig 右值 token，`n` 统一渲染为 `# CONFIG_X is not set`。同一个基类 renderer 在全部平台生成最终 override fragment，各平台只保留执行 fragment 的必要差异。

不采用 enable/disable 双数组，因为两者无法自然表达 module、字符串和跨层覆盖；不继续允许 raw line 混入 `defconfig`，因为该字段已经有独立的顺序语义。

### 5. 名称相同但语义不同的维度显式拆分

- 设备树统一为 `kernel.device_tree.{directory,name}`；`.dts` 源文件和 `.dtb` 产物扩展名由 builder 推导。
- 架构统一为 `architecture.{userspace,kernel,bootloader}`；例如 ARM64 SoC 可明确表达 `aarch64` 用户态、Linux Kbuild 的 `arm64` 与 U-Boot Kbuild 的 `arm`，避免同一个 `arch` 名称承载三套枚举。
- overlay 按实际执行阶段区分为构建期设备树合并与 boot 分区运行期 overlay；平台不支持某阶段时 validator 必须拒绝，不能静默忽略。

### 6. 所有源码只走 sources 注册表

顶层 `sources` 保存 source descriptor：

```json
{
  "sources": {
    "linux": {
      "url": "https://example/linux.git",
      "branch": "vendor-6.6",
      "commit": "...",
      "recurse_submodules": false
    }
  },
  "kernel": {
    "source": {"name": "linux", "subpath": "src"}
  }
}
```

独立组件仓库也注册为一个 source；多个组件引用同一个 name 即表达共享仓库。`local_path` 与远端字段互斥，commit 存在时仍是最终 pin。这样 `SourceManager` 只解释一套来源结构，不再维护 direct repo、`from_repo` 和平台翻译分支。

### 7. 外部产物统一 descriptor 并强制校验

所有下载型产物使用 `{url, sha256, filename}`；filename 可省略时由 URL 安全推导，但 sha256 不可省略。Bootloader firmware、toolchain、额外 deb、固件和预构建镜像均复用同一个下载入口。配置中的扁平 `*_url`/`*_sha256` 和无校验下载在迁移后删除。

### 8. 两层校验而不是把 schema 全塞进 Jsonnet

Jsonnet 使用 assertion 提供就近、低成本的组合约束；Python validator 负责最终 JSON 的完整 schema、未知字段、跨字段关系、source 引用、下载 hash 和平台能力校验。validator 还对每次层级合并前后的 diff 做层级所有权检查，例如 SoC 不得固定具体板的显示路由或 rootfs 产品包策略。

不引入 JSON Schema/Pydantic 等新依赖：当前字段规模用显式 Python 校验表即可，等 schema 出现外部消费者时再评估标准化描述。

### 9. 迁移以行为对照为准，不以 JSON 字节相等为准

旧配置先为全部 56 个 target 固化语义快照；新旧字段改名后不能直接做原始 JSON diff，因此对照器规范化并比较以下实际输入：

- Kernel/Bootloader defconfig 顺序及最终 Kconfig symbol 状态；
- source URL、branch、commit、subpath 与 submodule 策略；
- 设备树、overlay、rootfs 软件包、固件、分区和下载产物；
- builder 可见的最终 canonical JSON 中不存在未知或无消费者字段。

迁移完成后删除快照生成的旧加载路径，只保留 Jsonnet 全 target 回归测试。

## Risks / Trade-offs

- [Python Jsonnet binding 在支持的 Python 版本缺少 wheel] → 首个任务先在项目支持的 Python 版本矩阵验证安装；失败时改用随 flange 分发的固定 go-jsonnet binary，不改变配置契约。
- [Jsonnet import 可读取宿主文件] → 自定义 import callback 只允许规范化后位于 `components/` 配置根内的 `.jsonnet`/`.libsonnet`，拒绝绝对路径、越界和其他扩展名。
- [一次迁移 56 个 target 容易遗漏隐式行为] → 按平台分批迁移，每批必须通过全量语义快照和对应平台测试，最后才删除旧加载器。
- [严格未知字段校验暴露现有死参数] → 先逐项确认消费者；删除无效声明或补齐真正缺失的公共消费者，不为通过校验添加 alias。
- [source 统一后 checkout 目录冲突] → source 缓存身份包含 descriptor 内容哈希；不同 URL/revision 不共用可变工作树。
- [Jsonnet 过度承载构建逻辑] → import 白名单和 review 规则禁止 native callback、文件探测及命令执行，所有产物行为仍由 Python builder 实现。

## Migration Plan

1. 固化 56 个 target 的旧语义快照，并建立字段—消费者清单。
2. 引入 Jsonnet binding、受限 evaluator、最小公共库和 canonical validator，不切换默认加载器。
3. 迁移 rootfs 基线及 Qualcomm + Khadas VIM3L 两条代表路径，验证 Kconfig、`dts/dtb`、source 和条件语义收敛。
4. 按 Rockchip、Amlogic、Allwinner、Qualcomm 批次迁移剩余配置；每批更新对应测试与规格引用。
5. 将默认注册表切换为 Jsonnet，跑全量测试和 56 target 对照。
6. 删除 Python 配置模块、旧 merge/condition 实现、旧字段翻译及迁移快照。

若某批验证失败，只回退该批 Jsonnet 文件与加载开关；旧加载器在第 6 步前保持可用。第 6 步完成后，回滚以 Git revert 整个变更为单位，不保留运行时双栈开关。

## Open Questions

- Python binding 的发布包是否覆盖项目最终声明的全部宿主 Python 版本；该问题必须在实施任务 1 中用干净环境验证后关闭。
