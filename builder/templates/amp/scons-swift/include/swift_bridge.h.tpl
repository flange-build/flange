#ifndef ${name_upper}_SWIFT_BRIDGE_H
#define ${name_upper}_SWIFT_BRIDGE_H

#include <stdint.h>

uint32_t swift_handle_message(const uint8_t *input,
                              uint32_t input_count,
                              uint8_t *output,
                              uint32_t output_capacity);

#endif /* ${name_upper}_SWIFT_BRIDGE_H */
