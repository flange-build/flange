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

## Docker/APFS 稀疏复制修复

2026-09-08 用户标准 debug 构建完成前六个组件，但 image 失败。实际容器中 GNU cp 9.4 已存在；
复制 rootfs 复现 `error deallocating ... Invalid argument`，添加 `--reflink=never` 仍复现。
原实现把所有非零退出码误报为缺少 GNU cp。

UNO Q 组包改为按零块 seek/truncate，保留空洞及真实 I/O 异常。38 项刷写回归通过，覆盖
无外部 cp、数据/尾部空洞/权限保留和磁盘满诊断。随后在同一标准 amd64 Docker/APFS 路径中，
使用用户实际 debug 的 U-Boot、EFI、rootfs、userdata 和固件完整执行 `build_bundle`、`validate_bundle`，
成功退出。rootfs 逻辑 9663676416 字节、实占 2327314432 字节；userdata 逻辑 3221225472 字节、
实占 2220359680 字节。清单 SHA256：`1d6bd9f72efe2838fdbbd55d7b42b10a0192c931965523b469e11af79b7aca07`。
报告保存在 `.build/verification/unoq-sparse-copy-fix/result.json`；验证临时副本已清理。
此检查复用了前六个组件的产物，没有重新执行整个 `flange build`，也未写入组件缓存成功标记。

## 2026-09-08：仓库内置 QDL 宿主工具

按用户最终选择保留 QDL，不实施 edl-ng 适配。入库官方 `qdl-packing v2.4-26`
四个发行文件，覆盖 macOS/Linux 的 ARM64 和 x86_64，总二进制约 14 MiB。
四个压缩包均与 GitHub Release API 提供的 SHA256 比对通过；每个架构目录的
`manifest.json` 记录来源、压缩包摘要及入库文件摘要，保留随附 LICENSE 和上游 README。
打包配方固定在 `81e410a3f6b86b86531e713acf87188ee9a583bf`，二进制未修改。

验证结果：
- macOS ARM64 原生与 x86_64（当前 Mac 的 Rosetta 环境）均成功运行 `--version`。
- Linux x86_64 在已有 `flange-build:latest`、ARM64 在已有 `ubuntu:24.04` 容器运行通过；
  两个容器使用 `--network none` 且未透传 USB，`ldd` 未发现缺失运行库。
- 四者均输出上游 `qdl version v2.4-dirty`；macOS ARM64 的 `--help` 确认支持原有
  `--serial`、`--storage` 和 read XML 参数。
- `tests/test_unoq_tools.py` 与 `tests/test_unoq_flash.py`：45 项通过。
- 仅增加宿主架构选择，无需重建 Docker、kernel、rootfs 或已有镜像发布包。

没有连接或刷写设备，实板验收仍保持未完成。以上运行测试不代表 UNO Q USB 刷写已验收。

## 2026-09-08：Finder 元数据导致发布包预检失败

实际 debug 发布包比 manifest 多出根目录 `.DS_Store`，无缺失文件。
文件集合校验仅豁免清单外的普通 `.DS_Store`；清单内文件照常校验，其他额外文件、
普通及悬空符号链接均不享受豁免。错误消息列出缺失与额外路径。

实际 debug 的 `UnoQFlashStrategy.preflight` 已通过，包含发布包全部文件摘要、
XML/GPT 与 flash-config 计划比对；未删除元数据、改写镜像或 manifest，未访问 USB。
工具选择与刷写测试合计 49 项通过，严格 OpenSpec 校验通过。

## 2026-09-08：macOS USB 枚举修复

实际 `ioreg -p IOUSB -a` 返回字典根节点，原遍历函数误将字典键当作节点，
触发 `AttributeError`。同时该命令未包含 `-l`，实际结果缺少 idVendor/idProduct。
改为 `ioreg -p IOUSB -l -a`，递归兼容字典与列表，只遍历 IORegistryEntryChildren。

51 项工具与刷写回归通过；新增用例覆盖两种根节点、嵌套设备、非设备节点和不同 VID/PID。
在当前 Mac 运行修复后的 detect_device，已识别一个具有有效串号的 EDL 候选设备。
此次验证仅调用 ioreg，不启动 QDL、不读写设备存储；GPT 身份验证和实板刷写仍待执行。

## 2026-09-09：实时刷写输出

用户报告一次全量刷写成功，用时 292.2 秒；这是用户提供的写入完成结果，
不等同于读回、冷启动和运行时功能验收。原 capture_output 隐藏了整个刷写过程。
现使用 PTY 转发 QDL 输出，交互终端设置有效宽度启用原生进度，重定向设置零宽度仅保留普通消息。
stdout/stderr 合流实时落盘；超时、非零退出保留日志，异常路径回收子进程，不自动重试。
镜像复核、GPT 读取、实际写入分别显示阶段提示。

模拟子进程握手验证：子进程等待终端已收到进度后才退出，同时断言磁盘日志已包含进度；
覆盖交互/重定向、失败退出码及超时后日志保留和进程回收。本轮未启动实际刷写。

## 2026-09-09：首次 ADB 实板核验，完整适配未通过

通过指定 ADB serial 连接并确认 model 为 Arduino UnoQ，用户为 arduino，
系统 Ubuntu 24.04.4，内核与 modules 目录均为 `7.0.0-flange-unoq+`。
检查限于只读状态和无线扫描，未覆盖 MCU sketch、修改 GPT 或重启设备。
板端时钟显示 2026-07-28，以下记录日期采用宿主时间。

已观察到：系统启动及 ADB 登录成功；userdata 挂载于 /home/arduino 并扩至现有分区；
Arduino Zephyr core 0.90.0 可列出，Router 启动并打开 ttyHS1；Bluetooth hci0 固件初始化成功。
这些证据不等同 MCU 双向 RPC、蓝牙连接、重复冷启动及完整应用闭环验收。

未通过及阻塞项：
- Wi-Fi：ath10k_snoc 已加载并绑定 c800000.wifi，但 /sys/class/ieee80211 为空，
  只有 lo/docker0 网卡，nmcli 无无线设备或扫描结果。modem remoteproc 为 offline，ADSP 为 running。
  rmtfs 与 tqftpserv 都依赖不存在的 qrtr-ns.service，均 inactive；这是确定的依赖缺陷，
  修复后仍须重新验证 Wi-Fi 注册、扫描、连接，不能推定为唯一原因。
  wlanmdsp.mbn、modem.mbn 等存在于 /usr/lib/firmware/updates/qcom/qcm2290。
- Arduino 容器：flange-unoq-data 报“容器架构错误”，实际镜像 Architecture 为 arm64，
  但 Image ID 为 sha256:7254a587d6f9f090ceb50f344ede4ceac9e12f4ec83eb25461efde95bdc4db17，
  与锁定 config_digest sha256:22b878f2712b7b2fe0fddaa677393886045746819e127615cafca4c63b306015
  不同；需要核对归档转换流程，不能通过放宽校验解决。App CLI 因依赖失败未启动。
- qbootctl：/chosen 和 cmdline 均没有可信槽位，成功标记服务正确拒绝写入，槽位传递尚未打通。
- Avahi：arduino.service 发布文件缺失，串号配置失败。
- zramswap：配置 lz4，但当前 zram 仅提供 lzo-rle/lzo。
- lightdm：服务失败，桌面尚未通过验收；内核另报告缺少 qcom/venus-6.0/venus.mbn。

原始补充诊断：`.build/verification/arduino-uno-q/20260909/diagnostics.txt`。
8.1–8.7 仍保持未完成，不归档、不宣称完整适配完成。

## 2026-09-09：首轮运行时修复及实板复验

用户明确授权 arduino 用户密码和测试无线网络；设备操作固定 ADB serial，未执行 GPT 写入、
MCU 上传或重启。用户密码及 Wi-Fi 密码不写入仓库。设备处于本轮热修复状态，尚未从新镜像冷启动。

### 已修复且实板通过

- 补齐 Ubuntu qrtr-tools 1.0-2ubuntu3；包 SHA256 与设备 APT 索引一致。
  qrtr-ns/rmtfs/tqftpserv 启动后 modem 与 Wi-Fi 初始化，wlan0 注册成功，2.4/5 GHz 均可扫描。
  连接用户指定网络后 DHCP 获得 192.168.10.130，默认路由、DNS 和 HTTPS（Ubuntu Release HTTP 200）通过。
  无线与蓝牙均没有软硬阻断；蓝牙连接仍未测试。
- Docker 29.1.3 使用 containerd 存储，inspect.Id 是 manifest 身份，不能等同 config digest。
  新 helper 从本地 ctr 内容库读取 manifest，自行校验 manifest SHA256 与锁定 config_digest，
  仍要求 linux/arm64；经典 Docker ID 路径继续支持。Compose 使用校验后的真实本地 ID。
  五个离线镜像均成功导入，flange-unoq-data active；未修改源容器锁或放宽摘要检查。
- App CLI 平台版本约束改为 `=0.90.0`（Environment 的赋值符加约束等号表现为双等号），
  0.13.0 daemon 稳定运行；/v1/version 返回版本，/v1/apps 返回示例列表。
  既有 NRestarts=52 为修复前失败计数，修复后观察未继续增长。
- 从已固定 Arduino overlay 补回 Avahi arduino.service，串号服务 active。
- 显式安装 lightdm-gtk-greeter 并选择 Xfce，LightDM active；未宣称实际外接显示画面已验收。
- zram-tools 使用内核支持的 lzo-rle；zramswap active，/dev/zram0 已作为交换区启用。
- 补齐 systemd-timesyncd；先校准旧时钟，随后 NTPSynchronized=yes，恢复正常 TLS 校验，未使用 -k。
- 旧锁定 Debian firmware-qcom-soc 中 Venus 为 6.0.52，低于当前内核要求 6.0.55，
  实测被拒绝。改为 Linux Firmware 固定 20260221 标签独立资源，SHA256
  602d18992dbc11c7141472d4c68778d49277491ca7452ebf6115be0e6119572a，随附同标签 LICENSE.qcom。
  重新加载后出现 Qualcomm Venus decoder /dev/video0、encoder /dev/video1；实际编解码未验收。

构建配方同步增加依赖、登录界面配置、Avahi 与 Venus 资源锁、容器身份 helper、App CLI 约束，
并扩充 verify-runtime 门禁。zram 配置在 rootfs 定制中修改，不由自有 DEB 占用发行版已拥有的文件。
91 项 UNO Q 平台、运行时、USB、刷写与实时输出测试通过；包括错误 manifest/config/platform 拒绝。

### 仍未完成

systemctl --failed 仅剩 qbootctl.service；实际 /chosen 仍无可信 arduino,boot-slot。
尚未修改启动固件或猜测 A/B 槽位。后续需定位并修复槽位跨 U-Boot/EFI 的传递，再做冷启动与成功标记验收。
本轮未完整重建 rootfs/boot/image，现有发布包不包含这些热修复。MCU RPC、App Lab 创建运行闭环、
真实编解码、显示音频及重复冷启动仍保持待验收，不归档变更。

参考：Docker 官方 containerd 存储说明 https://docs.docker.com/engine/storage/containerd/ ，
实际身份行为通过设备 ctr content 与 Docker inspect 交叉验证。


## 2026-09-09 后续适配验证

- U-Boot 槽位捕获移到 EVT_OF_LIVE_BUILT，在 EFI 修改 DTB 之前复制并校验前级 bootargs。
  后续 ft_board_setup 仅传递已捕获值，并清除外部 DTB 自带的槽位声明。
  这是针对 live tree 属性时序的修复假设，未用新固件重启，不能宣称 qbootctl 已恢复。
- Docker 中 U-Boot 编译及 Android v0 容器校验通过；提取实际 C 捕获函数进行 12 个
  分支检查，覆盖 A/B、重复键、非法值、缺失属性、未终止字符串及其他板型。
- App CLI API 创建 flange-validation-20260909，指定 skip-sketch=true；完成
  stopped → running → stopped → running，容器两次输出 Hello world!。
  SSE 以 SERVER_CLOSED 结束，结果以 API 状态及容器日志交叉确认。
  容器 socket 调用 $/version 收到 MessagePack 响应 [1, 1, null, "0.10.0"]。
  该项只证明 Linux 容器与 Router 通路，不代表 MCU RPC 或桌面 App Lab 验收完成。
- 编译专用 bridge_validation sketch，通过固定 Zephyr core 0.90.0 及 RouterBridge 0.4.3；
  程序 72016 字节、全局变量 25698 字节，提供 flange.echo 回显和 flange.tick 递增通知。
  尚未上传，不修改既有 MCU sketch 或 bootloader。
- ALSA 枚举 Arduino-Imola-HPH-LOUT，DRM 提供 renderD128，DP-1 为 disconnected。
  Venus 枚举 H.264/HEVC 编码及 H.264/VP9/HEVC 解码格式；均不替代实际音视频测试。
- 修复 packages/.gitignore 的 *.d 规则对 LightDM 配置目录的误忽略。
- 91 项相关 Python 回归通过。启动完整重建；因磁盘可用空间只有约 1.5 GiB，
  清理三次旧构建的 rootfs/run-* 临时输出后恢复约 14 GiB，保留已发布镜像与验收记录。

本轮证据位于 .build/verification/arduino-uno-q/20260909/：boot-slot-build.log、
slot-parser-test.c/log、bridge-compile.log、bridge_validation/、peripheral-inventory.txt、full-rebuild.log。

SQLStore Brick 已实测创建 SQLite 表、写入 value=42、读回；通过 App CLI 停止并再次启动 App 后，重新打开数据库仍读回同一记录，证明该 Brick 的本地数据持久化路径可用。测试数据仅位于专用验证 App 内。

运行时安装包已完成重建（11 分 26 秒），完整构建进入 rootfs 的基础包安装阶段。
成套镜像尚未完成，9.5 不勾选；新启动固件尚未部署，9.4/9.6 不勾选。
可重复执行的 MCU 测试位于 tests/hardware/arduino_uno_q/，尚未授权上传。
官方 flash_sketch.cfg 会在基础 Zephyr 固件不匹配时重写 filename0，后续上传必须额外核验写入范围。


## 2026-09-09 最终实现与烧入包交付

用户要求先完成适配实现，将烧入和最终实板验证留到最后交付。按此顺序，本轮不再对设备执行写入、
MCU 上传或重启；OpenSpec 的硬件验收条目继续待完成，不归档。

### 完成项及证据

| 交付项 | 当前证据 |
| --- | --- |
| U-Boot 槽位修复 | 优先读取 ABL 实际 DTB；初始 live tree 为无外部 DTB 时的来源；合法值提前复制，EFI 阶段传递。Docker 编译、Android v0 独立解包通过，实际 C 函数 17 项边界用例通过 |
| Ubuntu 与独立 userdata | 标准 Docker 成套重建完成；直接读取最终 ext4，逐字节比对热修复文件，固件摘要、ABI/initramfs 报告、core 0.90.0 检查通过；两份 ext4 的 e2fsck -fn 通过 |
| EFI 启动输入 | 从最终 FAT 镜像提取 Image、DTB、initrd、BOOTAA64，与对应组件实际文件逐一比对一致；启动项及 DTB 身份通过 |
| QDL 交付包 | 最终构建 18 分 18 秒，34 分区；调用与 flange flash 相同的纯本地 preflight，通过文件集合、摘要、GPT/XML、分区映射及 flash-config 绑定校验 |
| 组件一致性 | 组件 Artifact.validate 通过，再用原始文件 SHA256 对比 QDL manifest；注意组件 sha256 是含类型/权限的 hash_path，不能直接当作文件原始 SHA256 |
| 离线回归 | 91 项相关 Python 测试通过、OpenSpec 严格验证通过、git diff --check 通过 |
| 用户验收入口 | docs/boards/arduino-uno-q-handoff.md；tests/hardware/arduino_uno_q/collect_runtime.py、bridge_validation/、verify_bridge.py；脚本语法和帮助入口检查通过 |

最终包 manifest 原始 SHA256：`d558f55bf37af6619fe6c58c3dda15193f7c2c2f64a92b3779ba95a75317013f`。

- `files/uboot-boot.img`：577536 字节；SHA256 `4011e09a8d691d0bd32d0d839520d8905fdb8c4e4b472ba7aa9650670f9a2ff8`。
- `files/efi.img`：536870912 字节；SHA256 `c5eaf86bf44deba1f2d7680381526b6d67e1b7ef5ecc66b6ddfb39e5485d1499`。
- `files/rootfs.img`：9663676416 字节；SHA256 `4e32c31b08821af76a9d01e5a95589207e4b2e42dae246138d228d0074f119cc`。
- `files/userdata.img`：3221225472 字节；SHA256 `dccc822148da958c05d97e0a83cfb2a89bb0fa9aa764b36b5fb558774e4a451d`。

证据位于 .build/verification/arduino-uno-q/20260909/：
final-image-build.log、boot-slot-final-build.log、slot-parser-test.log、final-rootfs-report.json、
final-esp-report.json、final-bundle-check.log、final-delivery.json、final-flash-list.log、final-regression.log。

未把本地交付通过等同于硬件完成：最终镜像的 qbootctl 成功标记、断电重启与网络恢复、MCU 双向 RPC、
App Lab 图形流程和实际 Bluetooth/USB Host/显示/音频/摄像头仍由烧入后的验收确认。


## 目录发布字符串路径修复

后续构建在 image 目录发布阶段失败：GNU cp 返回非零后，_copy_sparse 的备用分支对字符串调用
.open()，产生 AttributeError。shutil.copytree 的 copy_function 参数实际为字符串，原测试只覆盖
直接传入 Path 的文件复制，未覆盖这个调用方式。

在 _copy_sparse 入口将 str/PathLike 统一为 Path；不改变复制策略和分区布局。
新增真实 copytree 回归，分别模拟 cp 缺失和 cp 留下部分输出后失败，修复前两例均复现原异常，
修复后验证文件内容、长度、权限、符号链接与稀疏占用。平台发布及 UNO Q 相关 73 项回归通过，
Docker Python 3.12 的实际目录备用复制也通过。本轮未重新执行完整 flange build。

构建盘当时仅剩约 1.5 GiB，清理此前由助手生成的 rootfs/run-dsq0v0dt 和 image/run-pwhqec5r
旧临时副本；保留当前正式产物和用户本次失败构建的临时结果。原日志未保留 cp 的 stderr，
不能据此断言该次 cp 的底层失败原因就是空间不足。


## 2026-09-09 用户烧入后 ADB 验收：未全部通过

复制修复 27b9e9e34 已推送后，通过 ADB 执行只读验证，没有重启、重新加载容器或写入 MCU。
设备运行新编译的 7.0.0-flange-unoq+ 内核；container_identity.py 与 load-containers 的原始摘要
均与仓库一致，不能把本次容器失败归因于旧版加载脚本。

- 通过：ADB 登录、Wi-Fi DHCP/默认路由/DNS、HTTPS 200、NTP 同步；独立 userdata 扩容至约 18 GiB。
- 状态正常：Router、rmtfs、tqftpserv、qrtr-ns、LightDM、zram；Bluetooth 控制器可枚举且未 rfkill 阻断。
- 驱动节点存在：DRM renderD128、Venus video0/video1、ALSA 声卡；外接显示未连接，不代表实际音视频已通过。
- 失败：/chosen/arduino,boot-slot 仍缺失，qbootctl.service 失败。之前补丁的离线检查不能证明实际 ABL/EFI 通道有效。
- 失败：flange-unoq-data 导入 ei-models-runner 时，containerd 返回 lease does not exist，App CLI 因依赖失败未启动，8800 端口不可用。只完成两个预装容器导入。
- 日志显示首次 NTP 校时把系统时间从 7 月 28 日跳到 9 月 9 日，发生在导入期间；这可能使 containerd 租约过期，但当前仅为待验证假设。

证据：.build/verification/arduino-uno-q/20260909/after-user-flash.json 和 after-user-flash-details.txt。
完整适配验收仍未通过，下一步需定位槽位传递及首次容器导入与校时的顺序问题。
