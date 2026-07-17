#include <assert.h>
#include <stdio.h>
#include <string.h>

#include "device_match.h"

int main(void)
{
    assert(device_match_gud_framebuffer("guddrmfb"));
    assert(!device_match_gud_framebuffer("rockchipdrmfb"));
    assert(device_match_cardputer_input("Cardputer GUD Display", 1));
    assert(!device_match_cardputer_input("Cardputer GUD Display", 0));
    assert(device_match_cardputer_pcm(
        "sysdefault:CARD=Display",
        "Cardputer GUD Display, USB Audio", "Output"));
    assert(!device_match_cardputer_pcm(
        "sysdefault:CARD=Display",
        "Cardputer GUD Display, USB Audio", "Input"));
    char device[96];
    assert(device_make_plughw("hw:CARD=Display,DEV=3",
                              device, sizeof(device)) == 0);
    assert(strcmp(device, "plughw:CARD=Display,DEV=3") == 0);
    assert(device_make_plughw("default", device, sizeof(device)) != 0);
    puts("device match tests passed");
    return 0;
}
