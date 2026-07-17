#pragma once

#include <pthread.h>
#include <stddef.h>

#include "track.h"

#define QUEUE_LOADER_ERROR_SIZE 160

typedef int (*queue_loader_callback_t)(
    void *context, track_list_t *tracks,
    char *error, size_t error_size
);

typedef struct {
    pthread_t thread;
    pthread_mutex_t lock;
    queue_loader_callback_t callback;
    void *context;
    track_list_t tracks;
    char error[QUEUE_LOADER_ERROR_SIZE];
    int result;
    int done;
    int started;
} queue_loader_t;

int queue_loader_start(queue_loader_t *loader,
                       queue_loader_callback_t callback,
                       void *context);
int queue_loader_is_done(queue_loader_t *loader);
int queue_loader_finish(queue_loader_t *loader,
                        track_list_t *tracks,
                        char *error, size_t error_size);
