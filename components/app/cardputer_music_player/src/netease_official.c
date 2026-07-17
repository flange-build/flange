#define _POSIX_C_SOURCE 200809L

#define JSMN_STATIC
#define JSMN_STRICT
#include "jsmn.h"

#include "netease_official.h"

#include <arpa/inet.h>
#include <ctype.h>
#include <errno.h>
#include <fcntl.h>
#include <openssl/evp.h>
#include <openssl/pem.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

#include "http.h"

#define NETEASE_API_BASE "https://openncm.music.163.com"
#define NETEASE_RESPONSE_MAX (256U * 1024U)
#define NETEASE_REQUEST_SIZE 16384U
#define NETEASE_JSON_TOKENS 8192
#define NETEASE_STARTUP_RESOLVE_LIMIT 8U
#define NETEASE_API_CONNECT_TIMEOUT_MS 2500L
#define NETEASE_API_TIMEOUT_MS 6000L
#define NETEASE_IP_CONNECT_TIMEOUT_MS 1500L
#define NETEASE_IP_TIMEOUT_MS 2500L

typedef struct {
    const char *key;
    const char *value;
} sign_param_t;

static char cached_client_ip[64];

static int64_t epoch_seconds(void)
{
    return (int64_t)time(NULL);
}

static int64_t epoch_milliseconds(void)
{
    struct timespec value;
    if (clock_gettime(CLOCK_REALTIME, &value) != 0)
        return 0;
    return (int64_t)value.tv_sec * 1000 + value.tv_nsec / 1000000;
}

static int token_equals(const char *json, const jsmntok_t *token,
                        const char *value)
{
    size_t length = (size_t)(token->end - token->start);
    return token->type == JSMN_STRING && strlen(value) == length
        && strncmp(json + token->start, value, length) == 0;
}

static int token_skip(const jsmntok_t *tokens, int count, int index)
{
    if (index < 0 || index >= count)
        return count;
    int end = tokens[index].end;
    index++;
    while (index < count && tokens[index].start < end)
        index++;
    return index;
}

static int object_value(const char *json, const jsmntok_t *tokens,
                        int count, int object, const char *key)
{
    if (object < 0 || object >= count
            || tokens[object].type != JSMN_OBJECT)
        return -1;
    int cursor = object + 1;
    while (cursor + 1 < count
            && tokens[cursor].start < tokens[object].end) {
        int value = cursor + 1;
        if (token_equals(json, &tokens[cursor], key))
            return value;
        cursor = token_skip(tokens, count, value);
    }
    return -1;
}

static int copy_token(const char *json, const jsmntok_t *token,
                      char *output, size_t size)
{
    if (token == NULL || token->type != JSMN_STRING || size == 0U)
        return -1;
    size_t length = (size_t)(token->end - token->start);
    if (length >= size)
        return -1;
    memcpy(output, json + token->start, length);
    output[length] = '\0';
    return 0;
}

static int copy_json_string(const char *json, const jsmntok_t *token,
                            char *output, size_t size)
{
    if (token == NULL || token->type != JSMN_STRING || size == 0U)
        return -1;
    size_t used = 0U;
    for (int i = token->start; i < token->end; i++) {
        char value = json[i];
        if (value == '\\') {
            i++;
            if (i >= token->end)
                return -1;
            switch (json[i]) {
            case '"': value = '"'; break;
            case '\\': value = '\\'; break;
            case '/': value = '/'; break;
            case 'b': value = '\b'; break;
            case 'f': value = '\f'; break;
            case 'n': value = '\n'; break;
            case 'r': value = '\r'; break;
            case 't': value = '\t'; break;
            default: return -1;
            }
        }
        if (used + 1U >= size)
            return -1;
        output[used++] = value;
    }
    output[used] = '\0';
    return 0;
}

static int copy_scalar_string(const char *json, const jsmntok_t *token,
                              char *output, size_t size)
{
    if (token == NULL || size == 0U)
        return -1;
    if (token->type == JSMN_STRING)
        return copy_json_string(json, token, output, size);
    if (token->type != JSMN_PRIMITIVE)
        return -1;
    size_t length = (size_t)(token->end - token->start);
    if (length == 0U || length >= size)
        return -1;
    for (size_t i = 0U; i < length; i++) {
        unsigned char value =
            (unsigned char)json[token->start + (int)i];
        if (!isalnum(value) && value != '-' && value != '_')
            return -1;
    }
    memcpy(output, json + token->start, length);
    output[length] = '\0';
    return 0;
}

static int parse_json(const unsigned char *data, size_t size,
                      jsmntok_t tokens[NETEASE_JSON_TOKENS],
                      char *error, size_t error_size)
{
    jsmn_parser parser;
    jsmn_init(&parser);
    int count = jsmn_parse(&parser, (const char *)data, size,
                           tokens, NETEASE_JSON_TOKENS);
    if (count < 1 || tokens[0].type != JSMN_OBJECT) {
        snprintf(error, error_size, "网易云响应 JSON 无效");
        return -1;
    }
    return count;
}

static int parse_primitive_i64(const char *json, const jsmntok_t *token,
                               int64_t *output)
{
    if (token == NULL || token->type != JSMN_PRIMITIVE)
        return -1;
    size_t length = (size_t)(token->end - token->start);
    if (length == 0U || length >= 32U)
        return -1;
    char buffer[32];
    memcpy(buffer, json + token->start, length);
    buffer[length] = '\0';
    char *end = NULL;
    errno = 0;
    long long value = strtoll(buffer, &end, 10);
    if (errno != 0 || end == buffer || *end != '\0')
        return -1;
    *output = value;
    return 0;
}

static int parse_api_code(const char *json, const jsmntok_t *tokens,
                          int count, char *error, size_t error_size)
{
    int code_token = object_value(json, tokens, count, 0, "code");
    int64_t code = 0;
    if (code_token < 0
            || parse_primitive_i64(json, &tokens[code_token], &code) != 0) {
        snprintf(error, error_size, "网易云响应缺少 code");
        return -1;
    }
    if (code == 200)
        return 0;
    int message = object_value(json, tokens, count, 0, "message");
    char detail[96] = {0};
    if (message >= 0 && tokens[message].type == JSMN_STRING)
        (void)copy_token(json, &tokens[message], detail, sizeof(detail));
    snprintf(error, error_size, "网易云 API 错误 %lld%s%s",
             (long long)code, detail[0] == '\0' ? "" : ": ", detail);
    return -1;
}

static int compare_params(const void *left, const void *right)
{
    const sign_param_t *a = left;
    const sign_param_t *b = right;
    return strcmp(a->key, b->key);
}

static int build_sign_content(const sign_param_t *input, size_t count,
                              char *output, size_t size)
{
    if (count == 0U || count > 8U)
        return -1;
    sign_param_t params[8];
    memcpy(params, input, count * sizeof(params[0]));
    qsort(params, count, sizeof(params[0]), compare_params);
    size_t used = 0U;
    for (size_t i = 0U; i < count; i++) {
        if (params[i].value == NULL || params[i].value[0] == '\0')
            continue;
        int written = snprintf(output + used, size - used,
                               "%s%s=%s", used == 0U ? "" : "&",
                               params[i].key, params[i].value);
        if (written < 0 || (size_t)written >= size - used)
            return -1;
        used += (size_t)written;
    }
    return used == 0U ? -1 : 0;
}

static int rsa_sha256_sign(const char *private_key_file,
                           const char *content,
                           char *signature, size_t signature_size,
                           char *error, size_t error_size)
{
    FILE *file = fopen(private_key_file, "rb");
    if (file == NULL) {
        snprintf(error, error_size, "无法读取网易云 Private Key");
        return -1;
    }
    EVP_PKEY *key = PEM_read_PrivateKey(file, NULL, NULL, NULL);
    fclose(file);
    if (key == NULL) {
        snprintf(error, error_size, "网易云 Private Key 不是有效 PEM");
        return -1;
    }
    EVP_MD_CTX *context = EVP_MD_CTX_new();
    size_t signed_size = 0U;
    int result = -1;
    unsigned char *signed_data = NULL;
    if (context == NULL
            || EVP_DigestSignInit(context, NULL, EVP_sha256(), NULL, key) <= 0
            || EVP_DigestSignUpdate(context, content, strlen(content)) <= 0
            || EVP_DigestSignFinal(context, NULL, &signed_size) <= 0)
        goto cleanup;
    signed_data = malloc(signed_size);
    if (signed_data == NULL
            || EVP_DigestSignFinal(context, signed_data, &signed_size) <= 0)
        goto cleanup;
    size_t encoded_size = 4U * ((signed_size + 2U) / 3U) + 1U;
    if (encoded_size > signature_size)
        goto cleanup;
    int encoded = EVP_EncodeBlock((unsigned char *)signature,
                                  signed_data, (int)signed_size);
    if (encoded <= 0 || (size_t)encoded + 1U > signature_size)
        goto cleanup;
    signature[encoded] = '\0';
    result = 0;

cleanup:
    if (result != 0)
        snprintf(error, error_size, "网易云 RSA-SHA256 签名失败");
    if (signed_data != NULL) {
        memset(signed_data, 0, signed_size);
        free(signed_data);
    }
    EVP_MD_CTX_free(context);
    EVP_PKEY_free(key);
    return result;
}

static int sign_request(const app_config_t *config,
                        const sign_param_t *params, size_t count,
                        char *signature, size_t signature_size,
                        char *error, size_t error_size)
{
    char content[NETEASE_REQUEST_SIZE];
    if (build_sign_content(params, count, content, sizeof(content)) != 0) {
        snprintf(error, error_size, "网易云签名参数过长");
        return -1;
    }
    int result = rsa_sha256_sign(config->netease_private_key_file,
                                 content, signature, signature_size,
                                 error, error_size);
    memset(content, 0, sizeof(content));
    return result;
}

static int json_escape(const char *input, char *output, size_t size)
{
    size_t used = 0U;
    for (const unsigned char *cursor = (const unsigned char *)input;
         *cursor != '\0'; cursor++) {
        const char *escaped = NULL;
        if (*cursor == '"')
            escaped = "\\\"";
        else if (*cursor == '\\')
            escaped = "\\\\";
        if (escaped != NULL) {
            if (used + 2U >= size)
                return -1;
            output[used++] = escaped[0];
            output[used++] = escaped[1];
        } else {
            if (*cursor < 0x20U || used + 1U >= size)
                return -1;
            output[used++] = (char)*cursor;
        }
    }
    output[used] = '\0';
    return 0;
}

static int url_encode(const char *input, char *output, size_t size)
{
    static const char hex[] = "0123456789ABCDEF";
    size_t used = 0U;
    for (const unsigned char *cursor = (const unsigned char *)input;
         *cursor != '\0'; cursor++) {
        if (isalnum(*cursor) || *cursor == '-' || *cursor == '_'
                || *cursor == '.' || *cursor == '~') {
            if (used + 1U >= size)
                return -1;
            output[used++] = (char)*cursor;
        } else {
            if (used + 3U >= size)
                return -1;
            output[used++] = '%';
            output[used++] = hex[*cursor >> 4];
            output[used++] = hex[*cursor & 0x0fU];
        }
    }
    output[used] = '\0';
    return 0;
}

static int read_machine_id(char *output, size_t size)
{
    FILE *file = fopen("/etc/machine-id", "rb");
    char raw[96] = {0};
    if (file == NULL)
        return -1;
    size_t length = fread(raw, 1, sizeof(raw) - 1U, file);
    fclose(file);
    size_t used = 0U;
    for (size_t i = 0U; i < length && used + 1U < size; i++) {
        if (isalnum((unsigned char)raw[i]))
            output[used++] = raw[i];
    }
    output[used] = '\0';
    return used >= 8U ? 0 : -1;
}

int netease_official_parse_client_ip(
    const unsigned char *response_data, size_t size,
    char *output, size_t output_size)
{
    if (response_data == NULL || size == 0U || output_size == 0U)
        return -1;
    char candidate[64] = {0};
    if (response_data[0] == '{') {
        jsmntok_t tokens[NETEASE_JSON_TOKENS];
        char ignored[1];
        int count = parse_json(response_data, size, tokens,
                               ignored, sizeof(ignored));
        int ip = count > 0
            ? object_value((const char *)response_data, tokens,
                           count, 0, "ip")
            : -1;
        if (ip < 0
                || copy_token((const char *)response_data, &tokens[ip],
                              candidate, sizeof(candidate)) != 0)
            return -1;
    } else {
        size_t begin = 0U;
        while (begin < size && isspace(response_data[begin]))
            begin++;
        size_t end = size;
        while (end > begin && isspace(response_data[end - 1U]))
            end--;
        size_t length = end - begin;
        if (length == 0U || length >= sizeof(candidate))
            return -1;
        memcpy(candidate, response_data + begin, length);
        candidate[length] = '\0';
    }
    struct in_addr address;
    if (inet_pton(AF_INET, candidate, &address) != 1
            || strlen(candidate) >= output_size)
        return -1;
    snprintf(output, output_size, "%s", candidate);
    return 0;
}

static int fetch_client_ip(char *output, size_t size,
                           char *error, size_t error_size)
{
    static const char *urls[] = {
        "https://api.ipify.org?format=json",
        "https://ipv4.icanhazip.com/",
    };
    for (size_t i = 0U; i < sizeof(urls) / sizeof(urls[0]); i++) {
        http_response_t response;
        if (http_get_with_timeouts(
                urls[i], 1024U,
                NETEASE_IP_CONNECT_TIMEOUT_MS,
                NETEASE_IP_TIMEOUT_MS,
                &response, error, error_size) != 0)
            continue;
        int result = netease_official_parse_client_ip(
            response.data, response.size, output, size
        );
        http_response_free(&response);
        if (result == 0)
            return 0;
    }
    snprintf(error, error_size, "无法取得设备出口 IP");
    return -1;
}

static int make_device_json(const netease_official_session_t *session,
                            char *output, size_t size)
{
    char device_id[65];
    if (read_machine_id(device_id, sizeof(device_id)) != 0)
        return -1;
    int written = snprintf(
        output, size,
        "{\"deviceType\":\"openapi\",\"os\":\"ncmcli\","
        "\"appVer\":\"0.1.0\",\"channel\":\"ncmcli\","
        "\"model\":\"Linux_arm_cli\",\"brand\":\"ncmcli\","
        "\"osVer\":\"1.0.0\",\"clientIp\":\"%s\","
        "\"deviceId\":\"%s\"}", session->client_ip, device_id
    );
    return written > 0 && (size_t)written < size ? 0 : -1;
}

static int host_has_suffix(const char *host, size_t length,
                           const char *suffix)
{
    size_t suffix_length = strlen(suffix);
    return length >= suffix_length
        && strncmp(host + length - suffix_length,
                   suffix, suffix_length) == 0;
}

static int normalize_music_url(const char *json, const jsmntok_t *token,
                               char *output, size_t size)
{
    char url[TRACK_URL_SIZE];
    if (copy_json_string(json, token, url, sizeof(url)) != 0)
        return -1;
    const char *host = NULL;
    const char *scheme = NULL;
    if (strncmp(url, "https://", 8) == 0) {
        host = url + 8;
        scheme = "https://";
    } else if (strncmp(url, "http://", 7) == 0) {
        host = url + 7;
        scheme = "https://";
    } else {
        return -1;
    }
    const char *path = strchr(host, '/');
    if (path == NULL)
        return -1;
    size_t host_length = (size_t)(path - host);
    if (!host_has_suffix(host, host_length, ".music.126.net")
            && !host_has_suffix(host, host_length, ".music.163.com"))
        return -1;
    int written = snprintf(output, size, "%s%.*s%s", scheme,
                           (int)host_length, host, path);
    return written > 0 && (size_t)written < size ? 0 : -1;
}

int netease_official_validate_config(const app_config_t *config,
                                     char *error, size_t error_size)
{
    if (config->netease_app_id[0] == '\0'
            || config->netease_private_key_file[0] == '\0') {
        snprintf(error, error_size,
                 "请配置网易云 App ID 与 Private Key 文件");
        return -1;
    }
    for (const unsigned char *cursor =
             (const unsigned char *)config->netease_app_id;
         *cursor != '\0'; cursor++) {
        if (!isalnum(*cursor) && *cursor != '-' && *cursor != '_') {
            snprintf(error, error_size, "网易云 App ID 格式无效");
            return -1;
        }
    }
    struct stat info;
    if (stat(config->netease_private_key_file, &info) != 0
            || !S_ISREG(info.st_mode)) {
        snprintf(error, error_size, "网易云 Private Key 文件不存在");
        return -1;
    }
    if ((info.st_mode & 077) != 0) {
        snprintf(error, error_size,
                 "网易云 Private Key 文件权限必须为 0600");
        return -1;
    }
    return 0;
}

static int parse_anonymous_token(const http_response_t *response,
                                 netease_official_session_t *session,
                                 char *error, size_t error_size)
{
    jsmntok_t tokens[NETEASE_JSON_TOKENS];
    int count = parse_json(response->data, response->size, tokens,
                           error, error_size);
    const char *json = (const char *)response->data;
    if (count < 0 || parse_api_code(json, tokens, count,
                                    error, error_size) != 0)
        return -1;
    int data = object_value(json, tokens, count, 0, "data");
    int token = object_value(json, tokens, count, data, "accessToken");
    if (token < 0 || copy_token(json, &tokens[token],
                               session->anonymous_token,
                               sizeof(session->anonymous_token)) != 0) {
        snprintf(error, error_size, "匿名登录响应缺少 accessToken");
        return -1;
    }
    return 0;
}

static int request_anonymous_token(const app_config_t *config,
                                   netease_official_session_t *session,
                                   const char *device,
                                   char *error, size_t error_size)
{
    char timestamp[32];
    snprintf(timestamp, sizeof(timestamp), "%lld",
             (long long)epoch_milliseconds());
    char biz[160];
    snprintf(biz, sizeof(biz), "{\"clientId\":\"%s\"}",
             config->netease_app_id);
    sign_param_t params[] = {
        {"appId", config->netease_app_id},
        {"signType", "RSA_SHA256"},
        {"timestamp", timestamp},
        {"device", device},
        {"bizContent", biz},
    };
    char signature[1024];
    if (sign_request(config, params, sizeof(params) / sizeof(params[0]),
                     signature, sizeof(signature), error, error_size) != 0)
        return -1;
    char escaped_device[2048];
    char escaped_biz[512];
    if (json_escape(device, escaped_device, sizeof(escaped_device)) != 0
            || json_escape(biz, escaped_biz, sizeof(escaped_biz)) != 0) {
        snprintf(error, error_size, "网易云匿名登录参数过长");
        memset(signature, 0, sizeof(signature));
        return -1;
    }
    char body[NETEASE_REQUEST_SIZE];
    int written = snprintf(
        body, sizeof(body),
        "{\"appId\":\"%s\",\"signType\":\"RSA_SHA256\","
        "\"timestamp\":\"%s\",\"device\":\"%s\","
        "\"bizContent\":\"%s\",\"sign\":\"%s\"}",
        config->netease_app_id, timestamp, escaped_device,
        escaped_biz, signature
    );
    memset(signature, 0, sizeof(signature));
    if (written < 0 || (size_t)written >= sizeof(body)) {
        snprintf(error, error_size, "网易云匿名登录请求过长");
        return -1;
    }
    http_response_t response;
    int result = http_post_json(
        NETEASE_API_BASE "/openapi/music/basic/oauth2/login/anonymous",
        body, NETEASE_RESPONSE_MAX, &response, error, error_size
    );
    memset(body, 0, sizeof(body));
    if (result != 0)
        return -1;
    result = parse_anonymous_token(&response, session, error, error_size);
    http_response_free(&response);
    return result;
}

static int build_get_url(const app_config_t *config,
                         const char *path, const char *biz,
                         const char *device, const char *access_token,
                         char *url, size_t url_size,
                         char *error, size_t error_size)
{
    char timestamp[32];
    snprintf(timestamp, sizeof(timestamp), "%lld",
             (long long)epoch_milliseconds());
    sign_param_t params[] = {
        {"appId", config->netease_app_id},
        {"signType", "RSA_SHA256"},
        {"timestamp", timestamp},
        {"device", device},
        {"bizContent", biz},
        {"accessToken", access_token},
    };
    char signature[1024];
    if (sign_request(config, params, sizeof(params) / sizeof(params[0]),
                     signature, sizeof(signature), error, error_size) != 0)
        return -1;
    char encoded_device[4096];
    char encoded_biz[2048];
    char encoded_token[8192];
    char encoded_signature[4096];
    if (url_encode(device, encoded_device, sizeof(encoded_device)) != 0
            || url_encode(biz, encoded_biz, sizeof(encoded_biz)) != 0
            || url_encode(access_token, encoded_token,
                          sizeof(encoded_token)) != 0
            || url_encode(signature, encoded_signature,
                          sizeof(encoded_signature)) != 0) {
        memset(signature, 0, sizeof(signature));
        snprintf(error, error_size, "网易云登录 URL 参数过长");
        return -1;
    }
    memset(signature, 0, sizeof(signature));
    int written = snprintf(
        url, url_size,
        NETEASE_API_BASE "%s?appId=%s&signType=RSA_SHA256&timestamp=%s"
        "&device=%s&bizContent=%s&accessToken=%s&sign=%s",
        path, config->netease_app_id, timestamp, encoded_device,
        encoded_biz, encoded_token, encoded_signature
    );
    memset(encoded_token, 0, sizeof(encoded_token));
    return written > 0 && (size_t)written < url_size ? 0 : -1;
}

int netease_official_parse_qr_response(
    const unsigned char *response_data, size_t size,
    netease_official_session_t *session,
    char *error, size_t error_size)
{
    jsmntok_t tokens[NETEASE_JSON_TOKENS];
    int count = parse_json(response_data, size, tokens, error, error_size);
    const char *json = (const char *)response_data;
    int result = -1;
    if (count > 0 && parse_api_code(json, tokens, count,
                                    error, error_size) == 0) {
        int data = object_value(json, tokens, count, 0, "data");
        int qr_url = object_value(json, tokens, count, data, "qrCodeUrl");
        int uni_key = object_value(json, tokens, count, data, "uniKey");
        if (qr_url >= 0 && uni_key >= 0
                && copy_token(json, &tokens[qr_url], session->qr_url,
                              sizeof(session->qr_url)) == 0
                && copy_token(json, &tokens[uni_key], session->uni_key,
                              sizeof(session->uni_key)) == 0) {
            result = 0;
        } else {
            snprintf(error, error_size, "二维码响应缺少 URL 或 uniKey");
        }
    }
    return result;
}

static int request_qr_code(const app_config_t *config,
                           netease_official_session_t *session,
                           const char *device,
                           char *error, size_t error_size)
{
    char url[NETEASE_REQUEST_SIZE];
    if (build_get_url(
            config,
            "/openapi/music/basic/user/oauth2/qrcodekey/get/v2",
            "{\"type\":2,\"expiredKey\":\"300\"}", device,
            session->anonymous_token,
            url, sizeof(url), error, error_size) != 0) {
        if (error[0] == '\0')
            snprintf(error, error_size, "网易云二维码请求过长");
        return -1;
    }
    http_response_t response;
    if (http_get(url, NETEASE_RESPONSE_MAX, &response,
                 error, error_size) != 0)
        return -1;
    int result = netease_official_parse_qr_response(
        response.data, response.size, session, error, error_size
    );
    http_response_free(&response);
    return result;
}

int netease_official_begin_login(const app_config_t *config,
                                 netease_official_session_t *session,
                                 char *error, size_t error_size)
{
    memset(session, 0, sizeof(*session));
    if (netease_official_validate_config(config, error, error_size) != 0)
        return -1;
    if (fetch_client_ip(session->client_ip, sizeof(session->client_ip),
                        error, error_size) != 0)
        return -1;
    char device[1024];
    if (make_device_json(session, device, sizeof(device)) != 0) {
        snprintf(error, error_size, "无法生成网易云设备信息");
        return -1;
    }
    if (request_anonymous_token(config, session, device,
                                error, error_size) != 0)
        return -1;
    if (request_qr_code(config, session, device,
                        error, error_size) != 0) {
        memset(session->anonymous_token, 0,
               sizeof(session->anonymous_token));
        return -1;
    }
    return 0;
}

int netease_official_parse_poll_response(
    const unsigned char *response_data, size_t size,
    netease_official_session_t *session, netease_qr_status_t *status,
    char *error, size_t error_size)
{
    jsmntok_t tokens[NETEASE_JSON_TOKENS];
    int count = parse_json(response_data, size, tokens, error, error_size);
    const char *json = (const char *)response_data;
    int result = -1;
    if (count > 0 && parse_api_code(json, tokens, count,
                                    error, error_size) == 0) {
        int data = object_value(json, tokens, count, 0, "data");
        int status_token = object_value(json, tokens, count, data, "status");
        int64_t parsed_status = 0;
        if (status_token >= 0
                && parse_primitive_i64(json, &tokens[status_token],
                                       &parsed_status) == 0
                && parsed_status >= NETEASE_QR_EXPIRED
                && parsed_status <= NETEASE_QR_UNKNOWN) {
            *status = (netease_qr_status_t)parsed_status;
            result = 0;
            if (*status == NETEASE_QR_SUCCESS) {
                int auth = object_value(json, tokens, count,
                                        data, "accessToken");
                int access = object_value(json, tokens, count,
                                          auth, "accessToken");
                int refresh = object_value(json, tokens, count,
                                           auth, "refreshToken");
                int expire = object_value(json, tokens, count,
                                          auth, "expireTime");
                int64_t expire_seconds = 0;
                if (access < 0 || refresh < 0 || expire < 0
                        || copy_token(json, &tokens[access],
                                      session->access_token,
                                      sizeof(session->access_token)) != 0
                        || copy_token(json, &tokens[refresh],
                                      session->refresh_token,
                                      sizeof(session->refresh_token)) != 0
                        || parse_primitive_i64(json, &tokens[expire],
                                               &expire_seconds) != 0) {
                    snprintf(error, error_size,
                             "扫码成功响应缺少登录 token");
                    result = -1;
                } else {
                    session->expire_at = epoch_seconds() + expire_seconds;
                }
            }
        } else {
            snprintf(error, error_size, "二维码状态响应无效");
        }
    }
    return result;
}

int netease_official_poll_login(const app_config_t *config,
                                netease_official_session_t *session,
                                netease_qr_status_t *status,
                                char *error, size_t error_size)
{
    char device[1024];
    if (session->anonymous_token[0] == '\0'
            || session->uni_key[0] == '\0'
            || make_device_json(session, device, sizeof(device)) != 0) {
        snprintf(error, error_size, "网易云二维码会话无效");
        return -1;
    }
    char biz[512];
    int written = snprintf(biz, sizeof(biz),
                           "{\"key\":\"%s\",\"clientId\":\"%s\"}",
                           session->uni_key, config->netease_app_id);
    if (written < 0 || (size_t)written >= sizeof(biz)) {
        snprintf(error, error_size, "网易云轮询参数过长");
        return -1;
    }
    char url[NETEASE_REQUEST_SIZE];
    if (build_get_url(
            config,
            "/openapi/music/basic/oauth2/device/login/qrcode/get",
            biz, device, session->anonymous_token,
            url, sizeof(url), error, error_size) != 0) {
        if (error[0] == '\0')
            snprintf(error, error_size, "网易云轮询 URL 过长");
        return -1;
    }
    http_response_t response;
    if (http_get(url, NETEASE_RESPONSE_MAX, &response,
                 error, error_size) != 0)
        return -1;
    int result = netease_official_parse_poll_response(
        response.data, response.size, session, status, error, error_size
    );
    http_response_free(&response);
    return result;
}

static int map_recommendation(const char *json,
                              const jsmntok_t *tokens, int count,
                              int object, track_t *track, unsigned rank)
{
    int id = object_value(json, tokens, count, object, "id");
    int name = object_value(json, tokens, count, object, "name");
    int duration = object_value(json, tokens, count, object, "duration");
    int artists = object_value(json, tokens, count, object, "artists");
    int cover = object_value(json, tokens, count, object, "coverImgUrl");
    if (id < 0 || name < 0 || duration < 0 || artists < 0
            || tokens[artists].type != JSMN_ARRAY
            || tokens[artists].size < 1)
        return -1;
    int artist = artists + 1;
    int artist_name = object_value(json, tokens, count, artist, "name");
    int64_t duration_ms = 0;
    if (artist_name < 0
            || copy_scalar_string(json, &tokens[id],
                                  track->id, sizeof(track->id)) != 0
            || copy_json_string(json, &tokens[name],
                                track->title, sizeof(track->title)) != 0
            || copy_json_string(json, &tokens[artist_name],
                                track->artist, sizeof(track->artist)) != 0
            || parse_primitive_i64(json, &tokens[duration],
                                   &duration_ms) != 0
            || duration_ms < 0)
        return -1;
    snprintf(track->source, sizeof(track->source), "netease");
    track->rank = rank;
    track->duration_ms = (uint64_t)duration_ms;
    snprintf(track->share_url, sizeof(track->share_url),
             "https://music.163.com/song?id=%s", track->id);
    if (cover >= 0 && tokens[cover].type == JSMN_STRING) {
        if (normalize_music_url(
            json, &tokens[cover], track->cover_url,
            sizeof(track->cover_url)
        ) == 0 && strchr(track->cover_url, '?') == NULL) {
            size_t used = strlen(track->cover_url);
            static const char resize[] = "?param=256y256";
            if (used + sizeof(resize) <= sizeof(track->cover_url))
                memcpy(track->cover_url + used, resize, sizeof(resize));
        }
    }
    return 0;
}

int netease_official_map_recommendations(
    const unsigned char *response_data, size_t size,
    track_list_t *tracks, char *error, size_t error_size)
{
    if (response_data == NULL || size == 0U
            || size > NETEASE_RESPONSE_MAX) {
        snprintf(error, error_size, "网易云每日推荐响应大小无效");
        return -1;
    }
    jsmntok_t tokens[NETEASE_JSON_TOKENS];
    int count = parse_json(response_data, size, tokens, error, error_size);
    const char *json = (const char *)response_data;
    if (count < 0 || parse_api_code(json, tokens, count,
                                    error, error_size) != 0)
        return -1;
    int data = object_value(json, tokens, count, 0, "data");
    if (data < 0 || tokens[data].type != JSMN_ARRAY) {
        snprintf(error, error_size, "网易云每日推荐缺少 data");
        return -1;
    }
    memset(tracks, 0, sizeof(*tracks));
    int cursor = data + 1;
    while (cursor < count && tokens[cursor].start < tokens[data].end
            && tracks->count < TRACK_LIST_MAX) {
        if (tokens[cursor].type != JSMN_OBJECT) {
            snprintf(error, error_size, "网易云每日推荐曲目无效");
            return -1;
        }
        track_t *track = &tracks->items[tracks->count];
        memset(track, 0, sizeof(*track));
        if (map_recommendation(
                json, tokens, count, cursor, track,
                (unsigned)tracks->count + 1U) != 0) {
            snprintf(error, error_size, "网易云每日推荐曲目字段无效");
            return -1;
        }
        tracks->count++;
        cursor = token_skip(tokens, count, cursor);
    }
    if (tracks->count == 0U) {
        snprintf(error, error_size, "网易云每日推荐为空");
        return -1;
    }
    return 0;
}

size_t netease_official_map_play_urls(
    const unsigned char *response_data, size_t size,
    track_list_t *tracks, char *error, size_t error_size)
{
    jsmntok_t tokens[NETEASE_JSON_TOKENS];
    int count = parse_json(response_data, size, tokens, error, error_size);
    const char *json = (const char *)response_data;
    if (count < 0 || parse_api_code(json, tokens, count,
                                    error, error_size) != 0)
        return 0U;
    int data = object_value(json, tokens, count, 0, "data");
    if (data < 0 || tokens[data].type != JSMN_ARRAY) {
        snprintf(error, error_size, "网易云播放地址缺少 data");
        return 0U;
    }
    size_t mapped = 0U;
    int cursor = data + 1;
    while (cursor < count && tokens[cursor].start < tokens[data].end) {
        int id = object_value(json, tokens, count, cursor, "id");
        int url = object_value(json, tokens, count, cursor, "url");
        char id_value[TRACK_ID_SIZE];
        if (id >= 0
                && copy_scalar_string(json, &tokens[id], id_value,
                                      sizeof(id_value)) == 0) {
            for (size_t i = 0U; i < tracks->count; i++) {
                if (strcmp(tracks->items[i].id, id_value) != 0)
                    continue;
                if (url >= 0 && tokens[url].type == JSMN_STRING
                        && normalize_music_url(
                            json, &tokens[url],
                            tracks->items[i].audio_url,
                            sizeof(tracks->items[i].audio_url)) == 0) {
                    tracks->items[i].audio_resolved = 1;
                    mapped++;
                }
                break;
            }
        }
        cursor = token_skip(tokens, count, cursor);
    }
    error[0] = '\0';
    return mapped;
}

static int map_data_url(
    const unsigned char *response_data, size_t size,
    const char *url_field, track_t *track,
    char *error, size_t error_size)
{
    jsmntok_t tokens[NETEASE_JSON_TOKENS];
    int count = parse_json(response_data, size, tokens, error, error_size);
    const char *json = (const char *)response_data;
    if (count < 0 || parse_api_code(json, tokens, count,
                                    error, error_size) != 0)
        return -1;
    int data = object_value(json, tokens, count, 0, "data");
    int url = object_value(json, tokens, count, data, url_field);
    if (url < 0) {
        snprintf(error, error_size, "网易云播放响应缺少 data.%s",
                 url_field);
        return -1;
    }
    if (tokens[url].type != JSMN_STRING) {
        track->audio_resolved = 1;
        error[0] = '\0';
        return 0;
    }
    if (normalize_music_url(
            json, &tokens[url], track->audio_url,
            sizeof(track->audio_url)) != 0) {
        snprintf(error, error_size, "网易云单曲播放地址域名无效");
        return -1;
    }
    track->audio_resolved = 1;
    error[0] = '\0';
    return 1;
}

int netease_official_map_single_play_url(
    const unsigned char *response_data, size_t size,
    track_t *track, char *error, size_t error_size)
{
    return map_data_url(response_data, size, "url", track,
                        error, error_size);
}

int netease_official_map_song_detail_url(
    const unsigned char *response_data, size_t size,
    track_t *track, char *error, size_t error_size)
{
    return map_data_url(response_data, size, "playUrl", track,
                        error, error_size);
}

static int request_signed_get(const app_config_t *config,
                              const netease_official_session_t *session,
                              const char *device,
                              const char *path, const char *biz,
                              http_response_t *response,
                              char *error, size_t error_size)
{
    char url[NETEASE_REQUEST_SIZE];
    if (build_get_url(config, path, biz, device, session->access_token,
                      url, sizeof(url), error, error_size) != 0) {
        if (error[0] == '\0')
            snprintf(error, error_size, "网易云实名请求 URL 过长");
        return -1;
    }
    return http_get_with_timeouts(
        url, NETEASE_RESPONSE_MAX,
        NETEASE_API_CONNECT_TIMEOUT_MS,
        NETEASE_API_TIMEOUT_MS,
        response, error, error_size
    );
}

static int prepare_signed_context(
    const app_config_t *config,
    netease_official_session_t *session,
    char *device, size_t device_size,
    char *error, size_t error_size)
{
    memset(session, 0, sizeof(*session));
    int loaded = netease_official_load_session(
        config, session, error, error_size
    );
    if (loaded != 0) {
        if (loaded > 0)
            snprintf(error, error_size, "网易云登录 session 已过期");
        return -1;
    }

    struct in_addr address;
    if (inet_pton(AF_INET, session->client_ip, &address) != 1) {
        if (inet_pton(AF_INET, cached_client_ip, &address) == 1) {
            snprintf(session->client_ip, sizeof(session->client_ip),
                     "%s", cached_client_ip);
        } else {
            if (fetch_client_ip(
                    session->client_ip, sizeof(session->client_ip),
                    error, error_size) != 0)
                return -1;
            snprintf(cached_client_ip, sizeof(cached_client_ip),
                     "%s", session->client_ip);
        }
    } else {
        snprintf(cached_client_ip, sizeof(cached_client_ip),
                 "%s", session->client_ip);
    }

    if (make_device_json(session, device, device_size) != 0) {
        snprintf(error, error_size, "无法生成网易云设备信息");
        return -1;
    }
    return 0;
}

static int parse_star_playlist_id(const http_response_t *response,
                                  char *playlist_id, size_t playlist_id_size,
                                  char *error, size_t error_size)
{
    jsmntok_t tokens[NETEASE_JSON_TOKENS];
    int count = parse_json(response->data, response->size, tokens,
                           error, error_size);
    const char *json = (const char *)response->data;
    if (count < 0 || parse_api_code(json, tokens, count,
                                    error, error_size) != 0)
        return -1;
    int data = object_value(json, tokens, count, 0, "data");
    int id = object_value(json, tokens, count, data, "id");
    if (id < 0 || copy_scalar_string(
            json, &tokens[id], playlist_id, playlist_id_size) != 0) {
        snprintf(error, error_size, "网易云红心歌单响应缺少 ID");
        return -1;
    }
    return 0;
}

static int load_star_playlist(const app_config_t *config,
                              const netease_official_session_t *session,
                              const char *device, track_list_t *tracks,
                              char *error, size_t error_size)
{
    http_response_t response;
    if (request_signed_get(
            config, session, device,
            "/openapi/music/basic/playlist/star/get/v2",
            "{\"limit\":1,\"offset\":0}",
            &response, error, error_size) != 0)
        return -1;
    char playlist_id[TRACK_ID_SIZE];
    int result = parse_star_playlist_id(
        &response, playlist_id, sizeof(playlist_id), error, error_size
    );
    http_response_free(&response);
    if (result != 0)
        return -1;

    char biz[256];
    int written = snprintf(
        biz, sizeof(biz),
        "{\"playlistId\":\"%s\",\"limit\":32,"
        "\"offset\":0,\"qualityFlag\":true}",
        playlist_id
    );
    if (written < 0 || (size_t)written >= sizeof(biz)) {
        snprintf(error, error_size, "网易云红心歌单 ID 过长");
        return -1;
    }
    if (request_signed_get(
            config, session, device,
            "/openapi/music/basic/playlist/song/list/get/v3",
            biz, &response, error, error_size) != 0)
        return -1;
    result = netease_official_map_recommendations(
        response.data, response.size, tracks, error, error_size
    );
    http_response_free(&response);
    if (result == 0)
        fprintf(stderr, "[netease] 已加载用户红心歌单\n");
    return result;
}

typedef int (*map_track_url_fn)(
    const unsigned char *response_data, size_t size,
    track_t *track, char *error, size_t error_size
);

static int load_first_playable_url(
    const app_config_t *config,
    const netease_official_session_t *session,
    const char *device, track_list_t *tracks,
    const char *path, int use_detail,
    map_track_url_fn map_url,
    char *error, size_t error_size)
{
    size_t attempts = 0U;
    for (size_t i = 0U; i < tracks->count
            && attempts < NETEASE_STARTUP_RESOLVE_LIMIT; i++) {
        track_t *track = &tracks->items[i];
        if (track->audio_url[0] != '\0')
            return 1;
        if (track->audio_resolved)
            continue;

        char biz[224];
        int written = snprintf(
            biz, sizeof(biz),
            use_detail
                ? "{\"songId\":\"%s\",\"withUrl\":true,\"bitrate\":128}"
                : "{\"songId\":\"%s\",\"bitrate\":128}",
            track->id
        );
        if (written < 0 || (size_t)written >= sizeof(biz)) {
            snprintf(error, error_size, "网易云歌曲 ID 过长");
            return -1;
        }
        http_response_t response;
        if (request_signed_get(
                config, session, device, path, biz,
                &response, error, error_size) != 0) {
            fprintf(stderr,
                    "[netease] 启动播放地址请求中止，保留列表: %s\n",
                    error);
            error[0] = '\0';
            return 0;
        }
        attempts++;
        int result = map_url(response.data, response.size, track,
                             error, error_size);
        http_response_free(&response);
        if (result < 0)
            return -1;
        if (result > 0)
            return 1;
    }
    fprintf(stderr,
            "[netease] 启动播放地址预算已用 %zu/%u 次，"
            "剩余曲目按需加载\n",
            attempts, NETEASE_STARTUP_RESOLVE_LIMIT);
    error[0] = '\0';
    return 0;
}

static size_t count_playable_tracks(const track_list_t *tracks)
{
    size_t count = 0U;
    for (size_t i = 0U; i < tracks->count; i++) {
        if (tracks->items[i].audio_url[0] != '\0')
            count++;
    }
    return count;
}

static int resolve_track_detail(
    const app_config_t *config,
    const netease_official_session_t *session,
    const char *device, track_t *track,
    char *error, size_t error_size)
{
    char biz[224];
    int written = snprintf(
        biz, sizeof(biz),
        "{\"songId\":\"%s\",\"withUrl\":true,\"bitrate\":128}",
        track->id
    );
    if (written < 0 || (size_t)written >= sizeof(biz)) {
        snprintf(error, error_size, "网易云歌曲 ID 过长");
        return -1;
    }
    http_response_t response;
    if (request_signed_get(
            config, session, device,
            "/openapi/music/basic/song/detail/get/v2",
            biz, &response, error, error_size) != 0)
        return -1;
    int result = netease_official_map_song_detail_url(
        response.data, response.size, track, error, error_size
    );
    http_response_free(&response);
    return result;
}

static int make_play_url_biz(const track_list_t *tracks,
                             char *output, size_t size)
{
    int written = snprintf(output, size,
                           "{\"songIds\":[");
    if (written < 0 || (size_t)written >= size)
        return -1;
    size_t used = (size_t)written;
    for (size_t i = 0U; i < tracks->count; i++) {
        written = snprintf(output + used, size - used,
                           "%s\"%s\"", i == 0U ? "" : ",",
                           tracks->items[i].id);
        if (written < 0 || (size_t)written >= size - used)
            return -1;
        used += (size_t)written;
    }
    written = snprintf(output + used, size - used,
                       "],\"bitrate\":128}");
    return written > 0 && (size_t)written < size - used ? 0 : -1;
}

int netease_official_load_recommendations(
    const app_config_t *config, track_list_t *tracks,
    char *error, size_t error_size)
{
    netease_official_session_t session;
    char device[1024];
    if (prepare_signed_context(
            config, &session, device, sizeof(device),
            error, error_size) != 0)
        return -1;
    int result = load_star_playlist(
        config, &session, device, tracks, error, error_size
    );
    if (result != 0) {
        fprintf(stderr,
                "[netease] 红心歌单不可用，尝试每日推荐: %s\n",
                error);
        error[0] = '\0';
        http_response_t response;
        if (request_signed_get(
                config, &session, device,
                "/openapi/music/basic/recommend/songlist/get/v2",
                "{\"limit\":32,\"qualityFlag\":true}",
                &response, error, error_size) != 0)
            return -1;
        result = netease_official_map_recommendations(
            response.data, response.size, tracks, error, error_size
        );
        http_response_free(&response);
        if (result != 0)
            return -1;
    }

    char biz[4096];
    if (make_play_url_biz(tracks, biz, sizeof(biz)) != 0) {
        snprintf(error, error_size, "网易云歌曲 ID 列表过长");
        return -1;
    }
    http_response_t response;
    int batch_result = request_signed_get(
            config, &session, device,
            "/openapi/music/basic/batch/song/playurl/get",
            biz, &response, error, error_size) != 0
        ? -1 : 0;
    size_t mapped = 0U;
    if (batch_result == 0) {
        mapped = netease_official_map_play_urls(
            response.data, response.size, tracks, error, error_size
        );
        http_response_free(&response);
    } else {
        fprintf(stderr,
                "[netease] 批量播放地址网络失败，先显示列表: %s\n",
                error);
        error[0] = '\0';
    }
    if (batch_result == 0 && (error[0] != '\0' || mapped == 0U)) {
        fprintf(stderr,
                "[netease] 批量播放地址不可用，受限降级: %s\n",
                error[0] == '\0' ? "没有可播放地址" : error);
        error[0] = '\0';
        int single_mapped = load_first_playable_url(
            config, &session, device, tracks,
            "/openapi/music/basic/song/playurl/get/v2", 0,
            netease_official_map_single_play_url,
            error, error_size
        );
        if (single_mapped < 0) {
            fprintf(stderr,
                    "[netease] 单曲播放地址不可用，尝试歌曲详情: %s\n",
                    error);
            error[0] = '\0';
            single_mapped = load_first_playable_url(
                config, &session, device, tracks,
                "/openapi/music/basic/song/detail/get/v2", 1,
                netease_official_map_song_detail_url,
                error, error_size
            );
            if (single_mapped < 0) {
                fprintf(stderr,
                        "[netease] 歌曲详情暂不可用，先显示列表: %s\n",
                        error);
                error[0] = '\0';
            }
        }
    }
    mapped = count_playable_tracks(tracks);
    fprintf(stderr, "[netease] 在线歌单 %zu 首，可播放 %zu 首\n",
            tracks->count, mapped);
    return 0;
}

int netease_official_resolve_track(
    const app_config_t *config, track_t *track,
    char *error, size_t error_size)
{
    if (track == NULL || track->id[0] == '\0') {
        snprintf(error, error_size, "网易云歌曲 ID 为空");
        return -1;
    }
    if (track->audio_resolved)
        return track->audio_url[0] == '\0' ? 0 : 1;

    netease_official_session_t session;
    char device[1024];
    if (prepare_signed_context(
            config, &session, device, sizeof(device),
            error, error_size) != 0)
        return -1;
    return resolve_track_detail(
        config, &session, device, track, error, error_size
    );
}

int netease_official_save_session(const app_config_t *config,
                                  const netease_official_session_t *session,
                                  char *error, size_t error_size)
{
    char temporary[CONFIG_PATH_SIZE + 8U];
    int written = snprintf(temporary, sizeof(temporary), "%s.tmp",
                           config->netease_session_file);
    if (written < 0 || (size_t)written >= sizeof(temporary)) {
        snprintf(error, error_size, "网易云 session 路径过长");
        return -1;
    }
    int fd = open(temporary, O_WRONLY | O_CREAT | O_TRUNC | O_CLOEXEC, 0600);
    if (fd < 0) {
        snprintf(error, error_size, "无法创建网易云 session");
        return -1;
    }
    (void)fchmod(fd, 0600);
    char json[NETEASE_TOKEN_SIZE * 2U + 256U];
    written = snprintf(
        json, sizeof(json),
        "{\n  \"accessToken\": \"%s\",\n"
        "  \"refreshToken\": \"%s\",\n"
        "  \"expireAt\": %lld\n}\n",
        session->access_token, session->refresh_token,
        (long long)session->expire_at
    );
    int result = 0;
    if (written < 0 || (size_t)written >= sizeof(json)
            || write(fd, json, (size_t)written) != (ssize_t)written
            || fsync(fd) != 0) {
        snprintf(error, error_size, "写入网易云 session 失败");
        result = -1;
    }
    memset(json, 0, sizeof(json));
    if (close(fd) != 0 && result == 0) {
        snprintf(error, error_size, "关闭网易云 session 失败");
        result = -1;
    }
    if (result == 0 && rename(temporary, config->netease_session_file) != 0) {
        snprintf(error, error_size, "保存网易云 session 失败");
        result = -1;
    }
    if (result != 0)
        unlink(temporary);
    return result;
}

int netease_official_load_session(const app_config_t *config,
                                  netease_official_session_t *session,
                                  char *error, size_t error_size)
{
    memset(session, 0, sizeof(*session));
    int fd = open(config->netease_session_file,
                  O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
    if (fd < 0 && errno == ENOENT)
        return 1;
    if (fd < 0) {
        snprintf(error, error_size, "无法打开网易云 session");
        return -1;
    }
    struct stat info;
    if (fstat(fd, &info) != 0 || !S_ISREG(info.st_mode)
            || (info.st_mode & 077) != 0) {
        close(fd);
        snprintf(error, error_size,
                 "网易云 session 文件必须为普通文件且权限为 0600");
        return -1;
    }
    FILE *file = fdopen(fd, "rb");
    if (file == NULL) {
        close(fd);
        snprintf(error, error_size, "无法读取网易云 session");
        return -1;
    }
    unsigned char json[NETEASE_TOKEN_SIZE * 2U + 256U];
    size_t length = fread(json, 1, sizeof(json) - 1U, file);
    int read_error = ferror(file);
    fclose(file);
    if (read_error || length == 0U || length >= sizeof(json)) {
        snprintf(error, error_size, "网易云 session 文件无效");
        return -1;
    }
    json[length] = '\0';
    jsmntok_t tokens[NETEASE_JSON_TOKENS];
    int count = parse_json(json, length, tokens, error, error_size);
    const char *text = (const char *)json;
    int access = count > 0
        ? object_value(text, tokens, count, 0, "accessToken") : -1;
    int refresh = count > 0
        ? object_value(text, tokens, count, 0, "refreshToken") : -1;
    int expire = count > 0
        ? object_value(text, tokens, count, 0, "expireAt") : -1;
    int64_t expire_at = 0;
    if (access < 0 || refresh < 0 || expire < 0
            || copy_token(text, &tokens[access], session->access_token,
                          sizeof(session->access_token)) != 0
            || copy_token(text, &tokens[refresh], session->refresh_token,
                          sizeof(session->refresh_token)) != 0
            || parse_primitive_i64(text, &tokens[expire], &expire_at) != 0) {
        memset(json, 0, sizeof(json));
        snprintf(error, error_size, "网易云 session 字段无效");
        return -1;
    }
    memset(json, 0, sizeof(json));
    session->expire_at = expire_at;
    if (expire_at <= epoch_seconds() + 60) {
        memset(session, 0, sizeof(*session));
        return 1;
    }
    return 0;
}
