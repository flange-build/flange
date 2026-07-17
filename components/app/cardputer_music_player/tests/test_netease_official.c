#define _POSIX_C_SOURCE 200809L

#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

#include "config.h"
#include "netease_official.h"

static void test_qr_response(void)
{
    static const unsigned char json[] =
        "{\"code\":200,\"data\":{\"qrCodeUrl\":"
        "\"https://music.163.com/login?code=fixture\","
        "\"uniKey\":\"fixture-key\"}}";
    netease_official_session_t session = {0};
    char error[160] = {0};

    assert(netease_official_parse_qr_response(
               json, sizeof(json) - 1U, &session,
               error, sizeof(error)) == 0);
    assert(strcmp(session.qr_url,
                  "https://music.163.com/login?code=fixture") == 0);
    assert(strcmp(session.uni_key, "fixture-key") == 0);
}

static void test_client_ip_responses(void)
{
    static const unsigned char json[] = "{\"ip\":\"203.0.113.8\"}";
    static const unsigned char text[] = "\n203.0.113.9\r\n";
    static const unsigned char invalid[] = "not-an-ip";
    char output[64] = {0};

    assert(netease_official_parse_client_ip(
               json, sizeof(json) - 1U, output, sizeof(output)) == 0);
    assert(strcmp(output, "203.0.113.8") == 0);
    assert(netease_official_parse_client_ip(
               text, sizeof(text) - 1U, output, sizeof(output)) == 0);
    assert(strcmp(output, "203.0.113.9") == 0);
    assert(netease_official_parse_client_ip(
               invalid, sizeof(invalid) - 1U,
               output, sizeof(output)) != 0);
}

static void test_poll_responses(void)
{
    static const unsigned char waiting[] =
        "{\"code\":200,\"data\":{\"status\":801}}";
    static const unsigned char success[] =
        "{\"code\":200,\"data\":{\"status\":803,\"accessToken\":{"
        "\"accessToken\":\"access-fixture\","
        "\"refreshToken\":\"refresh-fixture\","
        "\"expireTime\":604800}}}";
    netease_official_session_t session = {0};
    netease_qr_status_t status = NETEASE_QR_UNKNOWN;
    char error[160] = {0};

    assert(netease_official_parse_poll_response(
               waiting, sizeof(waiting) - 1U, &session, &status,
               error, sizeof(error)) == 0);
    assert(status == NETEASE_QR_WAITING);
    assert(netease_official_parse_poll_response(
               success, sizeof(success) - 1U, &session, &status,
               error, sizeof(error)) == 0);
    assert(status == NETEASE_QR_SUCCESS);
    assert(strcmp(session.access_token, "access-fixture") == 0);
    assert(strcmp(session.refresh_token, "refresh-fixture") == 0);
    assert(session.expire_at > (int64_t)time(NULL));
}

static void test_session_file(void)
{
    app_config_t config;
    config_defaults(&config);
    char path[] = "/tmp/cardputer-netease-session.XXXXXX";
    int fd = mkstemp(path);
    assert(fd >= 0);
    close(fd);
    unlink(path);
    snprintf(config.netease_session_file,
             sizeof(config.netease_session_file), "%s", path);

    netease_official_session_t written = {0};
    snprintf(written.access_token, sizeof(written.access_token),
             "saved-access");
    snprintf(written.refresh_token, sizeof(written.refresh_token),
             "saved-refresh");
    written.expire_at = (int64_t)time(NULL) + 3600;
    char error[160] = {0};
    assert(netease_official_save_session(
               &config, &written, error, sizeof(error)) == 0);

    struct stat info;
    assert(stat(path, &info) == 0);
    assert((info.st_mode & 0777) == 0600);
    netease_official_session_t loaded = {0};
    assert(netease_official_load_session(
               &config, &loaded, error, sizeof(error)) == 0);
    assert(strcmp(loaded.access_token, "saved-access") == 0);
    assert(strcmp(loaded.refresh_token, "saved-refresh") == 0);

    assert(chmod(path, 0644) == 0);
    memset(&loaded, 0, sizeof(loaded));
    assert(netease_official_load_session(
               &config, &loaded, error, sizeof(error)) == -1);
    assert(strstr(error, "0600") != NULL);
    unlink(path);
}

static unsigned char *read_fixture(const char *path, size_t *size)
{
    FILE *file = fopen(path, "rb");
    assert(file != NULL);
    assert(fseek(file, 0L, SEEK_END) == 0);
    long length = ftell(file);
    assert(length > 0);
    rewind(file);
    unsigned char *data = malloc((size_t)length + 1U);
    assert(data != NULL);
    assert(fread(data, 1U, (size_t)length, file) == (size_t)length);
    assert(fclose(file) == 0);
    data[length] = '\0';
    *size = (size_t)length;
    return data;
}

static void test_online_track_mapping(const char *recommendations_path,
                                      const char *play_urls_path)
{
    size_t recommendations_size = 0U;
    size_t play_urls_size = 0U;
    unsigned char *recommendations = read_fixture(
        recommendations_path, &recommendations_size
    );
    unsigned char *play_urls = read_fixture(
        play_urls_path, &play_urls_size
    );
    track_list_t tracks = {0};
    char error[160] = {0};

    assert(netease_official_map_recommendations(
               recommendations, recommendations_size, &tracks,
               error, sizeof(error)) == 0);
    assert(tracks.count == 2U);
    assert(strcmp(tracks.items[0].id, "1001") == 0);
    assert(strcmp(tracks.items[0].title, "在线歌曲一") == 0);
    assert(strcmp(tracks.items[0].artist, "歌手甲") == 0);
    assert(strcmp(tracks.items[0].cover_url,
                  "https://p1.music.126.net/cover-one.jpg"
                  "?param=256y256") == 0);
    assert(tracks.items[0].audio_url[0] == '\0');
    assert(tracks.items[0].audio_resolved == 0);

    assert(netease_official_map_play_urls(
               play_urls, play_urls_size, &tracks,
               error, sizeof(error)) == 1U);
    assert(error[0] == '\0');
    assert(strcmp(tracks.items[0].audio_url,
                  "https://m801.music.126.net/audio-one.mp3") == 0);
    assert(tracks.items[0].audio_resolved == 1);
    assert(tracks.items[1].audio_url[0] == '\0');
    assert(tracks.items[1].audio_resolved == 0);

    static const unsigned char single_url[] =
        "{\"code\":200,\"subCode\":\"200\",\"data\":{"
        "\"url\":\"http://iot202.music.126.net/audio-two.mp3\","
        "\"br\":128000}}";
    assert(netease_official_map_single_play_url(
               single_url, sizeof(single_url) - 1U, &tracks.items[1],
               error, sizeof(error)) == 1);
    assert(strcmp(tracks.items[1].audio_url,
                  "https://iot202.music.126.net/audio-two.mp3") == 0);

    static const unsigned char unavailable[] =
        "{\"code\":200,\"subCode\":\"10003\","
        "\"data\":{\"url\":null}}";
    assert(netease_official_map_single_play_url(
               unavailable, sizeof(unavailable) - 1U, &tracks.items[1],
               error, sizeof(error)) == 0);
    assert(error[0] == '\0');
    assert(tracks.items[1].audio_resolved == 1);

    static const unsigned char detail_url[] =
        "{\"code\":200,\"subCode\":\"200\",\"data\":{"
        "\"playUrl\":\"http://m802.music.126.net/detail-two.mp3\","
        "\"br\":128000}}";
    assert(netease_official_map_song_detail_url(
               detail_url, sizeof(detail_url) - 1U, &tracks.items[1],
               error, sizeof(error)) == 1);
    assert(strcmp(tracks.items[1].audio_url,
                  "https://m802.music.126.net/detail-two.mp3") == 0);

    free(play_urls);
    free(recommendations);
}

int main(int argc, char **argv)
{
    assert(argc == 3);
    test_client_ip_responses();
    test_qr_response();
    test_poll_responses();
    test_session_file();
    test_online_track_mapping(argv[1], argv[2]);
    puts("网易云官方登录与在线曲目协议测试通过");
    return 0;
}
