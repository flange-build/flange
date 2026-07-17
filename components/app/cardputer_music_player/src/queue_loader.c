#include "queue_loader.h"

#include <stdio.h>
#include <string.h>

static void *queue_loader_worker(void *opaque)
{
    queue_loader_t *loader = opaque;
    track_list_t tracks = {0};
    char error[QUEUE_LOADER_ERROR_SIZE] = {0};
    int result = loader->callback(
        loader->context, &tracks, error, sizeof(error)
    );

    pthread_mutex_lock(&loader->lock);
    loader->tracks = tracks;
    loader->result = result;
    snprintf(loader->error, sizeof(loader->error), "%s", error);
    loader->done = 1;
    pthread_mutex_unlock(&loader->lock);
    return NULL;
}

int queue_loader_start(queue_loader_t *loader,
                       queue_loader_callback_t callback,
                       void *context)
{
    if (loader == NULL || callback == NULL)
        return -1;
    memset(loader, 0, sizeof(*loader));
    loader->callback = callback;
    loader->context = context;
    if (pthread_mutex_init(&loader->lock, NULL) != 0)
        return -1;
    if (pthread_create(
            &loader->thread, NULL,
            queue_loader_worker, loader) != 0) {
        pthread_mutex_destroy(&loader->lock);
        return -1;
    }
    loader->started = 1;
    return 0;
}

int queue_loader_is_done(queue_loader_t *loader)
{
    if (loader == NULL || !loader->started)
        return 1;
    pthread_mutex_lock(&loader->lock);
    int done = loader->done;
    pthread_mutex_unlock(&loader->lock);
    return done;
}

int queue_loader_finish(queue_loader_t *loader,
                        track_list_t *tracks,
                        char *error, size_t error_size)
{
    if (loader == NULL || !loader->started || tracks == NULL
            || error == NULL || error_size == 0U)
        return -1;
    if (pthread_join(loader->thread, NULL) != 0) {
        snprintf(error, error_size, "无法等待在线列表加载线程");
        pthread_mutex_destroy(&loader->lock);
        loader->started = 0;
        return -1;
    }

    pthread_mutex_lock(&loader->lock);
    *tracks = loader->tracks;
    int result = loader->result;
    snprintf(error, error_size, "%s", loader->error);
    pthread_mutex_unlock(&loader->lock);
    pthread_mutex_destroy(&loader->lock);
    loader->started = 0;
    return result;
}
