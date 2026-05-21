# sec_ts 三星 SEC 触摸驱动 —— out-of-tree 内核模块
#
# 由 flange OOT 模块流水线以
#   make KSRC=<内核源> M=<本目录> ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu-
# 调用；亦可在本目录直接 make（KSRC 默认指向当前运行内核 build 链接）。
#
# 固件 s6d6ft0_v1.10_20170918.i 由 sec_ts_fw.c 直接 #include 编入 .ko，
# 不依赖 /lib/firmware 部署。

obj-m += sec_ts.o
sec_ts-objs := sec_ts_main.o sec_ts_fw.o sec_ts_fn.o sec_ts_selftest.o

ccflags-y += -DCONFIG_TOUCHSCREEN_SEC_TS_1223

# vendor 驱动源带 VLA / unused-label / unused-function / unused-variable 等
# 警告（部分 #ifdef 路径关闭导致），内核 -Werror 会拦截。OOT vendor 驱动不改
# 上游源，统一放宽为「警告不致命」。
ccflags-y += -Wno-error

KSRC ?= /lib/modules/$(shell uname -r)/build
M    ?= $(CURDIR)

all:
	$(MAKE) -C $(KSRC) M=$(M) modules

clean:
	$(MAKE) -C $(KSRC) M=$(M) clean
