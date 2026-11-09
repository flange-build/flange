# BE200 蓝牙（Gale Peak 2，USB 8087:0036）—— 以目标内核自带的 btusb/btintel
# 为底，补上设备 ID 与 hw_variant 0x1c 后作 OOT 模块编译，装入 updates/ 覆盖
# 内核树内同名模块。
#
# 由 flange OOT 模块流水线以
#   make KSRC=<内核源> M=<本目录> ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu-
# 调用。源码每次从 KSRC 重新拷贝，补丁幂等；已原生支持 0036 的内核不打补丁。
#
# 对内核的要求（config.jsonnet 声明，这里构建前校验）：BT_HCIBTUSB 与 BT_INTEL
# 必须为模块——内建版本会先于 updates/ 绑定设备，且 btintel 符号重复无法加载。

ifneq ($(KERNELRELEASE),)
obj-m += btusb.o btintel.o
else

KSRC ?= /lib/modules/$(shell uname -r)/build
M    ?= $(CURDIR)

BT_SRC := $(KSRC)/drivers/bluetooth
PATCH  := $(M)/0001-bluetooth-support-intel-gale-peak-8087-0036.patch

all: bt-sources
	$(MAKE) -C $(KSRC) M=$(M) modules

bt-sources:
	@for sym in BT_HCIBTUSB BT_INTEL; do \
		if ! grep -q "^CONFIG_$${sym}=m" $(KSRC)/.config; then \
			echo "错误：intel-be200 要求内核 CONFIG_$${sym}=m" >&2; exit 1; \
		fi; \
	done
	cp $(BT_SRC)/btusb.c $(BT_SRC)/btintel.c $(BT_SRC)/*.h $(M)/
	grep -q "USB_DEVICE(0x8087, 0x0036)" $(M)/btusb.c || patch -d $(M) -p3 < $(PATCH)

clean:
	$(MAKE) -C $(KSRC) M=$(M) clean
	rm -f $(M)/btusb.c $(M)/btintel.c $(M)/*.h

.PHONY: all bt-sources clean
endif
