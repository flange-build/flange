#include <rtthread.h>

#include "swift_bridge.h"

static int swift_i2c(int argc, char **argv)
{
    return swift_i2c_command(argc, argv);
}
MSH_CMD_EXPORT(swift_i2c, Swift I2C transfer command);
