# 设计说明

## 决策 1：per-App 缓存放在 AppBuilder 内，不动依赖图

**选项**：(a) 把每个 App 提升为依赖图节点；(b) 在 `app` 组件内部做二级缓存。

**选择 (b)**。理由：依赖图同时被 `engine` 的拓扑排序、`cache` 的 Merkle 级联、`REQUIRED_ARTIFACTS` 与产物收集三处消费，把动态数量的 App 塞进静态图需要同时改这三处的语义（产物目录、跳过逻辑、force 传播），而收益与 (b) 相同——engine 级失效只表示"App 集合里有东西变了"，具体重建哪些由 `build_all` 逐个判定，组件级失效本身是廉价的。

组件级 `compute_hash("app")` 改为混入各 App 的 per-App 哈希，因此既保持了 `build-cache` spec 中"App hash 覆盖全部 custom package 源码"的既有契约，也让 rootfs 的 Merkle 边不变。

**代价**：`app` 组件失效时仍会调用 `build_all`（即使全部命中），这是几秒的对账开销，换来不动三处消费方。

## 决策 2：per-App 哈希刻意不含全局输入

per-App 哈希只混：目标架构、App 打包逻辑（`builder/app.py`、`app_spec.py`、`deb.py`、`docker.py`、`config/apps.py` 与 Docker 定义）、来源描述符、源目录内容、包级附加输入、上游 App 哈希。

**不含** `jsonnet_hash` 与整棵 `builder/` 的逻辑指纹——否则任一配置或任一 builder 文件改动仍会重编全部 App，per-App 粒度就形同虚设。

风险是"配置变化改变了某个 App 的构建结果但 per-App 哈希不变"。逐一核对 `builder/app.py` 中所有从 config 读值的位置后确认：`board/product/variant` 只决定输出与 sysroot 路径，不进 deb 内容；`custom_packages`/`recovery` 只决定集合成员，由组件级哈希覆盖；`external_app_dirs` 若改变解析目标，目录内容哈希随之改变。`build.options`、`apt_packages` 都来自 `app.yaml`，已在目录内容内。

## 决策 3：来源描述符中的 local_path 归一化为项目相对路径

`external_apps[<name>].local_path` 在 canonical 配置里是绝对路径，宿主机看到 `/Volumes/bsp/flange/...`、容器看到 `/workspace/...`。直接哈希会让同一份源码在两侧算出不同值。per-App 哈希把它归一化为相对项目根的路径；项目根之外的本地源保持原样（该模式本就强制重建）。

## 决策 4：配置切片用排除式而非白名单

**选项**：(a) 白名单——只混该组件消费的键；(b) 排除式——混完整配置减去该组件明确不消费的键。

**选择 (b)**。两者的失败方向相反：白名单漏登记 ⇒ under-invalidation（该重建没重建，产出错误镜像）；排除式漏登记 ⇒ over-invalidation（多编一次）。构建系统最坏的失败模式是静默产出错误镜像，因此选择失败方向安全的一侧。

剔除表按各 builder 模块实际读取的 config 顶层键取证得出，并保留两处已核实的跨子树消费：kernel 经 `builder/dtb_overlay.py` 读 `boot.overlays.intree`；rockchip bootloader 读 `amp.enabled` 校验 U-Boot 选项。

**Merkle 约束**：依赖上游的组件其实际敏感面是「自身切片 ∪ 上游切片」，所以剔除表不能比上游更激进——`device-tree-overlay` 依赖 kernel，写了 kernel 未剔除的键也会被级联带回来，只会误导读者。测试矩阵对每个组件的敏感/不敏感键双向断言，防止后续改动踩空。

这同时替代了旧的 `jsonnet_hash`：后者混入 Jsonnet 源文件的**原始字节**，连"只加一行注释"都会让全部组件失效。切片以求值结果为准，语义不变的编辑不再触发重建。`jsonnet_hash` 保留在 `ResolvedConfig` 上供诊断。

## 决策 5：构建逻辑指纹用"默认包含 + 显式排除"

排除表只列有证据表明不参与任何组件构建的模块（刷写执行、在线维护、部署、脚手架及模板、清单查询）与非当前平台目录，其余文件（含未来新增的顶层模块）默认仍进指纹。与决策 4 同理：漏登记只退化为过度失效。

排除 `flash.py` 暴露出一个既有的分层错误：它同时是宿主机刷写执行器与构建期分区表渲染器，而 `image.py` 反向延迟导入其 `generate_parameter_txt` 生成进入 image 缓存的产物。整份排除会让"改分区表渲染不重建 image"成为缓存洞。因此把该纯函数移入 `builder/partition/rockchip.py`（它本就属于分区表逻辑），`flash.py` 保留 re-export 兼容既有导入。

## 决策 6：包内编译链拆成单元 App，而不是自建 stamp 引擎

**选项**：(A) 把 7 个子工程拆成独立 App，用 `build.deps` 串联，靠框架的 per-App 缓存；(B) 保持单 App，脚本内自建子单元 stamp。

**选择 (A)**。(B) 曾作为过渡实现落地过（约 300 行 stamp 引擎：源身份指纹、命令行指纹、上游级联、原子 stamp 读写），它能工作，但它是**框架已有能力的第四次重复实现** —— 同一个"按内容哈希判断要不要重做"的需求，仓库里已经有组件级 `.build_hash`、App 级产物清单、Phase 1 快照三套。再加一套，意味着 `flange clean` 管不到它、`flange why` 解释不了它、它的正确性也没有框架的测试覆盖。拆成 App 后这 300 行整体删除。

拆分需要两个框架契约，两者都是**通用能力**而非为这个包开的后门：

1. **`app.type: staging`** —— 只产出供下游消费的交叉编译产物树，不打 deb、不进 rootfs。链上的中间环节（GStreamer core/base 之于 Rockchip 插件）本来就不交付任何包，此前只能被迫打一个空包或塞进别的单元。
2. **`build.staging`** —— 声明该产物树的位置，使它进入该 App 的产物清单与门禁。没有它，上游命中缓存而 staging 被删时，下游会在 configure 阶段以"找不到头文件"这种难查的方式失败。

单元间的 sysroot 传递：下游在编译前从各上游的 staging 树**重新合成**自己的 sysroot。每次重新合成，因此上游命中缓存被整体跳过也不影响，且不会残留上一轮的头文件。

**模板重打是第 8 个单元**：Noble 的分包边界与编译单元边界不重合 —— 已验证 `gstreamer1.0-plugins-good` 的两个 deb 里含有来自 `gst-plugins-bad` staging 的文件。所以重打必须等四个 GStreamer 单元全部就绪后一次性完成，不能挂在任何一个编译单元的尾巴上。

**两组平行声明**：`app.yaml` 的 `build.deps`（框架用于排序与 Merkle 级联）与 `lib/toolkit.py` 的 `Unit.deps`（脚本用于合成 sysroot）描述同一张图。这是拆分引入的唯一冗余，用一条对账测试钉住 —— deps 少一条会链出 ABI 不一致的插件，是必须机器强制的那类一致性。

## 决策 7：哈希分段化是可解释性的前提

`compute_hash` 原先把所有输入流式 `update` 进一个 hasher，中间结构被丢弃，"为什么重建"在数据结构层面就无法回答。改为先算出具名分段字典，再对字典求哈希：`dep:<组件>` / `identity` / `config` / `logic` / `own`。分段名本身就是重建理由。

分段随 `.build_hash` 一同存档到 `.build_hash.json`，`explain()` 对比存档与当前分段即可指出差异。这个改动不增加任何计算量（分段本来就要算），只是不再丢弃中间结果。

## 决策 8：稀疏拷贝用 `--sparse=auto`，不是 `always`

`mke2fs -d` 造出的 rootfs.img 与 image 的 raw.img 都高度稀疏（实测 4GiB 声明只占 2.2MiB），而 `shutil.copy2` 不做空洞检测，把整个声明尺寸实写成零 —— 这正是既有产物 `rootfs.img` 8.00GiB 声明、8.00GiB 实占的原因。

在真实的 Docker Desktop bind mount 上逐一实测四种方式：

| 方式 | 结果 |
|------|------|
| `cp --sparse=auto`（GNU cp 默认） | 0.1% 实占 ✓ |
| `cp`（无参数） | 0.1% 实占 ✓ |
| `dd conv=sparse` | 0.1% 实占 ✓ |
| `dd conv=notrunc,sparse` | 0.1% 实占 ✓ |
| `cp --sparse=always` | **失败**：`error deallocating ... Invalid argument` |

`--sparse=always` 在写完后还要 punch hole，virtiofs 不支持该操作。它会失败（回退到 copy2 后结果仍正确，但拿不到任何收益）。因此用默认的 `auto`：读到全零块时 seek 而不写，不需要 punch hole。

## 决策 9：快照回收用 LRU 而非 FIFO

保留"最近使用的 N 份"而非"最近创建的 N 份"：命中时刷新快照 mtime。否则常用的稳定基线会被一串一次性试验挤掉。本次正在使用的那一份永不回收——命中最老快照的构建不能把自己脚下的文件删掉。

回收是尽力而为：删除失败（并发构建已删、权限不符）只跳过，不影响构建。

## 未纳入本次变更的评审结论

架构评审识别出的以下方向改动面大、需独立立项，本次不做：

- **构建单元一等抽象**：把 App、OOT driver、dtbo、包内子工程统一为图上的节点，取代 9 节点静态组件图。
- **rootfs 构造序列数据化**：4 个平台 + recovery 共 5 份手抄的 Phase 2 序列（约 576 行冗余且已漂移），应收敛为声明式 Recipe + 单一执行器，把顺序约束从注释变成可校验的数据。
- **分区表单一事实源**：`parameter.txt` ×2、`flash-config.json`、`recovery-config.json`、`mtd-bundle.json` 共 4 处独立渲染，已出现 spinand idbloader 与 protected 规则的实际漂移。
- **`flash.py` 按构建期/执行期拆包**：本次只搬走了造成缓存洞的那一个纯函数。
- **产物直写 target 与镜像尺寸治理**：产物先在容器 `/tmp` 生成再整份拷入 target，多一次全量写；`grow_on_first_boot` 的 rootfs 其 `image_size` 是手工旋钮而非派生量。
- **Step 级计时与日志轮转**：`build.log` 无时间戳且每次截断，Phase 2 内部热点目前无法从产物中拆解。
