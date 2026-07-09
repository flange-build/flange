## 代码编译

### gcc

```shell
export PATH=/PATH/TO/arm-gnu-toolchain-13.2.Rel1-x86_64-arm-none-eabi/bin:$PATH
cd /PATH/TO/bsp/rockchip/common/hal/project/rk2118/GCC
make clean;make -j16;
cd ..
./mkimage.sh
ls -l GCC/TestDemo.elf
-rwxr-xr-x 1 rk rk 323600 Jan 15 09:32 GCC/TestDemo.elf # 这个是调试用的elf文件
ls -l Image/bare.img
-rw-r--r-- 1 rk rk 51232 Jan 15 09:32 Image/bare.img    # 这个就是要烧录的固件，需要配合前级loader
```

### keil

keil工程的创建这里就省略了，只列出需要加入的目录：

```shell
# 源码目录
bsp/rockchip/common/hal/project/rk2118/src
bsp/rockchip/common/hal/lib/CMSIS/Device/RK2118/Source/Templates/GCC
bsp/rockchip/common/hal/lib/CMSIS/Device/RK2118/Source/Templates
bsp/rockchip/common/hal/lib/hal/src
bsp/rockchip/common/hal/lib/hal/src/cru
bsp/rockchip/common/hal/lib/hal/src/pinctrl
bsp/rockchip/common/hal/lib/hal/src/pm
bsp/rockchip/common/hal/lib/bsp/RK2118

# 头文件目录
bsp/rockchip/common/hal/lib/CMSIS/Core/Include
bsp/rockchip/common/hal/lib/CMSIS/Device/RK2118/Include
bsp/rockchip/common/hal/lib/hal/inc
bsp/rockchip/common/hal/lib/bsp/RK2118
```

然后就是要根据`bsp/rockchip/common/hal/project/rk2118/GCC/gcc_arm.ld`写一个keil的链接脚本。

## 烧写

先`Rockchip_Developer_Guide_RK2118_CN.pdf`文档介绍正常烧写一个`Firmeware.img`，再把前面的到`bare.img`烧到`cpu0_os_a`分区，分区的位置可以在`bsp/rockchip/rk2118/board/adsp_demo/setting.ini`找到，例如下面的分区文件截图表明我们需要烧到0x60000这个位置(PartOffset的单位是512，0x300*512=0x60000)：

```shell
[UserPart4]
Name=cpu0_os_a
Type=0x200
PartOffset=0x300
PartSize=0x200
Flag=
File=../../Image/rtt0.img
```

