# 语义快照差异审查

旧加载器与 Jsonnet canonical 配置对全部 56 个 lunch target 的对照结果，只包含以下有意差异：

| 范围 | 差异 | 功能结论 |
| --- | --- | --- |
| Allwinner A733（6 个 target） | `riscv` 改名为 `riscv_toolchain`，`tarball` 统一为 `filename`，两个 toolchain 补充 SHA256 | 下载 URL 与文件名不变；新增完整性校验 |
| Qualcomm QCS6490（4 个 target） | PPA key 补充 `filename` 与 SHA256 | 下载 URL 不变；新增完整性校验 |
| 46 个含分区表的 target | 移除旧条件解析器误写入 `partitions.product/variant` 的字段 | 两字段无消费者，分区 entries 不变 |
| Qualcomm QCS6490（4 个 target） | AIC8800 firmware 从内嵌 repo 字段改为共享 `kernel.oot_sources` 引用 | URL、commit、subpath、文件和目标目录不变 |
| radxa-dragon-q8b debug | 四个板级包与图形包的排列顺序变化 | 包集合完全相同，apt 安装功能不变 |
| 全部 56 个 target | 公共 overlay source 从浮动引用固定到 commit `902ba0e8672c8e79db9f5f675fe35f697ff3beb3` | 来源仓库不变；构建输入改为可复现 revision |

除此之外，Kconfig、defconfig、设备树、overlay 列表、rootfs 包集合、源码 checkout、下载 URL、固件文件和分区 entries 均无差异。
