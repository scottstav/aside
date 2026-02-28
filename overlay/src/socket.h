#ifndef SOCKET_H
#define SOCKET_H

#include <stdbool.h>
#include <stddef.h>
#include <poll.h>

enum overlay_cmd {
    CMD_NONE = 0,
    CMD_OPEN,
    CMD_TEXT,
    CMD_DONE,
    CMD_CLEAR,
    CMD_REPLACE,
};

struct overlay_command {
    enum overlay_cmd cmd;
    char data[4096];
    char conv_id[64];  /* Conversation ID from daemon */
};

struct socket_server {
    int listen_fd;
    int client_fd;
    char read_buf[8192];
    size_t read_len;
    char path[512];
};

bool socket_init(struct socket_server *srv, const char *path);
int socket_get_fds(struct socket_server *srv, struct pollfd *fds, int offset);
bool socket_has_pending(struct socket_server *srv);
bool socket_process(struct socket_server *srv, struct pollfd *fds, int offset,
                    struct overlay_command *cmd);
void socket_cleanup(struct socket_server *srv);

#endif
