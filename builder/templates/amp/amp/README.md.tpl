# ${name}（AMP 协处理器应用）

${description}

这是一个 **amp 类型** App：协处理器从核固件（裸机 HAL / RT-Thread 之上的用户
应用），不打 deb、不进 rootfs。其 `src/` 会被 amp 组件 stage 进 SDK 应用槽位，
连同 Rockchip HAL 一起编进从核固件 `amp.img`。

## 集成进固件

在目标板的 amp product 配置里把 `amp.app` 指向本 App，例如
`components/board/tspi-rk3566/config.py` 的 amp 段加 `"app:amp": "${name}"`，然后：

```bash
lunch tspi-rk3566-amp     # 选 amp product（Linux 3 核 + cpu3 协处理器）
flange build              # amp 组件 stage 本 App 的 src 并编进 amp.img
flange flash amp          # 单刷 amp 分区
```

## 说明

- `src/main.c` 覆盖 SDK 示例 main.c，须提供 SDK 启动流程跳转的入口 `main()`。
- 从核 console 默认 UART4；与 Linux 通信走 rpmsg-lite（共享内存地址由 board
  配置 `amp.memory` 注入，与 kernel dts reserved-memory 三方对齐）。
- HAL API 见 `components/amp/rockchip/hal/lib/hal/inc`。
