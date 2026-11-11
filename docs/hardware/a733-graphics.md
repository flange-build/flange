# A733 PowerVR 图形边界

适用范围：Radxa Cubie A7A/A7Z、A733 BSP 与所用 PowerVR BXM 用户态库。
既有设备记录表明裸 DRM/KMS（内核模式设置）上的 GLES 可使用 GPU；
不能据此推断 X11、Wayland、GTK 和浏览器都已实现硬件加速。

## 已确认的限制

现场使用的 vendor EGL 库缺少 Wayland 平台入口，应用请求不支持的平台时可能崩溃；
GNOME Shell 能出现并不证明全部 GTK 客户端都走 GPU。相同库下，X11 适配也未形成可用的默认路径。
这是特定 BSP/用户态库的结论，升级库后应重新检查，不可推广为所有 PowerVR 的永久限制。

已有记录中 `GSK_RENDERER=cairo` 可以让受影响的 GTK 应用使用软件渲染；它是兼容规避，
不是 GPU 加速修复。修改运行环境后须重新登录该会话。

## 验证方法

在设备上检查实际驱动和输出：

```bash
ls -l /dev/dri/by-path/
eglinfo
```

从 EGL renderer/vendor 判断硬件库是否被加载；llvmpipe 表示软件渲染。
运行裸 DRM 测试需要释放显示管理器占用，并选择实际显示卡，不能照抄历史 `card1`。
GPU render node 与显示 connector 可能属于不同 DRM 设备。

GPU readback（像素回读）到 framebuffer 的实验不能证明零拷贝性能；
当前 SPI 屏使用 DRM panel-mipi-dbi 路径，参见 [Cubie A7Z](../boards/radxa-cubie-a7z.md)。
板级配置与驱动来源是当前输入，历史设备上的手工装包不会自动进入新镜像。
