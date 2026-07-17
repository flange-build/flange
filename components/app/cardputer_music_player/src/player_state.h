#pragma once

#include <stddef.h>
#include <stdint.h>

typedef struct {
    size_t current_index;
    size_t queue_count;
    unsigned underruns;
    unsigned media_retry_count;
    uint64_t degraded_until_ms;
    uint64_t media_retry_at_ms;
} player_state_t;

void player_state_reset(player_state_t *state, size_t queue_count);
size_t player_state_move(player_state_t *state, int direction);
void player_state_note_underruns(player_state_t *state,
                                 unsigned underruns, uint64_t now_ms);
void player_state_note_buffer_risk(player_state_t *state, uint64_t now_ms);
unsigned player_state_target_fps(const player_state_t *state,
                                 unsigned configured_fps,
                                 uint64_t now_ms);
void player_state_schedule_media_retry(player_state_t *state,
                                       uint64_t now_ms);
void player_state_schedule_queue_retry(player_state_t *state,
                                       uint64_t now_ms);
int player_state_media_retry_due(const player_state_t *state,
                                 uint64_t now_ms);
void player_state_clear_media_retry(player_state_t *state);
