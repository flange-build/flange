#include <assert.h>
#include <stdio.h>

#include "player_state.h"

int main(void)
{
    player_state_t state;
    player_state_reset(&state, 3);
    assert(state.current_index == 0);
    assert(player_state_move(&state, -1) == 2);
    assert(player_state_move(&state, 1) == 0);
    assert(player_state_move(&state, 1) == 1);

    player_state_note_underruns(&state, 1, 1000);
    assert(player_state_target_fps(&state, 12, 3999) == 5);
    assert(player_state_target_fps(&state, 12, 4000) == 12);
    player_state_note_underruns(&state, 2, 5000);
    assert(player_state_target_fps(&state, 10, 6000) == 5);
    player_state_note_buffer_risk(&state, 8000);
    assert(player_state_target_fps(&state, 10, 10999) == 5);
    assert(player_state_target_fps(&state, 10, 11000) == 10);

    player_state_schedule_media_retry(&state, 1000);
    assert(state.media_retry_count == 1);
    assert(!player_state_media_retry_due(&state, 5999));
    assert(player_state_media_retry_due(&state, 6000));
    player_state_schedule_media_retry(&state, 6000);
    assert(state.media_retry_count == 2);
    assert(player_state_media_retry_due(&state, 16000));
    player_state_schedule_media_retry(&state, 16000);
    assert(state.media_retry_count == 3);
    assert(player_state_media_retry_due(&state, 36000));
    player_state_schedule_media_retry(&state, 36000);
    assert(state.media_retry_at_ms == 0);
    player_state_clear_media_retry(&state);
    assert(state.media_retry_count == 0);
    assert(state.media_retry_at_ms == 0);

    player_state_schedule_queue_retry(&state, 1000);
    assert(state.media_retry_count == 1);
    assert(!player_state_media_retry_due(&state, 1999));
    assert(player_state_media_retry_due(&state, 2000));
    player_state_schedule_queue_retry(&state, 2000);
    assert(state.media_retry_count == 2);
    assert(player_state_media_retry_due(&state, 5000));
    player_state_schedule_queue_retry(&state, 5000);
    assert(state.media_retry_count == 3);
    assert(player_state_media_retry_due(&state, 15000));
    puts("player state tests passed");
    return 0;
}
