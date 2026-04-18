## REMOVED Requirements

### Requirement: Allwinner Flash 策略注册
**Reason**: 平台重命名为 `allwinnera733`，`_FLASH_STRATEGIES` 注册键从 `"allwinner"` 改为 `"allwinnera733"`，策略类名从 `AllwinnerFlashStrategy` 改为 `AllwinnerA733FlashStrategy`，本 capability 整体被 `allwinnera733-flash` 替代。
**Migration**: 参见 `allwinnera733-flash` 中的"A733 Flash 策略注册"；代码中所有 `get_flash_strategy("allwinner")` 调用改为 `get_flash_strategy("allwinnera733")`。

### Requirement: Allwinner SD 卡 dd 刷写
**Reason**: 平台重命名为 `allwinnera733`，本 capability 整体被 `allwinnera733-flash` 替代。
**Migration**: 参见 `allwinnera733-flash` 中的"A733 SD 卡 dd 刷写"。

### Requirement: Allwinner 分区镜像映射
**Reason**: 平台重命名为 `allwinnera733`，本 capability 整体被 `allwinnera733-flash` 替代。
**Migration**: 参见 `allwinnera733-flash` 中的"A733 分区镜像映射"。

### Requirement: Allwinner 设备检测
**Reason**: 平台重命名为 `allwinnera733`，本 capability 整体被 `allwinnera733-flash` 替代。
**Migration**: 参见 `allwinnera733-flash` 中的"A733 设备检测"。

### Requirement: Allwinner 无 pre_flash 步骤
**Reason**: 平台重命名为 `allwinnera733`，本 capability 整体被 `allwinnera733-flash` 替代。
**Migration**: 参见 `allwinnera733-flash` 中的"A733 无 pre_flash 步骤"。
