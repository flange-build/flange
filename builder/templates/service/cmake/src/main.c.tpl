#include <stdio.h>
#include <unistd.h>
#include <signal.h>

/* ${description} */

static volatile int running = 1;

static void handle_signal(int sig)
{
    (void)sig;
    running = 0;
}

int main(int argc, char *argv[])
{
    signal(SIGTERM, handle_signal);
    signal(SIGINT,  handle_signal);

    printf("${name} service started\n");

    while (running) {
        sleep(1);
    }

    printf("${name} service stopped\n");
    return 0;
}
