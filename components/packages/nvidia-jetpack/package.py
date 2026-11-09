"""NVIDIA JetPack 4.6.6 功能包：在 L4T R32.7.6 rootfs 中预装 CUDA / cuDNN / TensorRT 等 SDK。"""

PACKAGE = {
    "name": "nvidia-jetpack",
    "description": "JetPack 4.6.6（CUDA 10.2 / cuDNN 8 / TensorRT 8 / VPI / VisionWorks）",
    # 全部内容来自 NVIDIA r32.7 APT 源，没有需要 flange 构建的组件。
    "components": [],
}
