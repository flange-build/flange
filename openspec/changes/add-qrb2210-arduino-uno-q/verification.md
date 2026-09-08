# 验证记录

## 2026-09-07 环境与流程

- OpenSpec：`validate add-qrb2210-arduino-uno-q --strict` 通过，proposal/design/specs/tasks 全部就绪。
- 构建宿主：macOS；Python 3.13.0，pytest 9.1.1（仓库 `.venv`）。
- Docker：OrbStack，Linux aarch64；已存在 `flange-build:latest`。
- Docker 与 USB 只读枚举经工具权限审核后成功。未执行任何设备刷写。
- 用户确认 UNO Q 暂不在身边；停止设备探测，两个内存/存储规格共用板级支持。
- 全部硬件验收待实板可用时执行，不能据离线测试填写通过。

## 验证层次

1. 静态与单元：配置/schema、计划图、产物与缓存、XML/GPT 与命令编排。
2. 容器构建：固定输入的 kernel/modules/DTB、U-Boot、Ubuntu 自有包、rootfs/EFI/发布包。
3. 实板：恢复、组件刷写、冷启动、无线/USB/显示音频、MCU 与 App Lab/Bricks。

每项记录必须说明实际命令、结果和限制。只有第 3 层完成后才进入规格同步和归档。

## 公共平台接口

- `.venv/bin/python -m pytest tests/platforms/test_platform_plan_extensions.py -q`：15 项通过。
  覆盖附加依赖的执行顺序和缓存复用、rootfs 身份使 boot 指纹变化、循环/错误依赖拒绝、
  loader 缺失与篡改、重复/越界产物和 image 全局 flash-config 契约。
- 平台扩展、engine、cache_correctness、strict_boundaries 组合回归：94 项通过
  （增加最终执行顺序测试之前的计数；不累计重复运行）。
- `bootloader.recovery_firmware` 使用统一下载 descriptor，错误 SHA256 在配置阶段拒绝。

## 配置、计划与集成

- `tests/config/test_canonical_matrix.py`、`tests/config/test_query.py`、`tests/test_unoq_platform.py`：
  37 项通过（121.61 秒），覆盖 20 个板卡、96 个目标，UNO Q debug/release 均可求值。
- `python -m builder --target arduino-uno-q-default-debug plan boot`：成功，包含 kernel、
  Arduino runtime app、rootfs/initrd 与 boot 的依赖顺序。
- 同一目标的 `app plan flange-arduino-unoq-runtime` 成功列出自有 ARM64 DEB 的计划；未将计划输出当作已构建。
- UNO Q flash/runtime、已有 flash、engine、cache_correctness、platform_plan_extensions、
  strict_boundaries 组合：176 项通过（24.62 秒）。这组覆盖与前述测试有重叠，不累计为独立测试数量。
- 实施中再次运行 OpenSpec 严格校验及 `git diff --check`，均通过。

## 扩大回归与环境诊断

- `pytest tests/builder tests/platforms tests/config tests/test_unoq_platform.py tests/test_unoq_flash.py tests/test_unoq_runtime.py -q`：
  首轮 1804 通过、25 失败（431.08 秒）。失败包含沙箱禁止 `/var/tmp` 与 loopback socket、
  multiprocessing 启动超时，以及新平台缺少两份 golden（命令序列快照）。未将此轮报告成全通过。
- 经自动权限审核后复测相关 148 项：146 通过，仅剩两份 UNO Q golden 缺失。
  已增加真实 rootfs 构造序列与 QDL 发布输入映射快照；18 项 image/rootfs golden 和 16 项平台扩展测试全部通过。
  既有平台的 golden 未改变。
- UNO Q QDL 的 36 项离线测试通过。官方救援包实测组装含 29 文件、69 GPT 分区、36 写入条目；
  此步骤的系统镜像是明确占位输入，仅验证救援资源和打包协议，不能替代任务 7.3 的完整镜像组装。

## 实际 Docker 编译

- 固定 kernel commit 的 debug 配置与最终 `qrb2210-arduino-imola.dtb` 编译成功，日志记录
  base、video_sound-usbc overlay 和最终 DTB 的合成。
- 固定 U-Boot commit 原始编译及槽位透传补丁后的增量编译成功；从真实 C 函数提取的解析测试覆盖 10 个边界。
- 环境：构建镜像 `sha256:f266dc031863889f42b1a747c796a56aa3ca6eebf19e5177bfb793615d31b2ac`，
  aarch64-linux-gnu-gcc 13.3.0；临时容器补装 `mkbootimg 1:34.0.4-1build3`，Dockerfile 已声明对应工具。
- 本地证据位于 `.build/verification/arduino-uno-q/20260907/`，包含 config、DTB、编译日志、
  C 测试及记录 SHA256 的 `metadata.json`。完整 Image/modules、rootfs 和 ESP/发布包的最终结果见下文。

## Arduino 运行时的实际检查

- 固定资源实际下载、摘要验证与解包通过，自有 DebBuilder 完成首份约 1.3 GiB DEB（9791 文件）；
  此后加入递归库等修复并重新生成最终包，首份包不作为最终交付。
- 原生 ARM64 Ubuntu 24.04 中，Zephyr core 0.90.0 的实际 sketch 编译通过：Flash 61376 字节，RAM 21720 字节。
  此检查没有上传 MCU。编译发现的 MsgPack/ArxContainer/ArxTypeTraits/DebugLog 递归依赖已固定，库索引不再浮动下载。
- 早期 userdata 内容约 1920 MiB；最终五镜像资源约 2073 MiB，使用 3 GiB 初始镜像并重新计算容量门禁。
- libgpiod 2.2.2 私有库与 qbootctl 0.2.2 源码编译通过；9 项运行时离线测试通过。
- 早期三份 OCI 归档实际下载，后续补齐五份；EI runner 内 10 个 `.eim` 预置模型已逐文件计算摘要并写入模型锁。
- rootfs 与 userdata 同时保存资源、core/库索引和模型锁的身份，启动时比较，防止单刷 rootfs 静默混用旧资源。

## APT 回归测试的时序修复

第二轮完整收集仍复现 APT worker 的 5 秒启动超时。独立诊断在不执行任何前置 App 测试时同样复现：
spawn 子进程导入测试模块耗时 7.26/14.13 秒，其中 pytest 导入 4.29/8.11 秒，尚未进入 APT 互斥区。
另发现 `multiprocessing.Queue` 的跨生产者消息顺序不能代替事务发生顺序。
修复仅在测试：worker 移到轻量辅助模块，事件附带 monotonic 时间戳；互斥、并发断言及 5 秒超时保留。
独立 7 项通过（2.35 秒），全量收集后仅执行两项也通过（5.10 秒，单项约 0.5 秒）。生产 APT 代码未修改。

第二轮全量结果为 1833 通过、上述两项 APT 测试失败（569.22 秒），报告为 `regression.xml`。
修复后的新增/受影响组合回归 176 项全部通过（7.78 秒），报告为 `regression-followup.xml`；
包含最新 kernel/flash/runtime、平台与 golden、AppBuilder、APT 及严格 schema。
运行时随后新增模型篡改/Compose 消费检查，独立 12 项通过；计数不与全量结果简单相加。
音频配置隔离及 initramfs 门禁更新后，运行时 13 项与全部平台 rootfs golden 6 项复测通过（0.25 秒），
报告为 `runtime-final-regression.xml`。UNO Q 快照新增 initrd 检查，既有平台快照未改变。

## 完整生态与基础系统

- 原生 Ubuntu 24.04 中实际执行 `verify-runtime` 成功，App Lab/OpenOCD 等 `readelf`、`ldd -r`
  无缺库或未定义符号，必需固件与 Bluetooth 固件配对检查通过。
- UNO Q 适用 Bricks catalog 增补 InfluxDB 与 llamacpp，最终共五份固定 ARM64 镜像离线归档；
  手势/QNN/Genie 属于 Ventuno Q，不混入 UNO Q 支持范围。
- 两个按需 GGUF 模型使用官方固定 Hugging Face commit URL，并记录 LFS SHA256/尺寸作为审计数据。
  未下载这些大模型，未宣称实现下载后的额外字节摘要检查，也未将云 API 服务响应当作可锁定产物。
- Docker archive 导入通常缺 RepoDigests，因此启动阶段在确认本地 Config ID 后，将实际 Compose
  转为该 Image ID。用隔离 Compose 项目实际验证 `image: sha256:<configID>`、`--pull missing` 可命中已有镜像，
  运行 `true` 成功退出并清理，无镜像拉取；完整 Arduino 应用仍待实板验收。
- 五镜像/工具资源合计 userdata 实际约 2073 MiB；初始镜像使用 3 GiB 预算，启动时仅扩展 ext4
  至已存在的 userdata 分区容量，不执行 GPT/分区修改。错误 UUID、未挂载等场景有拒绝测试。
- 完整 Ubuntu 包集已通过实际 `Qrb2210RootfsBuilder._build_phase1` 与正式基础快照保存流程，
  XFCE/WebKit/Mesa/rmtfs/tqftpserv/Docker Compose 等依赖实际安装成功；最终 Phase 2、initrd 与成像结果见下文。

## 完整 kernel/modules 验证

- 原生 ARM64 Ubuntu 24.04 Docker 中完整构建 release 成功，版本 `7.0.0-flange-unoq`，共 1698 个模块，
  strip 后约 84 MiB；Image 约 51 MiB，ARM64 EFI 头校验通过。
- 最终 `.config` 与先前交叉 release 配置逐字节相同，`CONFIG_DEBUG_INFO_NONE=y`；GCC 13.3.0。
  早期 debug 配置/DTB 是另一次验证，不将其混入 release 完整包。切换原生容器是为避免 x86 模拟编译的显著开销，
  仓库正式 Docker 镜像的架构策略未改动。
- Image SHA256：`b602570448634c2571f09c88d733781cc4cf4693ce250aef88a4190081f41f70`。
- 最终 DTB SHA256：`e6c798b76d0be6993ad01b9c383449416e5b9946a0763e893b492db5689fd5c5`。
- 配置 SHA256：`9ba044022a21fe9930e42596af7f98247ddb9d91a31fa1509b29be3e20c47f14`。
- U-Boot Android 容器 SHA256：`b4d29bf558ba7b753de87659c5acbb49dc53a944a8d94421449ea6d42e4381da`；
  与原始 AOSP v0 打包实现的六组边界输入逐字节一致，并独立解包核验负载。
- 文件、日志与逐模块摘要已保存到本地验证目录；没有将编译成功等同板上启动成功。
- 主 agent 独立重新读取 `metadata.json` 中 1770 个文件并计算 SHA256，全部匹配。

## 实际 dpkg 长路径问题与修复

完整包安装触发公共 DebBuilder 默认 PAX 归档头，dpkg 拒绝 `type 'x'`。
按 [Debian deb(5) 格式约定](https://manpages.debian.org/trixie/dpkg-dev/deb.5.en.html)，
control/data tar 显式使用支持长路径、长链接的 GNU 格式。没有忽略 dpkg 错误。
新增回归检查原始 tar 头不含 PAX，读回超过 256 字符的文件路径和链接；78 项 DEB 测试通过。
Docker 中另用实际 DebBuilder 生成小包，在独立 `dpkg --root` 临时目录安装，
文件内容、0755 权限和长链接全部通过；脚本和输出为 `deb-longpath-verify.py/.log`。
AppBuilder 与 rootfs DEB 消费者的另外 34 项回归通过（0.55 秒），报告为 `deb-consumers-regression.xml`。

## 板端 ADB 补齐

完整链路复查发现早期运行时只有客户端 ADB，缺少板端 adbd，已增加正式 USB vendor 组件与构建依赖。
Arduino 补丁版 adbd 使用 Ubuntu 原生 Android 库；实际 `ldd -r` 无缺库和未定义符号，
不引入 Debian 的 Android 系统库。自有 gadget 脚本修正上游重启清理遗漏，先解绑 UDC，再卸载 FunctionFS、
删除 ADB/ACM 功能；仅操作自己创建的 gadget。

最新平台、运行时、rootfs golden 和配置矩阵组合 41 项通过（56.15 秒），报告为 `unoq-final-regression.xml`。
新增 `tests/test_unoq_usb.py` 的 6 项通过（0.48 秒），覆盖错误身份/UID、缺失/多个 UDC、
重复启停和部分失败清理。所有输入映射临时目录，未操作真实 `/sys`、`/dev`；这些模拟不证明实板枚举。
release 用户配置省略 password 字段并保持默认锁定，debug 密码保持 arduino；两变体均有配置断言。

## 最终完整 rootfs

2026-09-08（北京时间）完成含 USB 组件的 release 构建。实际重新生成包含 Android 库的基础快照，
执行正式 `Qrb2210RootfsBuilder.build`，通过包安装、账号配置、ABI、sketch 编译、initramfs 与成像。
证据位于 `.build/verification/arduino-uno-q/runtime/`：

- `filesystem-report.json`：rootfs 9663676416 字节（9 GiB）、userdata 3221225472 字节（3 GiB），
  两者 `e2fsck` 全部通过；userdata UUID 正确，根目录 UID/GID 为 1000，服务链接包含 adbd、Router、App CLI。
- `abi-report.json`、`usb-abi-report.json`：实际 Ubuntu ARM64 动态符号验证。
- `initramfs-report.json`：initrd 14710747 字节，含 BDF 选择脚本，排除提前加载的 ath10k_snoc；
  匹配模块保留在 rootfs 中。EFI 检查为 ARM64 PE/COFF。
- `environment.lock.json`、`models.manifest.json` 与 `app-report/`：资源身份、模型摘要和正式两包报告。

主运行时 DEB 由实际 prepare/DebBuilder 生成，再经正式 AppBuilder 外部产物导入；USB 小包直接走
原始生产 AppBuilder 配方。此路径不是一次完整标准 `flange build image` 的成功证明。
主包 SHA256 为 `3f644380bb2156b208208cb53d3ce7bed9376e885515dc4e0d650061d9f44473`，
USB 包为 `7bc3919cbbcc1dd4010154f4ce76d68d8437a7dcbc67b4a90edfc89d38004e24`。

最终配置的 CLI `--target arduino-uno-q-default-release --json plan image` 与
`app plan flange-arduino-unoq-runtime` 均返回 `ok: true`；后者确认 USB 先于主运行时，
且主运行时包含真实依赖边。输出保存为 `20260907/final-image-plan.json` 和 `final-runtime-plan.json`。

## 最终 EFI 与 QDL 发布包

实际 `Qrb2210BootBuilder` 生成 512 MiB FAT32 ESP，通过 fsck；Image、DTB、initrd、BOOTAA64
全部读回与输入逐字节一致。ESP SHA256 为 `ca2d4baceeaa6aec338e1472af22c933649ed51a78e78ed3e7350486f191ee02`。

实际 `Qrb2210ImageBuilder.build` 消费最终镜像，生成含 29 文件、69 GPT 分区、36 写入条目的包；
清单 SHA256 为 `1182794a25fa97f1d6ad1e3c2f078d3acf9bb3530f9f95a67abfa3149e132bed`。
结果及代码输入见 `20260907/qdl-verification/`，包含 `result.json`、实际 flash-config、manifest、只读 fsck 日志。

16 GB 基线和 32 GB 保留 20 GiB rootfs 的离线样本通过双 GPT CRC 与容量校验，所有受保护分区条目保持原样。
最低软件容量边界提供 3279638016 字节 userdata，大于实际镜像 3221225472 字节。
这些是明确标注的合成几何样本，不是设备分区读取或实板兼容证明；本次没有设备写入。

## 宿主交付与收尾

唯一发布树位于 `.build/verification/arduino-uno-q/20260907/release/image/flash-bundle`，
对应 `release/flash-config.json` 按宿主实际路径重新生成，无容器路径。
GNU tar 1.35 稀疏流导出：128 MiB 探针实际只占 32768 字节且摘要相同；最终包逻辑 13431158912 字节，
实占 4610895872 字节（约 4.3 GiB），无中间 tar 或重复镜像树。该宿主工具为本次新增安装。

宿主 `validate_bundle` 完整校验、实际策略 preflight 和只读分区列表均通过，结果见
`20260907/release-export-result.json`。主 agent 另行复核 1800 项已记录文件摘要，全部匹配，
并再次执行宿主完整包校验，清单摘要与容器端一致。未执行设备写入。
内核临时源码、对象、五个验证容器及独立卷已清理；保留最终产物、rootfs 容器和证据，位置见 `retained-artifacts.md`。

OpenSpec 30/37 项完成，剩余 8.1–8.7 为实板验收与归档。严格规格校验及 diff 空白检查通过。
