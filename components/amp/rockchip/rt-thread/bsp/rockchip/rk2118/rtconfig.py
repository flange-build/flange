import os

def check_define_in_file(file_path, define_string):
    try:
        with open(file_path, 'r') as file:
            for line in file:
                if line.strip() == define_string:
                    return True
        return False
    except FileNotFoundError:
        return False
    except Exception as e:
        return False

# toolchains options
ARCH='arm'
CPU='cortex-m33'
CROSS_TOOL='gcc'

if os.getenv('RTT_CC'):
    CROSS_TOOL = os.getenv('RTT_CC')

# cross_tool provides the cross compiler
# EXEC_PATH is the compiler execute path, for example, CodeSourcery, Keil MDK, IAR
if  CROSS_TOOL == 'gcc':
    PLATFORM = 'gcc'
    EXEC_PATH = '/usr/bin'
    #EXEC_PATH = '/opt/gcc-arm-none-eabi-7-2018-q2-update/bin'
elif CROSS_TOOL == 'keil':
    PLATFORM = 'armcc'
    EXEC_PATH = 'C:/Keil'
elif CROSS_TOOL == 'iar':
    print('================ERROR============================')
    print('Not support iar yet!')
    print('=================================================')
    exit(0)

if os.getenv('RTT_EXEC_PATH'):
    EXEC_PATH = os.getenv('RTT_EXEC_PATH')

#BUILD = 'debug'
BUILD = 'release'

if PLATFORM == 'gcc':
    # toolchains
    PREFIX = 'arm-none-eabi-'
    CC = PREFIX + 'gcc'
    AS = PREFIX + 'gcc'
    AR = PREFIX + 'ar'
    CXX = PREFIX + 'g++'
    LINK = PREFIX + 'gcc'
    TARGET_EXT = 'elf'
    SIZE = PREFIX + 'size'
    OBJDUMP = PREFIX + 'objdump'
    OBJCPY = PREFIX + 'objcopy'
    STRIP = PREFIX + 'strip'

    DEVICE = ' -mcpu=cortex-m33 -mthumb -mfpu=fpv5-sp-d16 -mfloat-abi=hard -ffunction-sections -fdata-sections'
    CFLAGS = DEVICE + ' -g -Wall -Werror -D__RT_THREAD__ '
    AFLAGS = ' -c' + DEVICE + ' -x assembler-with-cpp -Wa,-mimplicit-it=thumb -D__ASSEMBLY__ '
    LFLAGS = DEVICE + ' -lm -lgcc -lc' + ' -specs=nano.specs -specs=nosys.specs -nostartfiles -Wl,--gc-sections,-Map=rtthread.map,-cref,-u,Reset_Handler '

    CPATH = ''
    LPATH = ''

    LINK_SCRIPT = 'gcc_xip_on.ld'

    if check_define_in_file('rtconfig.h', '#define CPU_RUN_IN_XIP'):
        LINK_SCRIPT = 'gcc_xip_on.ld'

    if check_define_in_file('rtconfig.h', '#define CPU_RUN_IN_SRAM'):
        LINK_SCRIPT = 'gcc_xip_off_sram.ld'

    if check_define_in_file('rtconfig.h', '#define CPU_RUN_IN_DDR'):
        LINK_SCRIPT = 'gcc_xip_off_ddr.ld'

    LFLAGS += '-T %s' % LINK_SCRIPT

    if BUILD == 'debug':
        CFLAGS += ' -O0 -gdwarf-2'
        AFLAGS += ' -gdwarf-2'
    else:
        CFLAGS += ' -Os'
    CXXFLAGS = CFLAGS

    POST_ACTION = OBJCPY + ' -O binary $TARGET rtthread.bin\n' + SIZE + ' $TARGET \n'
    POST_ACTION += './align_bin_size.sh rtthread.bin;./rename_rtt.py\n'

    M_CFLAGS = CFLAGS + ' -mlong-calls  -Dsourcerygxx -fPIC '
    M_LFLAGS = DEVICE + ' -Wl,--gc-sections,-z,max-page-size=0x4 -shared -fPIC -e main -nostartfiles -nostdlib -static-libgcc'
    M_POST_ACTION = STRIP + ' -R .hash $TARGET\n' + SIZE + ' $TARGET \n'

