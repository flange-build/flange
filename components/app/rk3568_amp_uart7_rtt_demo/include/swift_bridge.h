#ifndef RK3568_AMP_UART7_RTT_DEMO_SWIFT_BRIDGE_H
#define RK3568_AMP_UART7_RTT_DEMO_SWIFT_BRIDGE_H

#include <stdint.h>

uint32_t swift_handle_message(const uint8_t *input,
                              uint32_t input_count,
                              uint8_t *output,
                              uint32_t output_capacity);

int32_t swift_i2c_command(int32_t argc, char **argv);

#endif /* RK3568_AMP_UART7_RTT_DEMO_SWIFT_BRIDGE_H */
