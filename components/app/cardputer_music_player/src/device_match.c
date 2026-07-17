#include "device_match.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

int device_match_gud_framebuffer(const char *name)
{
    return name != NULL && strstr(name, "guddrmfb") != NULL;
}

int device_match_cardputer_input(const char *name, int supports_ev_key)
{
    return supports_ev_key && name != NULL
        && strstr(name, "Cardputer GUD Display") != NULL;
}

int device_match_cardputer_pcm(const char *name, const char *description,
                               const char *io_id)
{
    int is_output = io_id == NULL || strcmp(io_id, "Output") == 0;
    if (!is_output)
        return 0;
    return (name != NULL && strstr(name, "CARD=Display") != NULL)
        || (description != NULL
            && strstr(description, "Cardputer GUD Display") != NULL);
}

int device_make_plughw(const char *hint_name, char *device, size_t size)
{
    if (hint_name == NULL || device == NULL || size == 0U)
        return -1;
    const char *card = strstr(hint_name, "CARD=");
    if (card == NULL)
        return -1;
    card += strlen("CARD=");

    char card_id[48];
    size_t card_len = strcspn(card, ", ");
    if (card_len == 0U || card_len >= sizeof(card_id))
        return -1;
    memcpy(card_id, card, card_len);
    card_id[card_len] = '\0';

    unsigned device_index = 0;
    const char *dev = strstr(card + card_len, "DEV=");
    if (dev != NULL) {
        char *end = NULL;
        unsigned long parsed = strtoul(dev + strlen("DEV="), &end, 10);
        if (end != dev + strlen("DEV=") && parsed <= 255U)
            device_index = (unsigned)parsed;
    }
    int written = snprintf(device, size, "plughw:CARD=%s,DEV=%u",
                           card_id, device_index);
    return written > 0 && (size_t)written < size ? 0 : -1;
}
