#include "player_state.h"

#include <string.h>

void player_state_reset(player_state_t *state, size_t queue_count)
{
    memset(state, 0, sizeof(*state));
    state->queue_count = queue_count;
}

size_t player_state_move(player_state_t *state, int direction)
{
    if (state->queue_count == 0U)
        return 0U;
    if (direction < 0) {
        state->current_index = state->current_index == 0U
            ? state->queue_count - 1U : state->current_index - 1U;
    } else if (direction > 0) {
        state->current_index = (state->current_index + 1U)
            % state->queue_count;
    }
    return state->current_index;
}

void player_state_note_underruns(player_state_t *state,
                                 unsigned underruns, uint64_t now_ms)
{
    if (underruns != state->underruns) {
        state->underruns = underruns;
        state->degraded_until_ms = now_ms + 3000U;
    }
}

void player_state_note_buffer_risk(player_state_t *state, uint64_t now_ms)
{
    state->degraded_until_ms = now_ms + 3000U;
}

unsigned player_state_target_fps(const player_state_t *state,
                                 unsigned configured_fps,
                                 uint64_t now_ms)
{
    return now_ms < state->degraded_until_ms ? 5U : configured_fps;
}

static void schedule_retry(player_state_t *state, uint64_t now_ms,
                           const uint64_t *delays_ms, size_t count)
{
    if (state->media_retry_count >= count) {
        state->media_retry_at_ms = 0U;
        return;
    }
    state->media_retry_at_ms = now_ms + delays_ms[state->media_retry_count];
    state->media_retry_count++;
}

void player_state_schedule_media_retry(player_state_t *state,
                                       uint64_t now_ms)
{
    static const uint64_t delays_ms[] = {5000U, 10000U, 20000U};
    schedule_retry(
        state, now_ms, delays_ms,
        sizeof(delays_ms) / sizeof(delays_ms[0])
    );
}

void player_state_schedule_queue_retry(player_state_t *state,
                                       uint64_t now_ms)
{
    static const uint64_t delays_ms[] = {1000U, 3000U, 10000U};
    schedule_retry(
        state, now_ms, delays_ms,
        sizeof(delays_ms) / sizeof(delays_ms[0])
    );
}

int player_state_media_retry_due(const player_state_t *state,
                                 uint64_t now_ms)
{
    return state->media_retry_at_ms != 0U
        && now_ms >= state->media_retry_at_ms;
}

void player_state_clear_media_retry(player_state_t *state)
{
    state->media_retry_count = 0U;
    state->media_retry_at_ms = 0U;
}
