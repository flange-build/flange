#!/bin/bash
# 在 Docker 构建容器的宿主架构编译并运行纯算法测试。
set -xeuo pipefail

app_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
spectrum_test_bin="$(mktemp /tmp/cardputer-spectrum-test.XXXXXX)"
manifest_test_bin="$(mktemp /tmp/cardputer-manifest-test.XXXXXX)"
decoder_test_bin="$(mktemp /tmp/cardputer-decoder-test.XXXXXX)"
image_test_bin="$(mktemp /tmp/cardputer-image-test.XXXXXX)"
provider_test_bin="$(mktemp /tmp/cardputer-provider-test.XXXXXX)"
netease_test_bin="$(mktemp /tmp/cardputer-netease-test.XXXXXX)"
netease_official_test_bin="$(mktemp /tmp/cardputer-netease-official-test.XXXXXX)"
config_test_bin="$(mktemp /tmp/cardputer-config-test.XXXXXX)"
device_test_bin="$(mktemp /tmp/cardputer-device-test.XXXXXX)"
state_test_bin="$(mktemp /tmp/cardputer-state-test.XXXXXX)"
text_test_bin="$(mktemp /tmp/cardputer-text-test.XXXXXX)"
input_test_bin="$(mktemp /tmp/cardputer-input-test.XXXXXX)"
loader_test_bin="$(mktemp /tmp/cardputer-loader-test.XXXXXX)"
http_test_bin="$(mktemp /tmp/cardputer-http-test.XXXXXX)"
trap 'rm -f "${spectrum_test_bin}" "${manifest_test_bin}" "${decoder_test_bin}" "${image_test_bin}" "${provider_test_bin}" "${netease_test_bin}" "${netease_official_test_bin}" "${config_test_bin}" "${device_test_bin}" "${state_test_bin}" "${text_test_bin}" "${input_test_bin}" "${loader_test_bin}" "${http_test_bin}"' EXIT

cc \
    -std=c11 \
    -Wall \
    -Wextra \
    -Werror \
    -I"${app_dir}/src" \
    "${app_dir}/tests/test_spectrum.c" \
    "${app_dir}/src/spectrum.c" \
    -lm \
    -o "${spectrum_test_bin}"

"${spectrum_test_bin}"

cc \
    -std=c11 \
    -Wall \
    -Wextra \
    -Werror \
    -I"${app_dir}/src" \
    -I"${app_dir}/third_party/jsmn" \
    "${app_dir}/tests/test_manifest.c" \
    "${app_dir}/src/manifest.c" \
    "${app_dir}/src/track.c" \
    -o "${manifest_test_bin}"

"${manifest_test_bin}"

cc \
    -std=c11 \
    -Wall \
    -Wextra \
    -Werror \
    -DDECODER_WAV_ONLY \
    -I"${app_dir}/src" \
    "${app_dir}/tests/test_decoder.c" \
    "${app_dir}/src/decoder.c" \
    -o "${decoder_test_bin}"

"${decoder_test_bin}"

cc \
    -std=c11 \
    -Wall \
    -Wextra \
    -Werror \
    -Wno-shadow \
    -I"${app_dir}/src" \
    -I"${app_dir}/third_party/stb" \
    "${app_dir}/tests/test_image.c" \
    "${app_dir}/src/image.c" \
    -lm \
    -o "${image_test_bin}"

"${image_test_bin}" "${app_dir}/res/midnight-bloom.png"

cc \
    -std=c11 \
    -Wall \
    -Wextra \
    -Werror \
    -I"${app_dir}/src" \
    -I"${app_dir}/third_party/jsmn" \
    "${app_dir}/tests/test_provider.c" \
    "${app_dir}/src/provider.c" \
    "${app_dir}/src/manifest.c" \
    "${app_dir}/src/track.c" \
    -o "${provider_test_bin}"

"${provider_test_bin}" "${app_dir}/tests/fixtures/douyin-hot.json"

cc \
    -std=c11 \
    -Wall \
    -Wextra \
    -Werror \
    -I"${app_dir}/src" \
    -I"${app_dir}/third_party/jsmn" \
    "${app_dir}/tests/test_netease.c" \
    "${app_dir}/src/netease.c" \
    -o "${netease_test_bin}"

"${netease_test_bin}" "${app_dir}/tests/fixtures/netease-playlist.json"

cc \
    -std=c11 \
    -Wall \
    -Wextra \
    -Werror \
    -I"${app_dir}/src" \
    -I"${app_dir}/third_party/jsmn" \
    "${app_dir}/tests/test_netease_official.c" \
    "${app_dir}/src/netease_official.c" \
    "${app_dir}/src/config.c" \
    "${app_dir}/src/http.c" \
    -lcurl \
    -lssl \
    -lcrypto \
    -o "${netease_official_test_bin}"

"${netease_official_test_bin}" \
    "${app_dir}/tests/fixtures/netease-official-recommendations.json" \
    "${app_dir}/tests/fixtures/netease-official-play-urls.json"

cc \
    -std=c11 \
    -Wall \
    -Wextra \
    -Werror \
    -I"${app_dir}/src" \
    -I"${app_dir}/third_party/jsmn" \
    "${app_dir}/tests/test_config.c" \
    "${app_dir}/src/config.c" \
    -o "${config_test_bin}"

"${config_test_bin}"

cc \
    -std=c11 \
    -Wall \
    -Wextra \
    -Werror \
    -I"${app_dir}/src" \
    "${app_dir}/tests/test_device_match.c" \
    "${app_dir}/src/device_match.c" \
    -o "${device_test_bin}"

"${device_test_bin}"

cc \
    -std=c11 \
    -Wall \
    -Wextra \
    -Werror \
    -I"${app_dir}/src" \
    "${app_dir}/tests/test_player_state.c" \
    "${app_dir}/src/player_state.c" \
    -o "${state_test_bin}"

"${state_test_bin}"

cc \
    -std=c11 \
    -Wall \
    -Wextra \
    -Werror \
    -I"${app_dir}/src" \
    "${app_dir}/tests/test_text.c" \
    "${app_dir}/src/text.c" \
    -o "${text_test_bin}"

"${text_test_bin}"

cc \
    -std=c11 \
    -Wall \
    -Wextra \
    -Werror \
    -I"${app_dir}/src" \
    "${app_dir}/tests/test_input.c" \
    "${app_dir}/src/input.c" \
    "${app_dir}/src/device_match.c" \
    -o "${input_test_bin}"

"${input_test_bin}"

cc \
    -std=c11 \
    -Wall \
    -Wextra \
    -Werror \
    -I"${app_dir}/src" \
    "${app_dir}/tests/test_queue_loader.c" \
    "${app_dir}/src/queue_loader.c" \
    -pthread \
    -o "${loader_test_bin}"

"${loader_test_bin}"

cc \
    -std=c11 \
    -Wall \
    -Wextra \
    -Werror \
    -DCARDPUTER_HTTP_TESTING \
    -I"${app_dir}/src" \
    "${app_dir}/tests/test_http.c" \
    "${app_dir}/src/http.c" \
    -lcurl \
    -o "${http_test_bin}"

"${http_test_bin}"
