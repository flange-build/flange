# A733 (PowerVR BXM) GPU 桌面图形：现状、死结与方案

## 概述

A733 / a7a（魅族 E3 屏板）的 GPU 是 **Imagination PowerVR B-Series BXM-4-64**，用 IMG 闭源 DDK **24.2@6603887**（Mesa 派生的用户态）。本文整理 2026-05 对"桌面图形为什么跑不顺"的系统排查结论。

**一句话结论**：**PVR 硬件 GLES 本身完全可用，但只在「裸 DRM/KMS 直接渲染」下能硬件加速；X11 和 wayland 两条桌面路都被堵死——X11 是 Xorg 在 split-GPU 上 segfault，wayland 是 PVR EGL 编译时没带 wayland 平台。要桌面硬件加速，唯一根治是重编/换一份带 wayland WSI 的 DDK 用户态库。**

**当前状态（2026-05-25）**：
- ✅ 硬件 GLES 经裸 DRM/KMS 验证可用（`glmark2-es2-drm` 全屏硬件加速 ~500 FPS）。
- ❌ GNOME (GTK4/wayland) 设置类应用一启动即 SIGSEGV——PVR EGL 缺 wayland 平台。
- ❌ X11（GNOME-on-Xorg、KDE-on-Xorg 均试）Xorg server segfault，且会把设备搞到 adb 掉线 + 重启。
- ⚠️ 临时可用：GNOME + `GSK_RENDERER=cairo`（GTK4 软件渲染，绕开 EGL）。

> 关联：[[support_ubuntu_desktop]]（GNOME 安装/自启）、[[support_weston]]（weston compositor）、[[fb-gpu-test]]（裸 fb GPU 测试）、[[project_a7a_gpu_no_hw_gl]]、[[project_a7a_meizu_e3_panel_bringup]]。

## 设备环境

| 项目 | 值 |
|---|---|
| SoC | Allwinner A733（sun60iw2） |
| GPU | Imagination PowerVR B-Series BXM-4-64 (MC1) |
| GPU 内核驱动 | `pvrsrvkm`（OOT），固件 `rgx.fw` BVNC 36.56.104.183 |
| DDK 用户态 | 24.2@6603887（Mesa 派生，闭源 blob） |
| 系统 | Ubuntu 24.04.4 LTS (aarch64) |
| Kernel | 5.15.147+ |
| 系统 Mesa | 25.2.8 / libglvnd 1.7.0（被 PVR overlay 压住） |
| DRM card0 | `pvrsrvkm` + `renderD128` —— **PVR GPU，render-only，无 connector** |
| DRM card1 | `sunxi-drm` —— **显示控制器**，connector `DSI-1`(1080×2160)/`HDMI-A-1` |
| by-path | `platform-1800000.gpu-card→card0`、`platform-soc@3000000:sunxi-drm-card→card1`（稳定，card 枚举序重启会变） |
| Display | DSI-1 1080×2160 魅族 E3 屏（[[project_a7a_meizu_e3_panel_bringup]]） |

> **关键拓扑：这是 split-GPU**——渲染（PVR card0）与扫描输出（sunxi card1）是两个独立 DRM 节点。下面所有坑都源于此。

## 1. 硬件 GLES：可用（仅限裸 DRM/KMS）

PVR 用户态 GL 栈本身是好的，硬件加速正常：

- **`eglinfo`（GBM / Surfaceless 平台）** 报 `OpenGL ES profile renderer: PowerVR B-Series BXM-4-64`、`OpenGL ES 3.2 build 24.2@6603887`。这是最简硬件验证（surfaceless 不需 connector）。
- **`glmark2-es2-drm`** 实测全屏硬件加速跑通（见 §4.3）。

`/usr/local/lib/libEGL.so.1` 是 **PVR 配套的 Mesa 派生 EGL**（egl_dri2 框架 + `/usr/local/lib/dri/pvr_dri.so` 硬件后端），EGL vendor 字符串显示 "Mesa Project" 属正常。它支持 `gbm / surfaceless / x11 / device / drm` 平台——**唯独没有 wayland**（见 §2）。

> 注意：设备**没装 binutils**，`strings`/`readelf`/`nm` 都不存在。分析 blob 用 `grep -a`（文件 not stripped，符号在）。早先任何基于 `strings` 的"搜不到 X"判断都无效。

## 2. 核心障碍：PVR EGL 缺 wayland 平台

### 现象
GNOME 的 GTK4 应用（`gnome-control-center`「设置」首当其冲）、`glmark2-es2-wayland` 在 Wayland 会话下**一启动即 SIGSEGV，窗口根本不出现**。

### gdb 栈（决定性证据，两者完全一致）
```
#0 XGetXCBConnection ()         ← libX11-xcb.so.1
#1 dri2_get_xcb_connection ()   ← /usr/local/lib/libEGL
#2 dri2_initialize_x11 ()       ← 退到了 X11 平台
#4 eglInitialize ()
#7 gdk_display_prepare_gl ()     ← GTK4 建 GSK GL renderer（glmark2 则是自己的 main）
```

### 根因（`grep -a` 实证）
- `libEGL.so.1` 编进去的平台：`dri2_initialize_{device,drm,surfaceless,x11}` —— **没有 `dri2_initialize_wayland`**。
- `libpvr_mesa_wsi.so`(4.6MB) 的 WSI surface：`create_{xcb,xlib,display,headless}_surface` —— **没有 `create_wayland_surface`**（且多为服务 `libVK_IMG` 的 Vulkan WSI API）。

**两层（EGL + WSI）都没编 wayland。** Wayland 会话里 GTK4/glmark2 调 `eglGetPlatformDisplay(WAYLAND)`，PVR EGL 不认 wayland 平台 → 退回 `EGL_DEFAULT_DISPLAY` 被当 x11（环境里有 `DISPLAY=:0` Xwayland）→ `dri2_initialize_x11` 对无效 X 连接调 `XGetXCBConnection(NULL)` → 段错误。

### 为什么 mutter/gnome-shell 不崩
它走 **GBM** 平台（KMS+render-node 分离它原生支持），不碰 wayland 客户端 EGL 平台。崩的只是 GTK4 **客户端**应用的 GL 初始化。

## 3. X11 路线：彻底死路

设想"全面切 X11 绕开 wayland"（PVR EGL 支持 x11 平台）。实测撞上一连串坑，最终在 Xorg server 层 **segfault**——**与桌面环境/DM 无关**（GNOME-gdm、KDE-sddm 都试，rootless / root Xorg 都试）。

| # | 坎 | 处理 | 结果 |
|---|---|---|---|
| 1 | IMG 包 `xserver-xorg-img-bxm` 的 `/etc/X11/xorg.conf.d/20-modesetting.conf` 把 `kmsdev` 写死 `/dev/dri/card0` | card0 是 PVR(无 connector、不支持 dumb)，改指 sunxi by-path | 过了"KMS doesn't support dumb interface" |
| 2 | 多 DRM 卡无 BusID → `Cannot run in framebuffer mode` | `/etc/X11/xorg.conf.d` 加 `Option "AutoAddGPU" "off"` | glamor 初始化、DSI 点亮 |
| 3 | rootless Xorg(gdm) + kmsdev 触发 old-probe 绕过 logind → `drmSetMaster: Permission denied` | 改用 root Xorg（SDDM 默认 root 跑 Xorg） | 过了权限关 |
| 4 | root Xorg 仍 **`Caught signal 11 (Segmentation fault)`** | —— | **到此为止** |

第 4 步崩溃点：`[DRI2] Setup complete (sunxi-drm)` → `GLX: Initialized DRISWRAST GL provider` 之后 segfault（无符号栈，疑 PVR GL 在 Xorg glamor/GLX 上下文崩）。

**额外代价**：启动 KDE(SDDM autologin→X11) 时，SDDM 反复重试崩溃的 Xorg，把设备搞到 **adb 掉线 + 重启**（boot -1→0，受控 shutdown，非 kernel panic）。

> **`kmsdev=card0` 是 IMG 包的真 bug**，应改 by-path 指 sunxi（card 枚举序不稳）。不管走不走 X11，建议在 flange 里修掉这个配置。

**结论**：X11 在此平台不可行——split-GPU 的 Xorg glamor 链 + PVR GL on X 必崩。

## 4. 可用 / 临时方案

### 4.1 GNOME + `GSK_RENDERER=cairo`（已验证）
让 GTK4 走纯 cairo 软件 2D 渲染、绕开 EGL，`gnome-control-center` 即可正常打开。落地 `/etc/environment`（PAM 注入，GUI 会话生效，`su - flange -c 'echo $GSK_RENDERER'` 可验）。代价仅 GTK4 应用软件渲染（2D 应用够用），gnome-shell 仍 GBM 硬件加速。

### 4.2 KDE + Qt raster（未验证，理论更优）
Qt Widgets **默认就是 raster(CPU)渲染**，不碰 EGL，天然不撞 PVR wayland 缺口（比 GTK4 强制 GSK-GL 友好）；KWin 用 GBM 合成（硬件 OK）。**唯一隐患**：`plasmashell` 是 QtQuick/QML（默认 GL scenegraph），wayland 下可能仍需 `QT_QUICK_BACKEND=software`。本次因用户坚持验证 X11，**KDE wayland 未实测**。注意 `kubuntu-desktop` 默认只装 plasma **X11** 会话，wayland 会话要另装 `plasma-workspace-wayland`。

### 4.3 `glmark2-es2-drm`：裸 console 硬件 benchmark（已验证）★
**推翻"glmark2-drm split-GPU 跑不了"的旧结论。** 两个条件满足即硬件跑通：
1. **DRM master 空闲**——无 compositor/DM 占用（卸 GNOME、停 sddm 的裸 console 即可）；
2. **指对 device**——默认开 card0(PVR 无 connector)报 `Failed to find a suitable connector`，必须指 sunxi 做扫描输出：

```sh
glmark2-es2-drm --winsys-options drm-device=/dev/dri/card1
```

实测：`GL_RENDERER: PowerVR B-Series BXM-4-64`、`OpenGL ES 3.2`、`1080x2160 fullscreen`、build 场景 FPS **482/546**。render 自动走 PVR、scanout 走 sunxi，**跨卡 PRIME 其实工作正常**。这是绕开 X11/wayland 两死结的硬件渲染路径。

## 5. 根治：重编带 wayland WSI 的 DDK 用户态

wayland 硬件加速无法靠运行时配置补——全网调研（IMG/TI/Mesa 文档）结论：

- IMG 新的 **Mesa-EGL 集成方案**里，wayland/GBM 等 window system 是**编进 `libEGL.so` 的**，由 Mesa 编译期 `-D platforms=x11,wayland,…` 决定（可选 x11/wayland/android/haiku）。
- 旧的 `/etc/powervr.ini` + `WindowSystem` + `libpvrws_WAYLAND.so` 是 **SGX/老 Rogue** 机制，新 Mesa-EGL **已废弃**——**没有运行时开关**。
- 我们这份 DDK 24.2 编译时 `platforms` 只含 `x11/drm/surfaceless/device`，没加 wayland。

**唯一根治路径**：拿到 / 重编一份 `platforms` 含 `wayland` 的 DDK 用户态（libEGL + WSI）。业界标准做法是 Yocto `meta-img` / `meta-ti-bsp` 的 rogue recipe 用 **PACKAGECONFIG 控制 wayland/x11**——重编时**只动 Mesa-EGL 集成层加 wayland，硬件 umlibs（GLES/CL/Vulkan blob + 固件）不用动**。

**落到 flange（待办）**：先查 `components/platform/allwinnera733` 里 PVR DDK 是怎么进镜像的——
- 若是**预编译二进制**（当前 `xserver-xorg-img-bxm` deb 直下，见 [[project_a7a_gpu_no_hw_gl]]）：只能向 Allwinner(Tina/BSP)/IMG 索要带 wayland WSI 的同版本(24.2@6603887)变体，自己编不了。
- 若有**可控源码/构建**：仿 meta-img 的 PACKAGECONFIG，`platforms` 加 wayland 重编，根治即在仓库内可控。

## 6. 结论与建议

| 目标 | 结论 |
|---|---|
| 验证 GPU 硬件可用 | ✅ `eglinfo`(surfaceless) 或 `glmark2-es2-drm --winsys-options drm-device=/dev/dri/card1` |
| 让 GNOME「设置」能开（短期） | ✅ `GSK_RENDERER=cairo`（软件，够用） |
| GTK4/glmark2 wayland 硬件加速 | ❌ 需重编/换带 wayland WSI 的 DDK（§5） |
| 走 X11 | ❌ 死路，别再试（§3） |
| KDE wayland 是否更优 | ⚠️ 理论上是（Qt raster 默认软件），未实测 |

**建议优先级**：短期用 cairo 保住可用桌面 → 中期评估 KDE wayland（Qt 架构对此平台更友好）→ 根治走 DDK wayland WSI 重编（先确认 DDK 在 flange 是否可控源码构建）。**不要再在 X11 上投入。**

## 附录 A：命令速查

```sh
# 硬件验证（最简，不需 connector）
apt-get install -y mesa-utils
eglinfo | grep -iE 'renderer|vendor|version'        # 期望 PowerVR B-Series BXM-4-64

# 裸 console 硬件 benchmark（需先停掉所有 compositor/DM）
systemctl stop gdm3 sddm
glmark2-es2-drm --winsys-options drm-device=/dev/dri/card1
glmark2-es2-drm --winsys-options drm-device=/dev/dri/card1 -b build -b texture   # 只跑几个场景

# GNOME 设置打不开的临时修复
echo 'GSK_RENDERER=cairo' >> /etc/environment        # 重新登录生效
su - flange -c 'echo $GSK_RENDERER'                  # 验证注入

# 分析 PVR blob（设备无 binutils，用 grep -a）
grep -aoE 'dri2_initialize_[a-z0-9]+' /usr/local/lib/libEGL.so.1 | sort -u
grep -aoE 'pvr_mesa_wsi_create_[a-z]+_surface' /usr/local/lib/libpvr_mesa_wsi.so | sort -u

# DRM 拓扑（确认谁是 render、谁是 display）
ls -l /dev/dri/by-path/
for c in /sys/class/drm/card*-*; do echo -n "$c: "; cat $c/status 2>/dev/null; done
```

## 附录 B：参考链接

- TI Processor SDK — Graphics and Display（Mesa-EGL 内嵌 wayland / powervr.ini 废弃）：https://software-dl.ti.com/processor-sdk-linux/esd/docs/05_02_00_10/linux/Foundational_Components_Graphics.html
- Mesa EGL 文档（`-D platforms=x11,wayland,…`）：https://docs.mesa3d.org/egl.html
- Mesa PowerVR 驱动文档：https://docs.mesa3d.org/drivers/powervr.html
- Yocto/TI — ti-img-rogue-umlibs（window-system-agnostic DDK 组件）：https://patchwork.yoctoproject.org/project/ti/patch/20230119204026.1297616-1-rs@ti.com/mbox/
- Imagination — Open Source GPU Driver：https://developer.imaginationtech.com/solutions/open-source-gpu-driver/
- linux-sunxi.org — PowerVR：https://linux-sunxi.org/PowerVR
