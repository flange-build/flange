## ADDED Requirements

### Requirement: Tegra186 平台与 TX2 板卡可被发现
配置注册表 SHALL 发现 `nvidiategra186` 平台、`tegra186` SoC 与 `nvidia-jetson-tx2` 板卡，
并提供 `nvidia-jetson-tx2-default-debug`、`nvidia-jetson-tx2-default-release` 与 `nvidia-jetson-tx2-jetpack-{debug,release}` 目标。
平台包 `builder/platforms/nvidiategra186/` SHALL 满足 `PlatformSpec` 契约，`flash_tool` 为 `tegraflash`，recovery 组件关闭。

#### Scenario: 目标出现在列表中
- **WHEN** 执行 `flange target list nvidia-jetson-tx2`
- **THEN** 输出包含 default 与 jetpack 两个产品各自的 debug / release 目标

#### Scenario: 配置求值与计划完整
- **WHEN** 对 `nvidia-jetson-tx2-default-release` 执行 `flange plan`
- **THEN** 配置通过严格校验，计划列出 kernel、bootloader、boot、rootfs、image 及其依赖与必需产物，不包含 recovery

#### Scenario: 平台契约符合性
- **WHEN** 平台契约测试加载 `builder.platforms.nvidiategra186`
- **THEN** `ARTIFACT_NAMES` 与 `create_builder` 存在，`create_builder(component, None, None)` 对全部启用组件可实例化且不做实际工作

### Requirement: 内核从固定的 OE4T L4T 4.9 源码构建
kernel 组件 SHALL 从 `OE4T/linux-tegra-4.9` 的固定提交构建，使用 `tegra_defconfig` 与容器内默认 gcc-10.5 工具链，
产出 `Image`、`tegra186-quill-p3310-1000-c03-00-base.dtb` 与 modules 树，内核 release 与 stock 一致为 `4.9.337-tegra`。
DTB SHALL 在构建树中按文件名匹配后发布；同名拷贝内容必须一致，缺失或内容不一致时构建失败。

#### Scenario: 内核产物齐全
- **WHEN** 在 Docker 内执行 `flange build kernel`
- **THEN** kernel 产物目录包含 `Image`、`tegra186-quill-p3310-1000-c03-00-base.dtb` 与 `modules/lib/modules/<release>/`，release 为 `4.9.337-tegra`

#### Scenario: DTB 缺失或多份不一致
- **WHEN** 构建树中找不到同名 DTB，或多份同名 DTB 内容不同
- **THEN** 构建失败并列出实际匹配路径，不发布任何 kernel 产物

### Requirement: bootloader 收取 L4T BSP 预编译启动链
bootloader 组件 SHALL 通过 `bootloader.l4t_bsp` 下载描述符获取 L4T R32.7.6 BSP 并校验 SHA256，不从源码编译任何前级固件。
解包 SHALL 拒绝绝对路径、`..`、设备文件与越界链接，只提取 `Linux_for_Tegra/bootloader/` 与配置点名的 cboot DTB。
组件 SHALL 用 BSP 的 `mkbootimg` 把预编译 U-Boot 封装为 `kernel` 分区的 `boot.img`（头部 cmdline 取自配置），
生成 `kernel_bootctrl.bin`，并发布 `bootloader/tegraflash/` 目录。

#### Scenario: BSP 摘要不符
- **WHEN** 下载的 BSP 文件 SHA256 与配置不一致
- **THEN** 构建在解包前失败，缓存中不保留该文件

#### Scenario: 恶意归档成员
- **WHEN** BSP 归档包含绝对路径、`..` 或指向目标树外的链接成员
- **THEN** 解包失败并指出成员名，不发布任何 bootloader 产物

#### Scenario: 与 flash.sh 产物一致
- **WHEN** 使用与参考刷写相同的 BSP 与 cmdline 构建 bootloader
- **THEN** 产出的 `boot.img` 与 `kernel_bootctrl.bin` 与 flash.sh 生成的参考文件逐字节相同

### Requirement: cboot DTB 与内核 DTB 分离
`bootloader-dtb` 分区 SHALL 使用 BSP 预编译 DTB；`kernel-dtb` 分区 SHALL 使用 flange 内核构建的 DTB，
由 boot 组件在构建期合并 DTBO 后发布为 `boot/kernel-dtb.dtb`。平台 SHALL 声明 `DTBO_MERGE_AT_BUILD = True`，
不得配置运行期 overlay。

#### Scenario: 修改内核 DTS
- **WHEN** 板级内核补丁修改 DTS 后重新构建
- **THEN** `boot/kernel-dtb.dtb` 更新，`bootloader/tegraflash/` 中的 cboot DTB 保持不变

#### Scenario: 声明运行期 overlay
- **WHEN** TX2 配置声明 `boot.overlays.enabled`
- **THEN** 配置校验失败并提示本平台只支持构建期 overlay 合并

### Requirement: 板级 tegraflash 事实由配置声明
与 fab 相关的 BCT 配置文件、BPMP DTB、ODMDATA、分区模板 token 表、APP 分区尺寸与 EEPROM 身份期望 SHALL 通过
`bootloader.tegraflash` 与板级 `partitions` 声明；T186 共用事实位于 SoC 层，fab 相关事实位于 board 层。
配置引用的每个文件 SHALL 在构建期于 BSP 中存在，缺失时构建失败并指出字段路径。

#### Scenario: 配置引用不存在的 BCT 文件
- **WHEN** 板级配置的 `pinmux_config` 指向 BSP 中不存在的文件
- **THEN** bootloader 构建失败，错误包含字段路径与文件名
