#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "provider.h"

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

static void test_official_mapping(const char *fixture)
{
    size_t length = 0;
    char *json = read_file(fixture, &length);
    track_list_t tracks;
    char error[160] = {0};
    assert(provider_map_douyin(json, length, &tracks,
                               error, sizeof(error)) == 0);
    assert(tracks.count == 2);
    assert(strcmp(tracks.items[0].source, "douyin") == 0);
    assert(strcmp(tracks.items[0].title, "夏夜信号") == 0);
    assert(strcmp(tracks.items[1].artist, "榜单作者") == 0);
    assert(tracks.items[0].duration_ms == 183000);
    assert(tracks.items[0].audio_url[0] == '\0');
    free(json);
}

static void test_normalized_broker(void)
{
    static const char json[] =
        "{\"tracks\":[{\"source\":\"douyin\","
        "\"title\":\"Broker 曲目\",\"artist\":\"作者\","
        "\"share_url\":\"https://www.douyin.com/music/1\"}]}";
    track_list_t tracks;
    char error[160] = {0};
    assert(provider_map_douyin(json, strlen(json), &tracks,
                               error, sizeof(error)) == 0);
    assert(tracks.count == 1);
    assert(tracks.items[0].audio_url[0] == '\0');
}

static void test_resolver_merge(void)
{
    track_list_t tracks = {0};
    tracks.count = 2;
    snprintf(tracks.items[0].id, sizeof(tracks.items[0].id), "music-1");
    snprintf(tracks.items[1].share_url,
             sizeof(tracks.items[1].share_url),
             "https://www.douyin.com/music/2");
    track_list_t resolutions = {0};
    resolutions.count = 2;
    snprintf(resolutions.items[0].id,
             sizeof(resolutions.items[0].id), "music-1");
    snprintf(resolutions.items[0].audio_url,
             sizeof(resolutions.items[0].audio_url),
             "https://media.example/1.mp3");
    snprintf(resolutions.items[1].share_url,
             sizeof(resolutions.items[1].share_url),
             "https://www.douyin.com/music/2");
    snprintf(resolutions.items[1].audio_url,
             sizeof(resolutions.items[1].audio_url),
             "file:///var/lib/cardputer_music_player/2.wav");
    assert(provider_merge_resolutions(&tracks, &resolutions) == 2);
    assert(strcmp(tracks.items[0].audio_url,
                  "https://media.example/1.mp3") == 0);
    assert(strcmp(tracks.items[1].audio_url,
                  "file:///var/lib/cardputer_music_player/2.wav") == 0);
}

int main(int argc, char **argv)
{
    assert(argc == 2);
    test_official_mapping(argv[1]);
    test_normalized_broker();
    test_resolver_merge();
    puts("provider tests passed");
    return 0;
}
