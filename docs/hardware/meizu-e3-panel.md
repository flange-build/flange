# 魅族 E3 屏幕功能包

`meizu-e3-panel` 将面板、sec_ts 触摸和 sgm37604a 背光相关驱动与设备树组合为可选功能包。
选择板卡实际声明的 `meizu-e3-bringup` product，不把同一屏幕的接线复制到其他 SoC。

| 板卡 | 启动与接线入口 |
| --- | --- |
| [Radxa ROCK 5B](../boards/radxa-rock5b.md) | RK3588 的 DSI/触摸/I2C 背光与运行期 overlay |
| [Radxa Cubie A7A](../boards/radxa-cubie-a7a.md) | A733 对应 overlay；触摸供电有独立硬件限制 |
| [Radxa Dragon Q6A](../boards/radxa-dragon-q6a.md) | QCS6490 构建期 DTB 合并，I2C FIFO 与背光路径按板配置 |

驱动与配置入口为 [package.py](../../components/packages/meizu-e3-panel/package.py)。
面板点亮、背光调节、触摸坐标和休眠恢复分别验收；DTB 编译成功不证明电源与接线正确。
A7A 已观察到触摸无响应和中断风暴；供电瞬态是排查方向，尚无电气根因及改装验收，见[现象与边界](a7a-touch-power.md)。

内核升级时同时检查 DRM panel、I2C、GPIO 与触摸驱动 API；包内兼容层不代表任意内核均受支持。
构建与运行期覆盖的配置边界见[设备树覆盖](device-tree-overlays.md)。
