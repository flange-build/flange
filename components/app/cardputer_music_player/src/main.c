#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

#include "audio.h"
#include "config.h"
#include "decoder.h"
#include "framebuffer.h"
#include "input.h"
#include "manifest.h"
#include "media.h"
#include "netease.h"
#include "netease_official.h"
#include "provider.h"
#include "player_state.h"
#include "queue_loader.h"
#include "spectrum.h"
#include "track.h"
#include "ui.h"

#define DEFAULT_CONFIG_PATH "/etc/cardputer_music_player/config.json"

static volatile sig_atomic_t stop_requested;
static volatile sig_atomic_t degrade_test_requested;

static void on_signal(int signal_number)
{
    (void)signal_number;
    stop_requested = 1;
}

static void on_degrade_test_signal(int signal_number)
{
    (void)signal_number;
    degrade_test_requested = 1;
}

static uint64_t monotonic_ms(void)
{
    struct timespec time;
    clock_gettime(CLOCK_MONOTONIC, &time);
    return (uint64_t)time.tv_sec * 1000U
        + (uint64_t)time.tv_nsec / 1000000U;
}

static int uses_netease_official(const app_config_t *config)
{
    return strcmp(config->provider, "netease_official") == 0;
}

static void render_static_page(framebuffer_t *framebuffer, ui_state_t *ui)
{
    int16_t samples[SPECTRUM_SAMPLES] = {0};
    spectrum_frame_t spectrum = {0};
    ui_tick(ui, monotonic_ms());
    ui_render(framebuffer, ui, &spectrum, samples, SPECTRUM_SAMPLES,
              0U, 1);
}

static int ensure_netease_login(const app_config_t *config,
                                framebuffer_t *framebuffer,
                                input_device_t *input, int input_ready,
                                ui_state_t *ui,
                                char *error, size_t error_size)
{
    if (!uses_netease_official(config))
        return 0;

    netease_official_session_t session;
    int loaded = netease_official_load_session(config, &session,
                                                error, error_size);
    if (loaded == 0) {
        fprintf(stderr, "[netease] 使用已保存的官方登录 session\n");
        return 0;
    }
    if (loaded < 0)
        fprintf(stderr, "[netease] 忽略无效 session: %s\n", error);

    while (!stop_requested) {
        ui_set_status(ui, "正在申请网易云登录二维码");
        ui_show_page(ui, UI_PAGE_LOADING, monotonic_ms());
        render_static_page(framebuffer, ui);
        if (netease_official_begin_login(config, &session,
                                         error, error_size) != 0)
            return -1;
        if (ui_set_login_qr(ui, session.qr_url, "等待扫码") != 0) {
            snprintf(error, error_size, "网易云登录二维码生成失败");
            return -1;
        }
        ui_show_page(ui, UI_PAGE_LOGIN_QR, monotonic_ms());
        fprintf(stderr, "[netease] 二维码已生成，等待手机扫码\n");

        uint64_t next_poll_ms = 0U;
        int expired = 0;
        while (!stop_requested) {
            if (input_ready) {
                input_action_t action;
                while ((action = input_poll(input)) != INPUT_ACTION_NONE) {
                    if (action == INPUT_ACTION_REFRESH)
                        goto regenerate;
                }
            }

            uint64_t now_ms = monotonic_ms();
            if (!expired && now_ms >= next_poll_ms) {
                netease_qr_status_t status;
                if (netease_official_poll_login(config, &session, &status,
                                                error, error_size) != 0)
                    return -1;
                next_poll_ms = now_ms + 2500U;
                if (status == NETEASE_QR_WAITING) {
                    ui_set_status(ui, "等待扫码");
                } else if (status == NETEASE_QR_CONFIRMING) {
                    ui_set_status(ui, "请在手机上确认登录");
                } else if (status == NETEASE_QR_SUCCESS) {
                    ui_set_status(ui, "登录成功");
                    render_static_page(framebuffer, ui);
                    if (netease_official_save_session(
                            config, &session, error, error_size) != 0)
                        return -1;
                    fprintf(stderr, "[netease] 官方登录成功，session 已保存\n");
                    usleep(600000U);
                    return 0;
                } else if (status == NETEASE_QR_EXPIRED) {
                    expired = 1;
                    ui_set_status(ui, "二维码已过期 / 按 R 更新");
                } else {
                    ui_set_status(ui, "登录状态未知 / 按 R 更新");
                }
            }
            render_static_page(framebuffer, ui);
            usleep(50000U);
        }
regenerate:
        fprintf(stderr, "[netease] 正在重新生成登录二维码\n");
    }
    snprintf(error, error_size, "网易云登录已停止");
    return -1;
}

static int handle_input(input_action_t action, audio_engine_t *audio,
                        int audio_ready, ui_state_t *ui)
{
    switch (action) {
    case INPUT_ACTION_TOGGLE:
        if (audio_ready)
            audio_toggle_pause(audio);
        break;
    case INPUT_ACTION_SELECT:
        if (ui->page == UI_PAGE_QUEUE)
            return 3;
        break;
    case INPUT_ACTION_PREVIOUS:
        return -1;
    case INPUT_ACTION_NEXT:
        return 1;
    case INPUT_ACTION_UP:
        if (ui->page != UI_PAGE_QUEUE)
            ui_show_page(ui, UI_PAGE_QUEUE, monotonic_ms());
        else
            ui_move_queue_selection(ui, -1);
        break;
    case INPUT_ACTION_DOWN:
        if (ui->page != UI_PAGE_QUEUE)
            ui_show_page(ui, UI_PAGE_QUEUE, monotonic_ms());
        else
            ui_move_queue_selection(ui, 1);
        break;
    case INPUT_ACTION_VISUALIZER:
        ui->visualizer_mode = (ui->visualizer_mode + 1) % 2;
        break;
    case INPUT_ACTION_QUEUE:
        ui_show_page(ui,
                     ui->page == UI_PAGE_QUEUE
                         ? UI_PAGE_NOW_PLAYING : UI_PAGE_QUEUE,
                     monotonic_ms());
        break;
    case INPUT_ACTION_SOURCE:
        ui_show_page(ui,
                     ui->page == UI_PAGE_SOURCE
                         ? UI_PAGE_NOW_PLAYING : UI_PAGE_SOURCE,
                     monotonic_ms());
        break;
    case INPUT_ACTION_REFRESH:
        return 2;
    case INPUT_ACTION_BACK:
        ui_show_page(ui, UI_PAGE_NOW_PLAYING, monotonic_ms());
        break;
    case INPUT_ACTION_NONE:
        break;
    }
    return 0;
}

static int load_configured_queue(const app_config_t *config,
                                 track_list_t *tracks,
                                 char *error, size_t error_size)
{
    if (uses_netease_official(config))
        return netease_official_load_recommendations(
            config, tracks, error, error_size
        );
    if (strcmp(config->provider, "netease") == 0)
        return netease_load_playlist(config, tracks, error, error_size);
    if (strcmp(config->provider, "douyin") == 0
            || config->douyin_broker_url[0] != '\0'
            || config->douyin_api_url[0] != '\0') {
        int result = provider_load_douyin(config, tracks,
                                          error, error_size);
        if (result != 0)
            return result;
        if (config->resolver_url[0] != '\0'
                && provider_apply_resolver(config, tracks,
                                           error, error_size) != 0) {
            fprintf(stderr,
                    "[provider] resolver 不可用，保留仅展示榜单: %s\n",
                    error);
        }
        return 0;
    }
    if (config->manifest_url[0] != '\0') {
        return manifest_load_source(config->manifest_url, tracks,
                                    error, error_size);
    }
    snprintf(error, error_size, "未配置在线内容源或 Manifest");
    return -1;
}

static int load_queue_callback(void *context, track_list_t *tracks,
                               char *error, size_t error_size)
{
    return load_configured_queue(context, tracks, error, error_size);
}

static int load_queue_interactive(
    const app_config_t *config,
    framebuffer_t *framebuffer,
    input_device_t *input, int input_ready,
    audio_engine_t *audio, int audio_ready,
    ui_state_t *ui, track_list_t *tracks,
    char *error, size_t error_size)
{
    queue_loader_t loader;
    if (queue_loader_start(
            &loader, load_queue_callback, (void *)config) != 0) {
        fprintf(stderr,
                "[provider] 无法启动后台加载线程，改为同步加载\n");
        return load_configured_queue(
            config, tracks, error, error_size
        );
    }

    uint64_t started_ms = monotonic_ms();
    ui_show_page(ui, UI_PAGE_LOADING, started_ms);
    while (!stop_requested && !queue_loader_is_done(&loader)) {
        if (input_ready) {
            input_action_t action;
            while ((action = input_poll(input)) != INPUT_ACTION_NONE) {
                if (action == INPUT_ACTION_TOGGLE
                        || action == INPUT_ACTION_VISUALIZER) {
                    (void)handle_input(
                        action, audio, audio_ready, ui
                    );
                }
            }
        }

        uint64_t now_ms = monotonic_ms();
        char status[96];
        snprintf(
            status, sizeof(status),
            uses_netease_official(config)
                ? "正在读取我喜欢的音乐 · %llu 秒"
                : "正在加载在线歌单 · %llu 秒",
            (unsigned long long)((now_ms - started_ms) / 1000U)
        );
        ui_set_status(ui, status);

        int16_t samples[SPECTRUM_SAMPLES] = {0};
        spectrum_frame_t spectrum = {0};
        if (audio_ready) {
            audio_recent_samples(audio, samples, SPECTRUM_SAMPLES);
            spectrum_compute(samples, SPECTRUM_SAMPLES, &spectrum);
        }
        ui_tick(ui, now_ms);
        ui_render(
            framebuffer, ui, &spectrum,
            samples, SPECTRUM_SAMPLES,
            audio_ready ? audio_position_ms(audio) : 0U,
            audio_ready ? audio_is_paused(audio) : 1
        );
        usleep(100000U);
    }

    int result = queue_loader_finish(
        &loader, tracks, error, error_size
    );
    uint64_t elapsed_ms = monotonic_ms() - started_ms;
    fprintf(stderr,
            "[provider] 在线列表后台加载完成，耗时 %llu ms\n",
            (unsigned long long)elapsed_ms);
    if (stop_requested) {
        snprintf(error, error_size, "播放器正在退出");
        return -1;
    }
    return result;
}

static int prepare_current_track(ui_state_t *ui, audio_engine_t *audio,
                                 int audio_ready, const track_t *track)
{
    char error[160] = {0};
    if (audio_ready) {
        audio_fade_out(audio, 80U);
        audio_clear_media(audio);
    }
    ui_set_track(ui, track);
    ui_set_status(ui, "");
    int result = 0;
    if (track->audio_url[0] == '\0') {
        ui_set_status(
            ui, track->audio_resolved
                ? "仅展示 / 无可播放地址"
                : "播放地址待加载 / 按 E 重试"
        );
        result = 1;
    } else if (!audio_ready) {
        ui_set_status(ui, "音频设备不可用");
        result = 1;
    } else {
        decoded_audio_t decoded;
        if (media_load_audio(track->audio_url, &decoded,
                             error, sizeof(error)) != 0) {
            fprintf(stderr, "[media] %s\n", error);
            ui_set_status(ui, "音频加载失败 / 可按 R 重试");
            result = 1;
        } else {
            if (audio_play_pcm(
                    audio, decoded.samples, decoded.count) != 0) {
                ui_set_status(ui, "PCM 缓冲不足 / 播放已停止");
                result = 1;
            }
            decoder_audio_free(&decoded);
        }
    }

    if (track->cover_url[0] != '\0') {
        uint16_t cover[COVER_WIDTH * COVER_HEIGHT];
        uint16_t theme_color = 0;
        if (media_load_cover(track->cover_url, cover, &theme_color,
                             error, sizeof(error)) == 0) {
            ui_set_cover(ui, cover, theme_color);
        } else {
            fprintf(stderr, "[cover] %s\n", error);
        }
    }
    return result;
}

static size_t activate_from_index(ui_state_t *ui, audio_engine_t *audio,
                                  int audio_ready,
                                  const app_config_t *config,
                                  track_list_t *tracks,
                                  size_t start_index, int *activated)
{
    *activated = 0;
    track_t *requested = &tracks->items[start_index];
    if (!requested->audio_resolved
            && uses_netease_official(config)) {
        char error[160] = {0};
        fprintf(stderr,
                "[netease] 按需加载曲目 %zu 的播放地址\n",
                start_index + 1U);
        if (netease_official_resolve_track(
                config, requested, error, sizeof(error)) < 0) {
            fprintf(stderr,
                    "[netease] 按需播放地址暂不可用: %s\n",
                    error);
        }
    }
    for (size_t offset = 0; offset < tracks->count; offset++) {
        size_t index = (start_index + offset) % tracks->count;
        if (tracks->items[index].audio_url[0] == '\0')
            continue;
        if (prepare_current_track(ui, audio, audio_ready,
                                  &tracks->items[index]) == 0) {
            *activated = 1;
            return index;
        }
    }
    (void)prepare_current_track(ui, audio, audio_ready,
                                &tracks->items[start_index]);
    ui_set_status(ui, "全队列不可播放 / 按 R 重试");
    return start_index;
}

static int is_https_track(const track_t *track)
{
    return strncmp(track->audio_url, "https://", 8) == 0;
}

static void update_media_retry(player_state_t *state, int activated,
                               const track_t *track, uint64_t now_ms)
{
    player_state_clear_media_retry(state);
    if (!activated && is_https_track(track)) {
        player_state_schedule_media_retry(state, now_ms);
        fprintf(stderr, "[media] 在线音频将在 5 秒后重试\n");
    }
}

int main(int argc, char **argv)
{
    framebuffer_t framebuffer;
    input_device_t input;
    audio_engine_t audio;
    ui_state_t ui;
    int audio_ready = 0;
    int input_ready = 0;
    app_config_t config;
    track_list_t tracks;
    char startup_status[160] = {0};
    const char *config_path = DEFAULT_CONFIG_PATH;
    player_state_t player_state;
    unsigned last_target_fps;
    int activated = 0;

    if (argc == 2 && strcmp(argv[1], "--restore-tty") == 0)
        return framebuffer_restore_tty() == 0 ? 0 : 1;
    if (argc == 3 && strcmp(argv[1], "--config") == 0)
        config_path = argv[2];
    else if (argc != 1) {
        fprintf(stderr,
                "用法: %s [--config /absolute/config.json|--restore-tty]\n",
                argv[0]);
        return 2;
    }

    signal(SIGINT, on_signal);
    signal(SIGTERM, on_signal);
    signal(SIGUSR1, on_degrade_test_signal);
    signal(SIGPIPE, SIG_IGN);

    if (config_load_file(config_path, &config,
                         startup_status, sizeof(startup_status)) != 0) {
        fprintf(stderr, "[config] %s；使用默认网易云配置\n",
                startup_status);
        config_defaults(&config);
    }
    memset(&tracks, 0, sizeof(tracks));

    if (framebuffer_open_gud(&framebuffer) != 0)
        return 1;
    ui_init(&ui);
    ui.visualizer_mode = strcmp(config.visualizer, "waveform") == 0 ? 1 : 0;
    ui_set_status(&ui, "加载歌单与播放地址");
    ui_tick(&ui, monotonic_ms());
    int16_t initial_samples[SPECTRUM_SAMPLES] = {0};
    spectrum_frame_t initial_spectrum = {0};
    ui_render(&framebuffer, &ui, &initial_spectrum,
              initial_samples, SPECTRUM_SAMPLES, 0U, 1);

    if (input_open_cardputer(&input) == 0)
        input_ready = 1;
    if (audio_start(&audio) == 0)
        audio_ready = 1;
    player_state_reset(&player_state, 0U);
    startup_status[0] = '\0';
    if (ensure_netease_login(&config, &framebuffer, &input, input_ready,
                             &ui, startup_status,
                             sizeof(startup_status)) != 0
            || load_queue_interactive(
                &config, &framebuffer, &input, input_ready,
                &audio, audio_ready, &ui, &tracks,
                startup_status, sizeof(startup_status)) != 0
            || tracks.count == 0U) {
        if (startup_status[0] == '\0')
            snprintf(startup_status, sizeof(startup_status), "在线歌单为空");
        fprintf(stderr, "[provider] %s\n", startup_status);
        ui_set_status(&ui, startup_status);
        ui_show_page(&ui, UI_PAGE_ERROR, monotonic_ms());
        player_state_schedule_queue_retry(&player_state, monotonic_ms());
    } else {
        player_state_reset(&player_state, tracks.count);
        ui_set_queue(&ui, &tracks, 0U);
        ui_show_page(&ui, UI_PAGE_QUEUE, monotonic_ms());
        render_static_page(&framebuffer, &ui);
        player_state.current_index = activate_from_index(
            &ui, &audio, audio_ready, &config,
            &tracks, 0U, &activated
        );
        update_media_retry(&player_state, activated,
                           &tracks.items[player_state.current_index],
                           monotonic_ms());
        ui_set_queue(&ui, &tracks, player_state.current_index);
        ui_show_page(&ui, activated ? UI_PAGE_NOW_PLAYING : UI_PAGE_ERROR,
                     monotonic_ms());
    }
    last_target_fps = config.fps;

    fprintf(stderr, "[player] Cardputer Music Player 0.1.0 运行中\n");
    while (!stop_requested) {
        struct timespec started;
        struct timespec ended;
        int16_t samples[SPECTRUM_SAMPLES] = {0};
        spectrum_frame_t spectrum = {0};

        clock_gettime(CLOCK_MONOTONIC, &started);
        if (input_ready) {
            input_action_t action;
            while ((action = input_poll(&input)) != INPUT_ACTION_NONE) {
                int command = handle_input(action, &audio,
                                           audio_ready, &ui);
                if ((command == -1 || command == 1) && tracks.count > 0U) {
                    size_t requested_index = player_state_move(
                        &player_state, command
                    );
                    player_state.current_index = activate_from_index(
                        &ui, &audio, audio_ready, &config,
                        &tracks, requested_index, &activated
                    );
                    update_media_retry(
                        &player_state, activated,
                        &tracks.items[player_state.current_index],
                        monotonic_ms()
                    );
                    ui_set_queue(&ui, &tracks,
                                 player_state.current_index);
                    ui_show_page(&ui,
                                 activated ? UI_PAGE_NOW_PLAYING
                                           : UI_PAGE_ERROR,
                                 monotonic_ms());
                } else if (command == 3 && tracks.count > 0U
                           && ui.page == UI_PAGE_QUEUE) {
                    size_t requested_index = ui_queue_selection(&ui);
                    player_state.current_index = requested_index;
                    player_state.current_index = activate_from_index(
                        &ui, &audio, audio_ready, &config,
                        &tracks, requested_index, &activated
                    );
                    update_media_retry(
                        &player_state, activated,
                        &tracks.items[player_state.current_index],
                        monotonic_ms()
                    );
                    ui_set_queue(&ui, &tracks,
                                 player_state.current_index);
                    ui_show_page(&ui,
                                 activated ? UI_PAGE_NOW_PLAYING
                                           : UI_PAGE_ERROR,
                                 monotonic_ms());
                } else if (command == 2) {
                    track_list_t refreshed;
                    char refresh_error[160] = {0};
                    ui_set_status(&ui, "正在刷新在线歌单");
                    ui_show_page(&ui, UI_PAGE_LOADING, monotonic_ms());
                    ui_tick(&ui, monotonic_ms());
                    ui_render(&framebuffer, &ui, &spectrum,
                              samples, SPECTRUM_SAMPLES,
                              audio_ready
                                  ? audio_position_ms(&audio) : 0U,
                              audio_ready
                                  ? audio_is_paused(&audio) : 1);
                    if (ensure_netease_login(
                            &config, &framebuffer, &input, input_ready,
                            &ui, refresh_error, sizeof(refresh_error)) == 0
                            && load_queue_interactive(
                                &config, &framebuffer, &input, input_ready,
                                &audio, audio_ready, &ui, &refreshed,
                                refresh_error,
                                sizeof(refresh_error)) == 0
                            && refreshed.count > 0U) {
                        tracks = refreshed;
                        player_state_reset(&player_state, tracks.count);
                        ui_set_queue(&ui, &tracks, 0U);
                        ui_show_page(
                            &ui, UI_PAGE_QUEUE, monotonic_ms()
                        );
                        render_static_page(&framebuffer, &ui);
                        player_state.current_index = activate_from_index(
                            &ui, &audio, audio_ready, &config,
                            &tracks, 0U, &activated
                        );
                        update_media_retry(
                            &player_state, activated,
                            &tracks.items[player_state.current_index],
                            monotonic_ms()
                        );
                        ui_set_queue(&ui, &tracks,
                                     player_state.current_index);
                        ui_show_page(
                            &ui, activated ? UI_PAGE_NOW_PLAYING
                                           : UI_PAGE_ERROR,
                            monotonic_ms()
                        );
                    } else {
                        if (refresh_error[0] == '\0')
                            snprintf(refresh_error,
                                     sizeof(refresh_error),
                                     "在线歌单为空");
                        fprintf(stderr, "[provider] 刷新失败: %s\n",
                                refresh_error);
                        ui_set_status(&ui, refresh_error);
                        ui_show_page(&ui, UI_PAGE_ERROR,
                                     monotonic_ms());
                    }
                }
            }
        }
        if (tracks.count == 0U
                && player_state_media_retry_due(&player_state,
                                                monotonic_ms())) {
            track_list_t refreshed;
            char retry_error[160] = {0};
            fprintf(stderr, "[provider] 正在重试在线歌单（第 %u/3 次）\n",
                    player_state.media_retry_count);
            ui_set_status(&ui, "正在重试在线歌单");
            ui_show_page(&ui, UI_PAGE_LOADING, monotonic_ms());
            if (load_queue_interactive(
                    &config, &framebuffer, &input, input_ready,
                    &audio, audio_ready, &ui, &refreshed,
                    retry_error, sizeof(retry_error)) == 0
                    && refreshed.count > 0U) {
                tracks = refreshed;
                player_state_reset(&player_state, tracks.count);
                ui_set_queue(&ui, &tracks, 0U);
                ui_show_page(&ui, UI_PAGE_QUEUE, monotonic_ms());
                render_static_page(&framebuffer, &ui);
                player_state.current_index = activate_from_index(
                    &ui, &audio, audio_ready, &config,
                    &tracks, 0U, &activated
                );
                update_media_retry(
                    &player_state, activated,
                    &tracks.items[player_state.current_index],
                    monotonic_ms()
                );
                ui_set_queue(&ui, &tracks, player_state.current_index);
                ui_show_page(&ui,
                             activated ? UI_PAGE_NOW_PLAYING
                                       : UI_PAGE_ERROR,
                             monotonic_ms());
            } else {
                if (retry_error[0] == '\0')
                    snprintf(retry_error, sizeof(retry_error),
                             "在线歌单为空");
                ui_set_status(&ui, retry_error);
                ui_show_page(&ui, UI_PAGE_ERROR, monotonic_ms());
                player_state_schedule_queue_retry(
                    &player_state, monotonic_ms()
                );
            }
        }
        if (tracks.count > 0U
                && player_state_media_retry_due(&player_state,
                                                monotonic_ms())) {
            const track_t *track = &tracks.items[player_state.current_index];
            fprintf(stderr, "[media] 正在重试在线音频（第 %u/3 次）\n",
                    player_state.media_retry_count);
            if (prepare_current_track(&ui, &audio, audio_ready, track) == 0) {
                player_state_clear_media_retry(&player_state);
                ui_show_page(&ui, UI_PAGE_NOW_PLAYING, monotonic_ms());
                fprintf(stderr, "[media] 在线音频重试成功\n");
            } else {
                player_state_schedule_media_retry(
                    &player_state, monotonic_ms()
                );
                ui_show_page(&ui, UI_PAGE_ERROR, monotonic_ms());
            }
        }
        if (audio_ready && tracks.count > 0U
                && audio_take_finished(&audio)) {
            size_t requested_index = player_state_move(&player_state, 1);
            fprintf(stderr, "[player] 当前曲目播放完成，切换下一首\n");
            player_state.current_index = activate_from_index(
                &ui, &audio, audio_ready, &config,
                &tracks, requested_index, &activated
            );
            update_media_retry(
                &player_state, activated,
                &tracks.items[player_state.current_index],
                monotonic_ms()
            );
            ui_set_queue(&ui, &tracks, player_state.current_index);
            ui_show_page(&ui,
                         activated ? UI_PAGE_NOW_PLAYING : UI_PAGE_ERROR,
                         monotonic_ms());
        }
        if (audio_ready) {
            audio_recent_samples(&audio, samples, SPECTRUM_SAMPLES);
            spectrum_compute(samples, SPECTRUM_SAMPLES, &spectrum);
        }
        ui_tick(&ui, monotonic_ms());
        ui_render(&framebuffer, &ui, &spectrum,
                  samples, SPECTRUM_SAMPLES,
                  audio_ready ? audio_position_ms(&audio) : 0,
                  audio_ready ? audio_is_paused(&audio) : 1);

        clock_gettime(CLOCK_MONOTONIC, &ended);
        long elapsed_us = (ended.tv_sec - started.tv_sec) * 1000000L
            + (ended.tv_nsec - started.tv_nsec) / 1000L;
        unsigned target_fps = config.fps;
        uint64_t now_ms = monotonic_ms();
        if (degrade_test_requested) {
            degrade_test_requested = 0;
            player_state_note_buffer_risk(&player_state, now_ms);
            fprintf(stderr,
                    "[audio] 验收注入低缓冲风险，优先保障音频\n");
        }
        if (audio_ready)
            player_state_note_underruns(
                &player_state, audio_get_underruns(&audio), now_ms
            );
        target_fps = player_state_target_fps(
            &player_state, target_fps, now_ms
        );
        if (target_fps != last_target_fps) {
            fprintf(stderr, "[ui] 可视化帧率调整为 %u FPS\n",
                    target_fps);
            last_target_fps = target_fps;
        }
        long frame_us = 1000000L / (long)target_fps;
        if (elapsed_us < frame_us)
            usleep((useconds_t)(frame_us - elapsed_us));
    }

    fprintf(stderr, "[player] 正在恢复设备状态\n");
    if (audio_ready)
        audio_stop(&audio);
    if (input_ready)
        input_close(&input);
    ui_close(&ui);
    framebuffer_close(&framebuffer);
    return 0;
}
