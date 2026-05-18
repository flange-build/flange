# RKNPU 用户态环境搭建（OrangePi 5 Plus RK3588）

## 概述

在 OrangePi 5 Plus (RK3588，hostname `orangepi-5-plus`) 上把 Rockchip NPU 的用户态运行时跑通：装 `librknnrt.so` 推理库 + `rknn_server` 调试服务 + `rknn-toolkit-lite2` Python 推理 API，最后用一个 ResNet18 demo 在 NPU 上完成端到端推理验收。

**当前状态**：已验证通过（2026-05-19）。RKNN runtime / driver / model / toolkit 四方版本全部对齐到 **2.3.2**（kernel 驱动 0.9.8），ResNet18 在 NPU core 0 上 top-1 `space shuttle` 0.9997。

**约束**：所有改动 ad-hoc 落在板上（rootfs 直写 + adb push），**重刷镜像会丢**。落进 flange 仓的方案见末尾 "待办 / Follow-up"。

## 设备环境

| 项目 | 值 |
|---|---|
| 设备 | OrangePi 5 Plus |
| SoC | Rockchip RK3588（NPU 三核，8 TOPS@INT8） |
| 系统 | Ubuntu 24.04 noble (aarch64) |
| Kernel | argon BSP linux-6.1-stan-rkr5.1 |
| RKNPU 内核驱动 | `v0.9.8`（in-tree，已加载） |
| NPU DRM 节点 | `/dev/dri/renderD129`（绑 `bus/platform/drivers/RKNPU`） |
| Python | `3.12.3` |

**NPU 节点关键认知**：新版 rknpu kernel driver 走 DRM 子系统注册 render node，**没有** `/dev/rknpu` 字符设备。`/dev/dri/` 下三个 renderD12X 分属：

| 节点 | 绑定驱动 | 用途 |
|---|---|---|
| `/dev/dri/renderD128` | `rockchip-drm` | VOP 显示控制器 |
| `/dev/dri/renderD129` | `RKNPU` | **NPU 计算** |
| `/dev/dri/renderD130` | `panthor` | Mali-G610 GPU |

辨认命令：

```bash
for d in /dev/dri/renderD128 /dev/dri/renderD129 /dev/dri/renderD130; do
    echo "$d -> $(readlink /sys/class/drm/$(basename $d)/device/driver)"
done
```

确认 NPU 在 DT 中 enable：

```bash
cat /proc/device-tree/npu*/status      # okay
cat /proc/device-tree/npu*/compatible  # rockchip,rk3588-rknpu
```

确认 kernel 驱动版本：

```bash
cat /sys/kernel/debug/rknpu/version    # RKNPU driver: v0.9.8
```

## 版本对齐原则

RKNPU 整条链上四个 "版本" 必须主版本一致，否则模型加载会报 `RKNN_ERR_MODEL_INVALID` 或 runtime ABI 不匹配：

| 组件 | 来源 | 本次取值 |
|---|---|---|
| Kernel driver | in-tree（已加载） | `0.9.8` |
| `librknnrt.so` runtime | airockchip/rknn-toolkit2 GitHub | `2.3.2` |
| `rknn_server` 调试服务 | airockchip/rknn-toolkit2 GitHub | `2.3.2` |
| `rknn-toolkit-lite2` 板上 Python API | PyPI | `2.3.2` |
| PC 端 `rknn-toolkit2`（模型转换） | PyPI | 取 `2.3.2`（本变更未覆盖） |

本变更全部锁 **v2.3.2**（airockchip/rknn-toolkit2 当时最新 tag）。

## 步骤 1：装 `librknnrt.so` 推理运行时

在主机端从 GitHub release tag 下载 aarch64 二进制，adb push 到板上：

```bash
# 主机
TMP=$(mktemp -d) && cd "$TMP"
RAW=https://raw.githubusercontent.com/airockchip/rknn-toolkit2/v2.3.2
curl -fsSL -O "$RAW/rknpu2/runtime/Linux/librknn_api/aarch64/librknnrt.so"

adb push librknnrt.so /usr/lib/librknnrt.so
adb shell "chmod 0644 /usr/lib/librknnrt.so && ldconfig"
```

文件类型应为 `ELF 64-bit LSB shared object, ARM aarch64, dynamically linked, stripped`，~7.4 MB。

## 步骤 2：装 `rknn_server` 调试服务（+ systemd 自启）

`rknn_server` 在板上监听 adb 转发的连接，让 PC 端 `rknn-toolkit2` 通过 `init_runtime(target='rk3588')` 直接走 connect 模式在真板上做推理 / 性能评估，**不需要每次先转 .rknn 落板再跑**。

### 2a. 二进制 + 辅助脚本

```bash
# 主机
RAW=https://raw.githubusercontent.com/airockchip/rknn-toolkit2/v2.3.2
curl -fsSL -O "$RAW/rknpu2/runtime/Linux/rknn_server/aarch64/usr/bin/rknn_server"
curl -fsSL -O "$RAW/rknpu2/runtime/Linux/rknn_server/aarch64/usr/bin/start_rknn.sh"
curl -fsSL -O "$RAW/rknpu2/runtime/Linux/rknn_server/aarch64/usr/bin/restart_rknn.sh"

adb push rknn_server /usr/bin/rknn_server
adb push start_rknn.sh /usr/bin/start_rknn.sh
adb push restart_rknn.sh /usr/bin/restart_rknn.sh
adb shell "chmod 0755 /usr/bin/rknn_server /usr/bin/start_rknn.sh /usr/bin/restart_rknn.sh"
```

`start_rknn.sh` 是 Rockchip 原版的 `while true; rknn_server; sleep 1` 旁路重启包装。我们走 systemd `Restart=always` 更干净，但保留这两个脚本便于手动调试。

### 2b. systemd unit

```bash
sudo tee /etc/systemd/system/rknn-server.service > /dev/null <<'EOF'
[Unit]
Description=Rockchip RKNN Server
After=multi-user.target

[Service]
Type=simple
ExecStart=/usr/bin/rknn_server
Restart=always
RestartSec=1
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now rknn-server.service
```

### 设计要点

| 字段 | 作用 |
|---|---|
| `Type=simple` | rknn_server 前台运行（adb transfer 协议监听） |
| `Restart=always` + `RestartSec=1` | 替代 Rockchip 原版 `start_rknn.sh` 的 busy-loop 包装 |
| `After=multi-user.target` | 不抢早期 boot 资源；NPU 驱动早就 ready |
| 不指定 `User=` | server 需要 ioctl `/dev/dri/renderD129`，root 跑最省事；非 root 需把用户加进 `render` group 并额外授权 |

### 验证

```bash
systemctl --no-pager status rknn-server.service
journalctl -u rknn-server -n 5 --no-pager
# 期望：
#   start rknn server, version:2.3.2 (1842325 build@2025-03-30T09:54:34)
#   I NPUTransfer: Starting NPU Transfer Server, Transfer version 2.2.2 (...)
```

## 步骤 3：装板上 Python 推理栈

板上原生跑 .rknn 模型（不依赖 PC 转发）走 `rknn-toolkit-lite2`。它是 `librknnrt.so` 的 Python 绑定 + 模型 loader，只能 inference 不能转换/量化。

### 3a. 系统包：opencv / numpy / pip

```bash
adb shell "apt-get install -y python3-opencv python3-numpy python3-pip"
```

- `python3-opencv 4.6.0+dfsg-13.1ubuntu1`（noble 仓库）—— ResNet demo 用 `cv2.imread`
- `python3-numpy` —— 推理输入/输出张量
- `python3-pip` —— 装 wheel

走 apt 而非 pip 装 opencv 是因为 Ubuntu 24.04 PEP 668 限制 + opencv 拖一坨系统 lib，apt 更稳。

### 3b. `rknn-toolkit-lite2` wheel

PyPI 上 `rknn-toolkit-lite2 2.3.2` 有 cp310/311/312/37/38/39 全套 aarch64 wheel，对得上板上 Python 3.12。

```bash
# 主机
WHL_URL=$(curl -fsSL https://pypi.org/pypi/rknn-toolkit-lite2/2.3.2/json \
    | python3 -c "import sys,json; [print(f['url']) for f in json.load(sys.stdin)['urls'] if 'cp312' in f['filename'] and 'aarch64' in f['filename']]")
curl -fsSLO "$WHL_URL"

adb push rknn_toolkit_lite2-*.whl /tmp/
adb shell "pip3 install --break-system-packages /tmp/rknn_toolkit_lite2-2.3.2-cp312-cp312-manylinux_2_17_aarch64.manylinux2014_aarch64.whl"
```

`--break-system-packages` 是 PEP 668 下绕过 "externally-managed-environment" 拒绝；干净做法是 `python3 -m venv && source bin/activate` 后再 pip，但 demo 阶段省事直接系统装。

副依赖会自动拉：`psutil`、`ruamel.yaml`。

## 步骤 4：跑 ResNet18 demo 验收

demo 取 `airockchip/rknn-toolkit2` repo 内置的 `rknn-toolkit-lite2/examples/resnet18/`，含预编译的 rk3588 .rknn 模型 + 测试图（航天飞机）+ 1000 类 ImageNet label。

### 4a. 拉文件

```bash
# 主机
mkdir -p resnet18 && cd resnet18
BASE=https://raw.githubusercontent.com/airockchip/rknn-toolkit2/v2.3.2/rknn-toolkit-lite2/examples/resnet18
curl -fsSL -O "$BASE/test.py"
curl -fsSL -O "$BASE/synset_label.py"
curl -fsSL -O "$BASE/space_shuttle_224.jpg"
curl -fsSL -O "$BASE/resnet18_for_rk3588.rknn"
```

### 4b. 推上板执行

```bash
adb shell "mkdir -p /root/rknn-demo"
adb push ./. /root/rknn-demo/
adb shell "cd /root/rknn-demo && python3 test.py"
```

### 4c. 期望输出

```
W rknn-toolkit-lite2 version: 2.3.2
--> Load RKNN model
done
--> Init runtime environment
I RKNN: RKNN Runtime Information, librknnrt version: 2.3.2 (429f97ae6b@2025-04-09T09:09:27)
I RKNN: RKNN Driver Information, version: 0.9.8
I RKNN: RKNN Model Information, version: 6, toolkit version: 2.3.2 (compiler version: 2.3.2),
        target: RKNPU v2, target platform: rk3588, framework name: PyTorch, model inference type: static_shape
done
--> Running model
resnet18
-----TOP 5-----
[812] score:0.999680 class:"space shuttle"
[404] score:0.000249 class:"airliner"
[657] score:0.000013 class:"missile"
[466] score:0.000009 class:"bullet train, bullet"
[895] score:0.000008 class:"warplane, military plane"
done
```

`test.py` 默认走 `NPU_CORE_0` 单核；要并发可改 `core_mask=RKNNLite.NPU_CORE_0_1_2` 让模型在三核之间分流（仅对相同模型多 batch / 多线程推理有效，单一推理还是单核）。

## 故障排查 / 踩坑

### 1. `/dev/rknpu` 不存在 → 是否驱动没起来？

不是。新版 rknpu driver 走 DRM render node，**不再创建** `/dev/rknpu` 字符设备。判 NPU 是否 ready 看：
- `cat /sys/kernel/debug/rknpu/version` 有 `RKNPU driver: vX.Y.Z`
- `readlink /sys/class/drm/renderD129/device/driver` 含 `RKNPU`
- `cat /proc/device-tree/npu*/status` 输出 `okay`

老版本 librknn_api（v1.x）会找 `/dev/rknpu` —— 这正是必须升 runtime 到 v2.x 的理由之一。

### 2. `pip3 install` 报 `externally-managed-environment`

Ubuntu 24.04 PEP 668。两条路：
- `--break-system-packages` 暴力绕过（本变更走这条，demo 场景可接受）
- `python3 -m venv /opt/rknn-venv && /opt/rknn-venv/bin/pip install ...`（生产推荐）

### 3. `import cv2` 在 Ubuntu 24.04 缺 `libGL.so.1` 等

`python3-opencv` apt 装的话依赖自动拉齐；走 pip 装 `opencv-python` 才会缺 GL，需要再 `apt install libgl1`。本变更走 apt 路径。

### 4. ResNet demo 报 `query RKNN_QUERY_INPUT_DYNAMIC_RANGE error ...`

这是 **warning 不是 error**：模型是 static_shape 类型，runtime 仍按 static path 跑。日志后续 `Loading model failed` 才是真错。

### 5. PC 端走 `init_runtime(target='rk3588')` 连不上板

依次查：
- `adb devices` 板是否在列
- 板上 `systemctl is-active rknn-server`（应 active）
- 板上 `journalctl -u rknn-server -n 20` 看是否在 listen
- PC 端 `rknn-toolkit2` 版本必须与板上 `librknnrt.so` 主版本一致（本变更俩侧都 2.3.2）

### 6. 多模型 / 多核并发

`RKNNLite.init_runtime(core_mask=...)` 选项：
- `NPU_CORE_0` / `NPU_CORE_1` / `NPU_CORE_2`：指定单核
- `NPU_CORE_0_1` / `NPU_CORE_0_1_2`：让 runtime 在所选核里调度
- 单次 `inference()` 仍只用一个核；要真并行需多线程各持一个 RKNNLite 实例分指核

## 验收清单

- [x] `cat /sys/kernel/debug/rknpu/version` 输出 `RKNPU driver: v0.9.8`
- [x] `/dev/dri/renderD129` 绑 `bus/platform/drivers/RKNPU`
- [x] `/usr/lib/librknnrt.so` 存在，aarch64 ELF
- [x] `systemctl is-active rknn-server.service` 输出 `active`
- [x] `journalctl -u rknn-server -n 3` 含 `version:2.3.2`
- [x] `python3 -c "from rknnlite.api import RKNNLite"` 无报错
- [x] `cd /root/rknn-demo && python3 test.py` top-1 `space shuttle` 概率 > 0.99
- [x] runtime / driver / model toolkit 三方版本日志均显示 2.3.2 / 0.9.8 / 2.3.2

## 待办 / Follow-up

- **Wiki 同步**：把本流程结论摘要进 `wiki/boards/orangepi-5-plus.md` 加 `## RKNPU / AI` 段落
- **落进 flange 仓库**：当前所有改动都是 ad-hoc 落在板上的，重刷镜像会丢。后续考虑：
  - `overlay/usr/lib/librknnrt.so`（二进制资产，加 LFS 或单独 fetch 步骤）
  - `overlay/usr/bin/rknn_server` + `start_rknn.sh` + `restart_rknn.sh`
  - `overlay/etc/systemd/system/rknn-server.service` + `multi-user.target.wants/` symlink
  - `rootfs.+packages` 加 `python3-opencv`、`python3-numpy`、`python3-pip`
  - `rknn-toolkit-lite2` wheel：通过 rootfs hook 在 chroot 内 `pip install --break-system-packages /opt/wheels/*.whl`，或抽出 .so 内容打到 site-packages
  - 起独立 OpenSpec change `add-rk3588-rknpu-userspace`
  - 版本号集中到 product 配置（如 `components/product/<x>/rknn.version=2.3.2`）便于以后整体抬版本
- **PC 端 toolkit2 配套**：本变更只装板上；如果开发模型转换/量化流程，PC 端需 `pip install rknn-toolkit2==2.3.2` + 必要的 PyTorch/TF/ONNX 依赖。建议另起 dev-env 文档而非塞进本提案。
- **rknn_model_zoo 集成验证**：用 YOLOv5 / YOLOv8 / PPOCR 之类的复杂模型再过一遍 connect 模式 + 板上推理，验证非分类模型路径（检测/分割/OCR 的输入预处理、anchor 解码、NMS 等）。
- **多核 NPU 调度 benchmark**：测一下 ResNet50 / YOLOv8s 在单核 vs `NPU_CORE_0_1_2` 三核分流下的 FPS，给后续业务调度做参考。
- **非 root 跑 rknn_server**：当前 systemd unit 不带 `User=`，server 以 root 跑。要降权需把目标用户加进 `render` group（对 `/dev/dri/renderD129` 有读写权限），再 `User=<u> SupplementaryGroups=render`。同步本变更未做。
