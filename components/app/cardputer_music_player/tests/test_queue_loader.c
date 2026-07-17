#define _POSIX_C_SOURCE 200809L

#include <assert.h>
#include <stdio.h>
#include <string.h>
#include <time.h>

#include "queue_loader.h"

static int load_fixture(void *context, track_list_t *tracks,
                        char *error, size_t error_size)
{
    (void)context;
    (void)error;
    (void)error_size;
    struct timespec delay = {
        .tv_nsec = 50000000L,
    };
    nanosleep(&delay, NULL);
    tracks->count = 1U;
    snprintf(tracks->items[0].title,
             sizeof(tracks->items[0].title), "后台列表");
    return 0;
}

int main(void)
{
    queue_loader_t loader;
    assert(queue_loader_start(&loader, load_fixture, NULL) == 0);
    assert(queue_loader_is_done(&loader) == 0);

    struct timespec poll_delay = {
        .tv_nsec = 10000000L,
    };
    while (!queue_loader_is_done(&loader))
        nanosleep(&poll_delay, NULL);

    track_list_t tracks = {0};
    char error[QUEUE_LOADER_ERROR_SIZE] = {0};
    assert(queue_loader_finish(
               &loader, &tracks, error, sizeof(error)) == 0);
    assert(error[0] == '\0');
    assert(tracks.count == 1U);
    assert(strcmp(tracks.items[0].title, "后台列表") == 0);
    puts("后台列表加载测试通过");
    return 0;
}
