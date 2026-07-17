#include "track.h"

#include <string.h>

int track_audio_url_is_allowed(const char *url)
{
    if (url == NULL || url[0] == '\0')
        return 0;
    return strncmp(url, "https://", 8) == 0
        || strncmp(url, "file://", 7) == 0;
}
