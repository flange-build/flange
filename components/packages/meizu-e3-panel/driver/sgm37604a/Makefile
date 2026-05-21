# sgm37604a SGM37604A I2C 背光驱动 —— out-of-tree 内核模块
#
# 由 flange OOT 模块流水线以
#   make KSRC=<内核源> M=<本目录> ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu-
# 调用。该驱动主体由 CONFIG_BACKLIGHT_SGM37604 宏开关包裹，OOT 编译需显式定义。
#
# 注意：rock5b 背光走板载 MP3302 + 内核内建 pwm-backlight，不使用本驱动；
# 本驱动随 meizu-e3-panel 包保留，供使用 SGM37604A I2C 背光芯片的载板按需启用。

obj-m += sgm37604a.o

# 不定义 CONFIG_BACKLIGHT_SGM37604：该宏仅包裹一个 vendor 私有头 "sgm37604a.h"
# （参考件未提供，且 .c 中所有类型/寄存器/函数均已内联定义）与两个未被调用的
# bled_enable/disable 死函数。驱动主体（i2c probe + backlight_ops）在宏外，
# 不定义即可干净编译出功能完整的 .ko。
ccflags-y += -Wno-error

KSRC ?= /lib/modules/$(shell uname -r)/build
M    ?= $(CURDIR)

all:
	$(MAKE) -C $(KSRC) M=$(M) modules

clean:
	$(MAKE) -C $(KSRC) M=$(M) clean
