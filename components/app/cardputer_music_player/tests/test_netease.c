#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "netease.h"

static char *read_file(const char *path, size_t *length)
{
    FILE *file = fopen(path, "rb");
    assert(file != NULL);
    assert(fseek(file, 0, SEEK_END) == 0);
    long file_length = ftell(file);
    assert(file_length > 0);
    rewind(file);
    char *buffer = malloc((size_t)file_length + 1U);
    assert(buffer != NULL);
    assert(fread(buffer, 1, (size_t)file_length, file)
           == (size_t)file_length);
    fclose(file);
    buffer[file_length] = '\0';
    *length = (size_t)file_length;
    return buffer;
}

int main(int argc, char **argv)
{
    assert(argc == 2);
    size_t length = 0U;
    char *json = read_file(argv[1], &length);
    track_list_t tracks;
    char error[160] = {0};
    assert(netease_map_playlist(json, length, &tracks,
                                error, sizeof(error)) == 0);
    assert(tracks.count == 2U);
    assert(strcmp(tracks.items[0].id, "347230") == 0);
    assert(strcmp(tracks.items[0].title, "海风信号") == 0);
    assert(strcmp(tracks.items[0].artist, "测试歌手") == 0);
    assert(tracks.items[0].duration_ms == 183000U);
    free(json);

    static const char urls[] =
        "{\"data\":["
        "{\"id\":347230,\"url\":\"http://m1.music.126.net/a.mp3\"},"
        "{\"id\":347231,\"url\":null}],\"code\":200}";
    assert(netease_map_urls(urls, strlen(urls), &tracks,
                            error, sizeof(error)) == 1U);
    assert(strcmp(tracks.items[0].audio_url,
                  "https://m1.music.126.net/a.mp3") == 0);
    assert(tracks.items[1].audio_url[0] == '\0');
    puts("netease provider tests passed");
    return 0;
}
