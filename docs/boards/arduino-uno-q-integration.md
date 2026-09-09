# UNO Q 适配对 flange 的改动清单

基线为提交 `8e61004f6`，适配由 `d325e8447`、`3cd0c3516`、`e29b0606c` 引入。
另列本次 Docker/APFS 稀疏复制修复。原适配修改了 12 个既有 builder 文件和 1 个 Dockerfile，
新增 6 个 QRB2210 构建策略文件及 1 个 UNO Q 刷写模块。

## 既有公共代码的改动

| 文件 | 改动 | 影响范围 |
| --- | --- | --- |
| `builder/platforms/spec.py` | 新增 `EXTRA_DEPENDENCIES` 解析、依赖图合并及检查；新增 `required_artifacts` 可选钩子 | 公共平台契约。未声明的平台沿用原行为；检查未知组件、循环、重复产物和路径越界 |
| `builder/component_plan.py` | 计划消费平台附加依赖和必需产物；平台自定义 image 输出仍必须附带 flash-config | 改变计划及缓存输入/输出契约，UNO Q 声明 `boot → rootfs` |
| `builder/engine.py` | 计划与执行使用同一扩展依赖图；目录产物发布也使用稀疏复制；无 GNU cp 时按零块回退 | 调度和发布公共路径，适用于所有平台的目录产物 |
| `builder/config/schema.py`、`builder/config/validate.py` | 增加 `bootloader.device_tree`、`bootloader.recovery_firmware`，后者要求下载摘要 | 公共配置字段扩展，其他平台不必配置 |
| `builder/app_build.py` | 将 `/usr/lib/firmware/` 纳入非 Linux 用户态 ELF 的例外目录 | 所有 App/vendor 包的架构校验；普通动态库及程序仍校验目标架构 |
| `builder/deb.py` | control/data tar 改为 GNU 格式，避免 dpkg 拒绝长路径触发的 PAX 头 | 所有自有 DEB 的打包格式；独立修复提交 |
| `builder/flash/model.py` | FlashConfig 增加 bundle 清单路径及摘要，DeviceInfo 增加 serial | 公共数据模型和 JSON 输出，新增字段带默认值；外部严格 JSON 消费者需要留意字段增加 |
| `builder/flash/plan.py`、`builder/flash/generate.py` | 增加平台自定义 flash-config 生成钩子，注册 UnoQFlashPlan | 可从真实发布包生成分区计划，其他平台继续使用公共 PartitionLayout |
| `builder/flash/strategy.py`、`builder/flash/execute.py` | 增加具名分区和不支持禁止重启的能力标志；传递 `--yes`；注册 UNO Q 策略 | 公共执行器增加分支；默认标志保持既有行为。UNO Q 的固件保护在其策略内实现 |
| `docker/Dockerfile` | 安装 mkbootimg 包并检查 unpack_bootimg 存在 | 所有新构建的标准镜像增加工具依赖；旧镜像需执行 `flange docker build` 更新 |

最需要关注的是依赖图、产物契约与目录发布三个公共路径，以及所有 DEB 的 tar 格式变化。
共享 `KernelBuilder`、`RootfsBuilder` 基类、原有平台目录、基础 `DEPENDENCY_GRAPH` 没有直接修改。
刷写注册仍在公共 `plan.py/strategy.py` 中出现 UNO Q 名称，尚不是完全依靠平台自注册的架构。

APT 的另外一份提交只修改测试：把 multiprocessing worker 移到轻量模块，并用单调时间戳检查事务顺序。
没有修改生产 APT 锁或安装流程。此前尝试的自动安装 unpack_bootimg 逻辑已撤销，不属于当前代码。

## 新增且可供其他平台复用的能力

1. **平台附加组件依赖**：平台可以声明额外依赖，计划、执行与缓存共同消费。
2. **平台自定义必需产物**：支持一个组件输出多个文件或目录，并在缺失时拒绝缓存命中。
3. **基于发布包的刷写计划**：平台可以从外部 XML/GPT 等真实布局生成 flash-config，绑定清单摘要。
4. **发布目录内的稀疏镜像保留**：目录复制不再把大镜像的零区全部展开。
5. **更完整的 vendor 包兼容**：DEB 长路径/长链接，以及固件目录中异构处理器 ELF 的正确分类。
6. **刷写策略能力声明**：具名分区写入及工具自动重启约束可由其他策略使用。

Docker 构建、增量构建、Product/Variant、多平台、App/vendor 包和设备树覆盖原本已经存在；
本次是在这些机制上扩展和适配。

## UNO Q 平台本身新增的实现

| 能力 | 实现范围 |
| --- | --- |
| QRB2210 Linux | 固定上游 kernel、配置片段、最终合成 DTB、Image 和 modules；2 GB/4 GB 共用板级配置 |
| 双层启动镜像 | `boot_a/boot_b` 使用 Android v0 包装的 U-Boot；`efi` 使用包含 Image/DTB/initrd 的 systemd-boot FAT 分区 |
| 真实 QDL/eMMC 发布包 | 保留官方固件/XML/GPT，生成清单及摘要，支持全量和物理具名分区刷写 |
| 容量与持久化保护 | 按真实设备 GPT 校验布局，处理 16/32 GB 布局，保留校准区域；组件单刷不重写 GPT/userdata |
| Ubuntu 板级运行时 | 匹配 firmware、BDF revision 选择、rmtfs/tqftpserv、音频 UCM、启动槽位成功标记 |
| 独立 userdata | UID/GID 1000、固定 UUID、首次挂载后扩展 ext4，校验 rootfs 与 userdata 的资源身份 |
| Linux 与 MCU 协作 | 固定 Zephyr core、Arduino CLI、OpenOCD/remoteocd、Router/Bridge；显式 MCU 初始化和 sketch 保留策略 |
| USB 设备端 | Arduino 补丁版 adbd、ADB/ACM gadget 服务、身份及唯一 UDC 检查、幂等清理 |
| App Lab 与 Bricks | Ubuntu ABI 验证、五种 ARM64 容器归档、十个 EI 模型；两个可选 GGUF 按固定 commit 下载 |

这些是 UNO Q 策略和功能包的实现，不代表通用 Qualcomm QDL、任意 MCU、任意 Arduino 板或载板已经受支持。
固件主要是固定来源校验和打包，不是新增了 Qualcomm 固件源码编译体系。

## 本次 image 失败的修复范围

仅修改 `builder/flash/unoq.py` 的镜像复制和对应测试：用分块读写、seek/truncate 保留空洞，
避免 GNU cp 在 Docker/APFS 上执行不被支持的空洞回收；保留真实 I/O 错误。
没有为此修改公共构建器、安装工具或恢复之前撤销的自动 APT 逻辑。

## 验证边界

已有标准 Docker 成套构建、镜像组装和相关回归证据；首次 EDL 写入与 debug 启动已由用户完成。
热修复系统已验证 Wi-Fi 联网、App CLI 生命周期、SQLStore 数据恢复及容器至 Router 通路。
最终镜像冷启动、MCU 上传/双向 RPC、App Lab 图形闭环和实际音视频等仍待用户烧入验收。两个可选 GGUF 未预置，其 LFS SHA 是审计记录，
下载器没有新增下载后逐字节摘要门禁。

详细记录见 [OpenSpec 验证记录](../../openspec/changes/add-qrb2210-arduino-uno-q/verification.md)。
