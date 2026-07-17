#include <assert.h>
#include <stdio.h>
#include <string.h>

#include "manifest.h"

static void test_authorized_qishui_track(void)
{
    static const char json[] =
        "{\"tracks\":[{"
        "\"id\":\"qishui-1\","
        "\"source\":\"qishui\","
        "\"rank\":1,"
        "\"title\":\"\\u591c\\u822a\","
        "\"artist\":\"Luma Vale\","
        "\"duration_ms\":180000,"
        "\"audio_url\":\"https://media.example/audio.mp3\","
        "\"share_url\":\"https://qishui.douyin.com/example\""
        "}]}";
    track_list_t tracks;
    char error[160] = {0};
    assert(manifest_parse(json, strlen(json), &tracks,
                          error, sizeof(error)) == 0);
    assert(tracks.count == 1);
    assert(strcmp(tracks.items[0].source, "qishui") == 0);
    assert(strcmp(tracks.items[0].title, "夜航") == 0);
    assert(tracks.items[0].rank == 1);
    assert(tracks.items[0].duration_ms == 180000);
    assert(track_audio_url_is_allowed(tracks.items[0].audio_url));
}

static void test_metadata_only_track(void)
{
    static const char json[] =
        "{\"tracks\":[{"
        "\"id\":\"douyin-1\","
        "\"source\":\"douyin\","
        "\"title\":\"榜单曲目\","
        "\"artist\":\"作者\","
        "\"share_url\":\"https://www.douyin.com/music/example\""
        "}]}";
    track_list_t tracks;
    char error[160] = {0};
    assert(manifest_parse(json, strlen(json), &tracks,
                          error, sizeof(error)) == 0);
    assert(tracks.count == 1);
    assert(tracks.items[0].audio_url[0] == '\0');
}

static void test_share_page_rejected_as_audio(void)
{
    static const char json[] =
        "{\"tracks\":[{"
        "\"source\":\"qishui\","
        "\"title\":\"错误地址\","
        "\"artist\":\"作者\","
        "\"audio_url\":\"http://qishui.douyin.com/share\""
        "}]}";
    track_list_t tracks;
    char error[160] = {0};
    assert(manifest_parse(json, strlen(json), &tracks,
                          error, sizeof(error)) != 0);
}

static void test_empty_tracks_rejected(void)
{
    static const char json[] = "{\"tracks\":[]}";
    track_list_t tracks;
    char error[160] = {0};
    assert(manifest_parse(json, strlen(json), &tracks,
                          error, sizeof(error)) != 0);
}

int main(void)
{
    test_authorized_qishui_track();
    test_metadata_only_track();
    test_share_page_rejected_as_audio();
    test_empty_tracks_rejected();
    puts("manifest tests passed");
    return 0;
}
