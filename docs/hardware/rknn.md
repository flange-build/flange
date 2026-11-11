# RKNN 推理运行时

适用范围：Orange Pi 5 Plus / RK3588 上已记录的 Ubuntu 24.04 与 Rockchip 6.1 BSP 实验。
2026-05-19 的设备验证使用 RKNN runtime/toolkit/model 2.3.2、内核驱动 0.9.8，
ResNet18 在 NPU core 0 上完成推理，测试图 top-1 为 space shuttle（0.9997）。
这是指定模型与设备的结果，不是性能基准或其他模型的保证。

## 驱动与版本识别

新版 RKNPU 驱动通过 DRM render node 提供接口，缺少 `/dev/rknpu` 不等于驱动未加载。
设备编号动态分配，在设备上按绑定驱动定位：

```bash
for node in /sys/class/drm/renderD*; do
    readlink "$node/device/driver"
done
cat /sys/kernel/debug/rknpu/version
```

第二条需要已挂载 debugfs 且驱动提供该接口。GPU、显示与 NPU 的 render node 不应互换。
部署前对齐模型转换工具、模型格式、librknnrt 与内核驱动的兼容组合；
历史记录里的 2.3.2 不是要求盲目更新或降级的全局版本。

## 交付与验证边界

上述 librknnrt、rknn_server 和 Python toolkit-lite2 是设备现场安装，未作为通用 RKNN 功能包集成。
新刷镜像不保证含这些文件。要固化到产品，应使用 App/vendor 包和产品配置，
明确二进制来源、摘要、架构、许可证及运行依赖，操作入口见[扩展指南](../extension-guide.md)。

先确认驱动节点和运行库，再加载兼容模型，记录实际输出与错误。rknn_server 服务 active 只证明进程运行，
不能替代一次推理；多核性能、复杂模型、非 root 运行和 PC 远程调试需要分别验证。
不要将 `/root` 下的临时 demo 或固定设备编号写成发布接口。
