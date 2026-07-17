cmake_minimum_required(VERSION 3.16)
project(cardputer_music_player VERSION 0.1.0 LANGUAGES C)

set(CMAKE_RUNTIME_OUTPUT_DIRECTORY ${CMAKE_SOURCE_DIR}/bin)
set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)

find_package(ALSA REQUIRED)
find_package(Freetype REQUIRED)
find_package(CURL REQUIRED)
find_path(MPG123_INCLUDE_DIR mpg123.h REQUIRED)
find_library(MPG123_LIBRARY NAMES mpg123 REQUIRED)
find_library(QRENCODE_LIBRARY NAMES qrencode REQUIRED)
find_library(CRYPTO_LIBRARY NAMES crypto REQUIRED)

add_executable(cardputer_music_player
    src/audio.c
    src/config.c
    src/decoder.c
    src/device_match.c
    src/font.c
    src/framebuffer.c
    src/http.c
    src/image.c
    src/input.c
    src/main.c
    src/manifest.c
    src/manifest_source.c
    src/media.c
    src/netease.c
    src/netease_source.c
    src/netease_official.c
    src/provider.c
    src/provider_source.c
    src/player_state.c
    src/queue_loader.c
    src/spectrum.c
    src/track.c
    src/text.c
    src/ui.c
)

# stb_image 为固定版本的 vendored 上游实现，仅对该翻译单元关闭其内部 shadow 告警。
set_source_files_properties(src/image.c PROPERTIES COMPILE_OPTIONS "-Wno-shadow")

target_include_directories(cardputer_music_player PRIVATE
    src
    third_party/jsmn
    third_party/stb
    ${MPG123_INCLUDE_DIR}
)
target_compile_options(cardputer_music_player PRIVATE
    -Wall
    -Wextra
    -Werror
    -Wformat=2
    -Wshadow
)
target_link_libraries(cardputer_music_player PRIVATE
    ALSA::ALSA
    CURL::libcurl
    Freetype::Freetype
    ${MPG123_LIBRARY}
    ${QRENCODE_LIBRARY}
    ${CRYPTO_LIBRARY}
    m
    pthread
)

install(TARGETS cardputer_music_player DESTINATION bin)
