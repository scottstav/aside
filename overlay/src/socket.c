#include "socket.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <json-c/json.h>

static bool parse_command(const char *line, struct overlay_command *cmd)
{
    cmd->cmd = CMD_NONE;
    cmd->data[0] = '\0';
    cmd->conv_id[0] = '\0';
    cmd->mode[0] = '\0';

    struct json_object *root = json_tokener_parse(line);
    if (!root)
        return false;

    struct json_object *cmd_obj;
    if (!json_object_object_get_ex(root, "cmd", &cmd_obj)) {
        json_object_put(root);
        return false;
    }

    const char *cmd_str = json_object_get_string(cmd_obj);
    if (strcmp(cmd_str, "open") == 0)         cmd->cmd = CMD_OPEN;
    else if (strcmp(cmd_str, "text") == 0)    cmd->cmd = CMD_TEXT;
    else if (strcmp(cmd_str, "done") == 0)    cmd->cmd = CMD_DONE;
    else if (strcmp(cmd_str, "clear") == 0)   cmd->cmd = CMD_CLEAR;
    else if (strcmp(cmd_str, "replace") == 0) cmd->cmd = CMD_REPLACE;
    else if (strcmp(cmd_str, "listening") == 0) cmd->cmd = CMD_LISTENING;
    else if (strcmp(cmd_str, "thinking") == 0) cmd->cmd = CMD_THINKING;

    struct json_object *data_obj;
    if (json_object_object_get_ex(root, "data", &data_obj)) {
        const char *data_str = json_object_get_string(data_obj);
        if (data_str)
            snprintf(cmd->data, sizeof(cmd->data), "%s", data_str);
    }

    struct json_object *jid;
    if (json_object_object_get_ex(root, "conv_id", &jid))
        snprintf(cmd->conv_id, sizeof(cmd->conv_id), "%s",
                 json_object_get_string(jid));
    else
        cmd->conv_id[0] = '\0';

    struct json_object *jmode;
    if (json_object_object_get_ex(root, "mode", &jmode))
        snprintf(cmd->mode, sizeof(cmd->mode), "%s",
                 json_object_get_string(jmode));

    json_object_put(root);
    return cmd->cmd != CMD_NONE;
}

bool socket_init(struct socket_server *srv, const char *path)
{
    srv->listen_fd = socket(AF_UNIX, SOCK_STREAM, 0);
    if (srv->listen_fd < 0) {
        perror("socket");
        return false;
    }

    unlink(path);

    struct sockaddr_un addr = {0};
    addr.sun_family = AF_UNIX;
    snprintf(addr.sun_path, sizeof(addr.sun_path), "%s", path);

    if (bind(srv->listen_fd, (struct sockaddr *)&addr, sizeof(addr)) < 0) {
        perror("bind");
        close(srv->listen_fd);
        return false;
    }

    if (listen(srv->listen_fd, 1) < 0) {
        perror("listen");
        close(srv->listen_fd);
        unlink(path);
        return false;
    }

    int flags = fcntl(srv->listen_fd, F_GETFL, 0);
    fcntl(srv->listen_fd, F_SETFL, flags | O_NONBLOCK);

    srv->client_fd = -1;
    srv->read_len = 0;
    snprintf(srv->path, sizeof(srv->path), "%s", path);

    return true;
}

int socket_get_fds(struct socket_server *srv, struct pollfd *fds, int offset)
{
    fds[offset].fd = srv->listen_fd;
    fds[offset].events = POLLIN;
    fds[offset].revents = 0;

    if (srv->client_fd >= 0) {
        fds[offset + 1].fd = srv->client_fd;
        fds[offset + 1].events = POLLIN;
        fds[offset + 1].revents = 0;
        return 2;
    }

    return 1;
}

static void consume_one(struct socket_server *srv, struct overlay_command *cmd)
{
    char *nl = memchr(srv->read_buf, '\n', srv->read_len);
    if (!nl)
        return;
    *nl = '\0';
    parse_command(srv->read_buf, cmd);
    size_t consumed = (size_t)(nl - srv->read_buf) + 1;
    size_t remaining = srv->read_len - consumed;
    if (remaining > 0)
        memmove(srv->read_buf, nl + 1, remaining);
    srv->read_len = remaining;
}

bool socket_has_pending(struct socket_server *srv)
{
    return srv->read_len > 0
        && memchr(srv->read_buf, '\n', srv->read_len) != NULL;
}

bool socket_process(struct socket_server *srv, struct pollfd *fds, int offset,
                    struct overlay_command *cmd)
{
    cmd->cmd = CMD_NONE;
    cmd->data[0] = '\0';
    cmd->conv_id[0] = '\0';

    /* Check for new connection on listen fd */
    if (fds[offset].revents & POLLIN) {
        int new_fd = accept(srv->listen_fd, NULL, NULL);
        if (new_fd >= 0) {
            /* Last writer wins: close existing client */
            if (srv->client_fd >= 0)
                close(srv->client_fd);
            srv->client_fd = new_fd;
            srv->read_len = 0;
        }
    }

    /* Drain any already-buffered complete message first */
    if (srv->read_len > 0) {
        consume_one(srv, cmd);
        if (cmd->cmd != CMD_NONE)
            return true;
    }

    /* Read new data from client */
    if (srv->client_fd >= 0 && fds[offset + 1].revents & POLLIN) {
        ssize_t n = read(srv->client_fd, srv->read_buf + srv->read_len,
                         sizeof(srv->read_buf) - srv->read_len - 1);
        if (n <= 0) {
            /* Process any trailing message before closing */
            consume_one(srv, cmd);
            close(srv->client_fd);
            srv->client_fd = -1;
            srv->read_len = 0;
            return true;
        }

        srv->read_len += (size_t)n;
        srv->read_buf[srv->read_len] = '\0';
        consume_one(srv, cmd);
    }

    return true;
}

void socket_cleanup(struct socket_server *srv)
{
    if (srv->client_fd >= 0) {
        close(srv->client_fd);
        srv->client_fd = -1;
    }
    if (srv->listen_fd >= 0) {
        close(srv->listen_fd);
        srv->listen_fd = -1;
    }
    if (srv->path[0])
        unlink(srv->path);
}
