# panel_meizu_e3 魅族 E3 MIPI-DSI panel 驱动 —— out-of-tree 内核模块
#
# 由 flange OOT 模块流水线以
#   make KSRC=<内核源> M=<本目录> ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu-
# 调用。
#
# 设计目标：mainline drm_panel 风格的最小专用 panel 驱动，供没有通用
# DSI panel driver 的 mainline drm 栈（典型如 QCS6490 QCLINUX BSP 的
# drm/msm）消费。rock5b（Rockchip BSP simple-panel-dsi）与 a7a
# （Allwinner BSP allwinner,panel-dsi）走各自 vendor 通用驱动，本驱动
# 在那两板上编出但因 DT 不引用 `meizu,e3-panel` compatible 而不加载。

obj-m += panel_meizu_e3.o

ccflags-y += -Wno-error

KSRC ?= /lib/modules/$(shell uname -r)/build
M    ?= $(CURDIR)

all:
	$(MAKE) -C $(KSRC) M=$(M) modules

clean:
	$(MAKE) -C $(KSRC) M=$(M) clean
