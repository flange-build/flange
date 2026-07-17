#include <assert.h>
#include <stdio.h>
#include <string.h>

#include "config.h"

static void test_defaults(void)
{
    app_config_t config;
    config_defaults(&config);
    assert(strcmp(config.provider, "netease_official") == 0);
    assert(config.manifest_url[0] == '\0');
    assert(config.netease_api_url[0] == '\0');
    assert(config.netease_playlist_id[0] == '\0');
    assert(config.netease_app_id[0] == '\0');
    assert(config.netease_private_key_file[0] == '\0');
    assert(config.netease_session_file[0] == '/');
    assert(config.fps == 10);
}

static void test_parse(void)
{
    static const char json[] =
        "{\"provider\":\"douyin\","
        "\"douyin_broker_url\":\"https://broker.example/hot\","
        "\"resolver_url\":\"https://resolver.example/audio\","
        "\"visualizer\":\"waveform\",\"fps\":12}";
    app_config_t config;
    char error[160] = {0};
    assert(config_parse(json, strlen(json), &config,
                        error, sizeof(error)) == 0);
    assert(strcmp(config.provider, "douyin") == 0);
    assert(strcmp(config.visualizer, "waveform") == 0);
    assert(config.fps == 12);
}

static void test_secret_rejected(void)
{
    static const char json[] =
        "{\"client_secret\":\"must-not-enter-device\"}";
    app_config_t config;
    char error[160] = {0};
    assert(config_parse(json, strlen(json), &config,
                        error, sizeof(error)) != 0);
    assert(strstr(error, "client_secret") != NULL);

    static const char nested[] =
        "{\"provider_options\":{\"client_secret\":\"also-rejected\"}}";
    assert(config_parse(nested, strlen(nested), &config,
                        error, sizeof(error)) != 0);
}

static void test_insecure_broker_rejected(void)
{
    static const char json[] =
        "{\"douyin_broker_url\":\"http://broker.example/hot\"}";
    app_config_t config;
    char error[160] = {0};
    assert(config_parse(json, strlen(json), &config,
                        error, sizeof(error)) != 0);
}

static void test_netease_config(void)
{
    static const char unconfigured[] =
        "{\"provider\":\"netease\"}";
    static const char valid[] =
        "{\"provider\":\"netease\","
        "\"netease_api_url\":\"https://music-api.example.com\","
        "\"netease_playlist_id\":\"1234567890\"}";
    app_config_t config;
    char error[160] = {0};
    assert(config_parse(unconfigured, strlen(unconfigured), &config,
                        error, sizeof(error)) == 0);
    assert(config_parse(valid, strlen(valid), &config,
                        error, sizeof(error)) == 0);
    assert(strcmp(config.netease_playlist_id, "1234567890") == 0);

    static const char invalid[] =
        "{\"provider\":\"netease\","
        "\"netease_api_url\":\"http://music-api.example.com\","
        "\"netease_playlist_id\":\"not-a-number\"}";
    assert(config_parse(invalid, strlen(invalid), &config,
                        error, sizeof(error)) != 0);
}

static void test_netease_official_config(void)
{
    static const char valid[] =
        "{\"provider\":\"netease_official\","
        "\"netease_app_id\":\"application-id\","
        "\"netease_private_key_file\":\"/run/secrets/ncm.pem\","
        "\"netease_session_file\":\"/var/lib/player/session.json\"}";
    static const char invalid[] =
        "{\"netease_private_key_file\":\"relative.pem\"}";
    app_config_t config;
    char error[160] = {0};

    assert(config_parse(valid, strlen(valid), &config,
                        error, sizeof(error)) == 0);
    assert(strcmp(config.netease_app_id, "application-id") == 0);
    assert(config_parse(invalid, strlen(invalid), &config,
                        error, sizeof(error)) != 0);
}

int main(void)
{
    test_defaults();
    test_parse();
    test_secret_rejected();
    test_insecure_broker_rejected();
    test_netease_config();
    test_netease_official_config();
    puts("config tests passed");
    return 0;
}
