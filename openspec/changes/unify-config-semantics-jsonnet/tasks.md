## 1. 基线与运行时验证

- [x] 1.1 在项目支持的宿主 Python 版本中验证官方 Jsonnet binding 的安装、求值和错误位置输出，固定可用版本并补一个不依赖 PATH 中 Jsonnet CLI 的最小测试
- [x] 1.2 为现有 56 个 lunch target 生成只读语义快照，覆盖 defconfig/Kconfig、source、设备树、overlay、rootfs 包、下载产物和分区输入
- [x] 1.3 将全仓字段—生产消费者清单固化为测试数据，逐项标记 canonical 字段、待删除死字段和需要补齐的公共消费者

## 2. Jsonnet 求值边界

- [x] 2.1 新增最小 Jsonnet evaluator，支持 extVar product/variant、plain JSON 解析和包含 Jsonnet 文件位置的错误信息
- [x] 2.2 实现仅允许 `components/` 内 `.jsonnet`/`.libsonnet` 的 import callback，并测试绝对路径、`..`、符号链接越界和非法扩展名
- [x] 2.3 记录实际 import 依赖并把文件内容、target 维度和 canonical JSON 接入配置内容哈希，测试无关 board 文件不改变当前 target 哈希
- [x] 2.4 新增 `components/config/lib.libsonnet`，只实现标量数组 `without` 并用 Jsonnet 求值测试验证顺序与重复元素行为
- [x] 2.5 为 rootfs/platform/SoC/board overlay 实现固定顺序组合器和身份投影，测试目录身份、platform/SoC 归属及 product/variant 同名场景

## 3. Canonical schema 与公共消费者

- [x] 3.1 扩展 Python validator 的顶层、组件和 descriptor 允许字段表，先覆盖未知字段、旧 alias、互斥字段与 source 引用错误
- [x] 3.2 增加层级求值 diff 审计，测试 SoC 层拒绝单板显示/存储路由、AMP opt-in 和产品 rootfs 包策略
- [x] 3.3 在 KernelBuilder 基类实现 `kernel.config` renderer，并移除 defconfig raw option 解释；覆盖 y/m/n、字符串 token 和执行顺序测试
- [x] 3.4 在 Bootloader 公共路径复用同一 Kconfig renderer，统一 defconfig 数组输入并覆盖 Rockchip/Amlogic 行为测试
- [x] 3.5 将各平台 Kernel/Bootloader builder 改为读取 `architecture.{userspace,kernel,bootloader}` 和 `kernel.device_tree.{directory,name}`，删除 dts/dtb/arch alias 读取
- [x] 3.6 将 SourceManager 改为只读取 `sources.<name>` 与组件 `source.{name,subpath}`，并测试 local/remote 互斥、共享 checkout 和 revision 身份隔离
- [x] 3.7 把预构建镜像、Bootloader firmware、toolchain、额外 deb 与 firmware 统一接入 `{url,sha256,filename}` 下载入口，删除平台无校验下载路径
- [x] 3.8 将构建期 DTBO 合并与 boot 运行期 overlay 分成两个 canonical 字段，并为各平台添加消费或“不支持即报错”的能力校验
- [x] 3.9 删除或补齐 `wifi.aic8800_usb`、`fip_family_inc`、Qualcomm boot 元数据和 `memory.size` 的实际行为，确保最终 schema 不保留无生产消费者字段

## 4. 基线与代表路径迁移

- [x] 4.1 迁移 `components/rootfs/config.py` 与 `components/device-tree-overlay/config.py` 为 Jsonnet overlay，验证 package set 与公共 overlay source 快照一致
- [x] 4.2 迁移 Qualcomm QCS6490 platform/SoC 与 radxa-dragon-q6a，统一 Kconfig、source、device tree 和 product 条件并通过对应配置/平台测试
- [x] 4.3 迁移 Qualcomm SC8280XP platform/SoC 与 radxa-dragon-q8b，删除 enable/disable 与 raw defconfig 混用并通过语义快照
- [x] 4.4 迁移 Amlogic platform、S905D3 与 khadas-vim3l，保留工作区已新增 Binder symbol，验证 board 与 SoC 使用同一 `kernel.config` 结构

## 5. 其余平台配置迁移

- [x] 5.1 迁移 Amlogic S905Y2 与 radxa-zero，统一 source、Kconfig、设备树和 FIP 下载 descriptor
- [x] 5.2 迁移 Allwinner A733 platform/SoC，统一共享 sources、toolchain 下载校验和多段 defconfig
- [x] 5.3 迁移 radxa-cubie-a7a 与 radxa-cubie-a7z 的 product 条件、硬件包和 overlay 配置
- [x] 5.4 迁移 Rockchip platform 与 RK3506B/RK3566/RK3568 SoC，统一架构维度、source 和 Kernel/Bootloader Kconfig
- [x] 5.5 迁移 Rockchip RK3576/RK3582 SoC，验证 Panfrost fragment、SPI loader 与 4K sector 配置快照
- [x] 5.6 迁移 Rockchip RK3588/RK3588S SoC，验证 Panthor/Panfrost、rkbin 与 overlay 配置快照
- [x] 5.7 迁移 atk-rk3506b、orangepi-cm4、radxa-zero3w 和 tspi-rk3566 board，并用 Jsonnet 条件替换所有 AMP product 后缀键
- [x] 5.8 迁移 neons-core3566-nanob 与 rp-pro-rk3568-h board，验证设备树、分区和 rootfs 包保持一致
- [x] 5.9 迁移 armsom-cm5-io 与 radxa-rock-4d board，统一 raw disable Kconfig、设备树和 bootloader 覆盖
- [x] 5.10 迁移 orangepi-5-plus、orangepi-cm5-tablet、radxa-rock5b 与 radxa-rock5c-lite board，验证显示、存储和硬件包 product 快照

## 6. 注册表切换与旧实现删除

- [x] 6.1 将 `discover_boards`、platform/SoC 发现、`get_board_config` 和 `resolve_config` 默认切换到 Jsonnet evaluator，并跑完整 lunch target 枚举测试
- [x] 6.2 将 package set、硬件特性包和外部 app 归一化定位到 canonical 求值边界，确保 builder 接收的 JSON 不含操作字段或嵌套 product/variant
- [x] 6.3 删除旧 Python `deep_merge`、条件后缀解析和各平台 enable/disable/dts/dtb/source alias 翻译代码，保留针对旧字段必然失败的 validator 测试
- [x] 6.4 删除已迁移的 37 个 `config.py` 和迁移期开关，确认注册表不再动态 import 配置 Python 模块
- [x] 6.5 更新所有受影响 OpenSpec 规格、ProjectSpec 配置章节及中文开发文档中的 `.py` 路径和旧字段示例

## 7. 全量交叉验证

- [x] 7.1 对全部 56 个 target 运行新旧语义快照对照，逐项审查并记录所有有意差异，确保无未解释差异
- [x] 7.2 运行全部 config、builder、source、cache 和平台测试，修复迁移导致的失败且不放宽 canonical validator
- [x] 7.3 对每个平台抽取一个 target 验证最终 Kernel/Bootloader override fragment、设备树路径、源码 revision 和下载 SHA256 与实际 builder 命令一致
- [x] 7.4 删除迁移期旧加载器与快照生成代码后再次运行完整测试和 56 target 求值，确认仓库只剩 Jsonnet 单栈
- [x] 7.5 运行 OpenSpec 严格校验并检查变更目录、任务完成状态和中文文档规范，形成可归档结果

## 8. 配置可读性

- [x] 8.1 为每个 Jsonnet 配置源增加中文职责注释，并用 ProjectSpec 与回归测试固化要求
- [x] 8.2 从旧 `config.py` 逐项恢复语义注释到对应 Jsonnet 字段，并审计过时字段名与实现说明
- [x] 8.3 将固定版本的 Jsonnet Python binding 安装到 Docker 构建镜像，并在镜像内验证导入和求值
