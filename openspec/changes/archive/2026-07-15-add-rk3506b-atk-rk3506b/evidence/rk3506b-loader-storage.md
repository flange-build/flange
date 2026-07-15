# RK3506B loader 存储能力实机记录

记录日期：2026-07-12。

## 实机结果

ATK-RK3506B 已处于 Loader 模式。`flange flash` 在旧配置尝试查询存储列表时得到：

```text
List of supported storage
Error:Read Storage list failed!
```

随后直接执行 `upgrade_tool SSD` 得到：

```text
SwitchStorage failed,device doesn't have the feature
```

该结果表明当前 RK3506B loader 不提供 `SSD` 存储切换 capability，不表示 SPI NAND 不存在。
该板是单一 512 MiB SPI NAND 启动介质，刷写应保持 loader 当前介质，不配置
`flash_storage` selector，直接执行 `DI -p parameter.txt` 与具名 `DI` 分区写入。

## 原厂流程交叉确认

原厂 SDK release v1.3.1 的
`device/rockchip/common/scripts/rkflash.sh` 流程为上传 `MiniLoaderAll.bin` 后直接执行
`upgrade_tool di -p parameter.txt`，再执行 `di -uboot`、`di -b`、`di -rootfs` 等具名写入；
流程中没有 `SSD` 命令。这与实机返回一致。

## 实现约束

- `storage.type=spinand` 决定 parameter、UBI 与具名 DI 路由；
- `flash_storage` 只用于确实支持 `SSD` 的多介质 loader；
- ATK-RK3506B 的 `flash-config.json` 应为 `storage_type=spinand`、`storage=""`；
- 全刷用 `UL miniloader -noreset` 处理 miniloader，且不生成 `DI -idbloader`；
- 单分区刷写仅在 MaskROM 模式用 `DB` 临时下载 miniloader，Loader 模式跳过 `DB`；
- 两种模式均不执行 `SSD`；
- UFS 等显式配置 selector 的 target 仍须查询并严格校验 `SSD` 列表。

本记录只确认 loader 存储切换能力。容量探测、原厂备份、parameter 解析和分区写入仍按实机
验收任务分别执行；在完成备份与 MaskROM 恢复验证前，不据此授权破坏性全量刷写。

## RCI 芯片标记实机纠正

MaskROM 下通过 `DB` 临时启动 miniloader 后，macOS `upgrade_tool RCI` 返回：

```text
Chip Info: 46 30 35 33 AD 8 B1 80 94 CC FE 7F AB 8 B1 80

F053
```

其中 `46 30 35 33` 是 RK3506B 的 4 字节芯片标记，ASCII 表示为 `F053`。身份
门禁保留可读 `RK3506`/`RK3506B` 名称的 loader 兼容性，并只新增该精确标记；不对
其他 RK35xx 芯片放宽。该次失败发生在 `UL/DI` 之前，未对 SPI NAND 执行持久写入。

`RFI/RID` 随后返回：

```text
Flash Info:
        Manufacturer: SAMSUNG,value=00
        Flash Size: 511MB
        Block Size: 128KB
        Page Size: 2KB
        ECC Bits: 0
        Flash CS: Flash<0>

Flash ID:53 4E 41 4E 44

SNAND
```

`53 4E 41 4E 44` 解码后仍是介质类别 `SNAND`，不是 Linux SPI NAND 驱动读到的
物理 JEDEC ID；`Manufacturer` 也是 loader 的泛化字段。因此刷写身份门禁改为
RCI 精确匹配芯片，RFI/RID 只精确匹配 `SNAND`/`SPI NAND` 介质类别。它仍会拒绝
eMMC/UFS，不再把不可观测的 Winbond JEDEC ID 当作必选条件。该次失败同样位于
`UL/DI` 之前，未对 SPI NAND 写入。

## macOS UL 参数顺序实机纠正

首次 MaskROM 全刷将 Linux SDK 脚本的 option-first 形式原样传给 macOS
upgrade_tool：

```text
UL -noreset <Loader>
Loading loader...
Loading loader failed,err=-1!
```

该次失败发生在加载 loader 文件阶段，尚未执行 `DI -p` 或任何分区写入。
macOS 工具 `-h` 明确声明 `UL <Loader> [-noreset] [FLASH|EMMC|SPINOR|SPINAND]`，
因此实现改为文档顺序 `UL <Loader> -noreset`，并用测试锁定完整 argv 顺序。

本次实机还暴露出 debug `flash-config.json` 早于 board/flash 源码修正：旧清单仍含
`storage="SPINAND"` 和具名 `idbloader` 分区。实现增加本地 preflight，对此类清单在
任何设备命令前失败，并提示执行 `flange build image -f`。
