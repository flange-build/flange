/**
  * Copyright (c) 2023 Rockchip Electronics Co., Ltd
  *
  * SPDX-License-Identifier: Apache-2.0
  */

#include "aupipe.h"

#define DOT_FILE_HEADER \
"digraph aupipe {\n"    \
"  rankdir=LR;\n"       \
"  fontname=sans;\n"    \
"  fontsize=10;\n"      \
"  labelloc=t;\n"       \
"  nodesep=.1;\n"       \
"  ranksep=.2;\n"       \
"  node [style=\"filled,rounded\" shape=box fontsize=9 fontname=sans];\n"\
"  edge [labelfontsize=6 fontsize=9 fontname=monospace];\n"
#define DOT_FILE_OBJ_HEADER         \
"  subgraph cluster_%s {\n"         \
"    color=black;\n"                \
"    fillcolor=\"#aaffaa\";\n"      \
"    style=\"filled,rounded\";\n"   \
"    label=\"%s @ %p\";\n"
#define DOT_FILE_SRC_PAD \
"    %s_src_pad_%d [color=black height=0.2 style=filled fillcolor=\"#ffaaaa\" label=\"src_pad %d\\ndirection: source\\n\"];\n"
#define DOT_FILE_SINK_PAD \
"    %s_sink_pad_%d [color=black height=0.2 style=filled fillcolor=\"#aaaaff\" label=\"sink_pad %d\\ndirection: sink\\n\"];\n"
#define DOT_FILE_SRC_PAD_FAKE \
"    %s_src_pad_%d [color=black height=0.2 style=invis fillcolor=\"#ffaaaa\" label=\"src_pad %d\\ndirection: source\\n\"];\n"
#define DOT_FILE_SINK_PAD_FAKE \
"    %s_sink_pad_%d [color=black height=0.2 style=invis fillcolor=\"#aaaaff\" label=\"sink_pad %d\\ndirection: sink\\n\"];\n"
#define DOT_FILE_PAD_LINK_FAKE \
"    %s_sink_pad_%d->%s_src_pad_%d [style=invis]\n"
#define DOT_FILE_PAD_LINK \
"    %s_src_pad_%d->%s_sink_pad_%d\n"

#define PRINTF(fmt, ...)                \
do {                                    \
    if (fd)                             \
        fprintf(fd, fmt, ##__VA_ARGS__);\
    else                                \
        printf(fmt, ##__VA_ARGS__);     \
} while (0);

void aupipe_to_dot_file(Aupipe *pipe, char *file)
{
    ApList *list;
    ApList *last;
    ApObject *obj;
    ApPad *pad;
    ApPad *peer_pad;
    int srcpad, sinkpad;
    FILE *fd = fopen(file, "wb+");
    int i;

    PRINTF(DOT_FILE_HEADER);

    list = &pipe->objs;
    last = pipe->objs.last;
    do
    {
        list = list->next;
        obj = (ApObject *)list->data;
        PRINTF(DOT_FILE_OBJ_HEADER, obj->name, obj->name, obj);
        i = 0;
        while (1)
        {
            pad = obj->get_pad(obj, PAD_TYPE_SINK, i);
            if (!pad)
                break;
            PRINTF(DOT_FILE_SINK_PAD, obj->name, i, i);
            i++;
            if (i >= 32)
            {
                printf("the pad numbers is insane\n");
                break;
            }
        }
        srcpad = i;
        i = 0;
        while (1)
        {
            pad = obj->get_pad(obj, PAD_TYPE_SRC, i);
            if (!pad)
                break;
            PRINTF(DOT_FILE_SRC_PAD, obj->name, i, i);
            i++;
            if (i >= 32)
            {
                printf("the pad numbers is insane\n");
                break;
            }
        }
        sinkpad = i;
        if (srcpad && sinkpad)
        {
            if (srcpad != sinkpad)
            {
                if (srcpad > sinkpad)
                    for (; sinkpad < srcpad; sinkpad++)
                        PRINTF(DOT_FILE_SINK_PAD_FAKE, obj->name, sinkpad, sinkpad);
                if (srcpad < sinkpad)
                    for (; srcpad < sinkpad; srcpad++)
                        PRINTF(DOT_FILE_SRC_PAD_FAKE, obj->name, srcpad, srcpad);
            }
            for (i = 0; i < srcpad; i++)
                PRINTF(DOT_FILE_PAD_LINK_FAKE, obj->name, i, obj->name, i);
        }
        PRINTF("  }\n");
    }
    while (list != last);

    list = &pipe->objs;
    last = pipe->objs.last;
    do
    {
        list = list->next;
        obj = (ApObject *)list->data;
        i = 0;
        while (1)
        {
            pad = obj->get_pad(obj, PAD_TYPE_SRC, i);
            if (!pad)
                break;
            peer_pad = pad->peer;
            if (peer_pad)
                PRINTF(DOT_FILE_PAD_LINK, obj->name, i,
                       peer_pad->parent->name, peer_pad->id);
            i++;
            if (i >= 32)
            {
                printf("the pad numbers is insane\n");
                break;
            }
        }
    }
    while (list != last);
    PRINTF("}\n");

    if (fd)
        fclose(fd);
}

