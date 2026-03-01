#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <signal.h>
#include <poll.h>
#include <unistd.h>
#include <sys/timerfd.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <sys/wait.h>
#include <linux/input-event-codes.h>
#include "wayland.h"
#include "config.h"
#include "render.h"
#include "socket.h"
#include "animation.h"

static volatile sig_atomic_t quit = 0;
static char current_conv_id[64] = "";
static bool user_mode = false;    /* true = mic/user accent, false = agent accent */
static bool listening_active = false;  /* true = show waveform animation */
static uint64_t listening_start = 0;
static bool thinking_active = false;   /* true = pulse text, sweep accent */
static uint64_t thinking_start = 0;
static bool show_buttons = false;      /* true = render embedded action buttons */
static int hovered_button = -1;        /* -1 = none, 0-2 = mic/open/reply */
static pid_t actions_pid = 0;     /* child PID of aside-reply input, 0 = none */
static int actions_hold_fd = -1;  /* read end of hold pipe from reply input */
static bool actions_holding = false; /* true while user interacts with reply input */

static void handle_signal(int sig) { (void)sig; quit = 1; }

/* Kill the aside-reply input child if running */
static void kill_actions(void)
{
    if (actions_pid > 0) {
        kill(actions_pid, SIGTERM);
        waitpid(actions_pid, NULL, 0);
        actions_pid = 0;
    }
    if (actions_hold_fd >= 0) {
        close(actions_hold_fd);
        actions_hold_fd = -1;
    }
    actions_holding = false;
}

/* Check if aside-reply child has exited; returns true if it just died */
static bool reap_actions(void)
{
    if (actions_pid <= 0) return false;
    int status;
    pid_t r = waitpid(actions_pid, &status, WNOHANG);
    if (r == actions_pid) {
        actions_pid = 0;
        if (actions_hold_fd >= 0) {
            close(actions_hold_fd);
            actions_hold_fd = -1;
        }
        actions_holding = false;
        return true;
    }
    return false;
}

/* Compute the margin for the reply input window's anchored edge */
static uint32_t reply_input_margin(const struct overlay_config *cfg,
                                   const struct overlay_state *state)
{
    const char *pos = cfg->position;
    uint32_t gap = 4;

    if (strstr(pos, "bottom"))
        return cfg->margin_bottom + state->height + gap;
    if (strcmp(pos, "center") == 0) {
        uint32_t s = (uint32_t)(state->scale > 1 ? state->scale : 1);
        uint32_t logical_h = state->output_mode_height / s;
        if (logical_h > 0)
            return (logical_h + state->height) / 2 + gap;
    }
    return cfg->margin_top + state->height + gap;
}

/* Update layer-shell margin to keep overlay centered (center position only) */
static void update_center_margin(const struct overlay_config *cfg,
                                 struct overlay_state *state)
{
    if (strcmp(cfg->position, "center") != 0 || !state->layer_surface)
        return;
    uint32_t s = state->scale > 1 ? (uint32_t)state->scale : 1;
    uint32_t logical_h = state->output_mode_height / s;
    if (logical_h > state->height) {
        uint32_t center_margin = (logical_h - state->height) / 2;
        zwlr_layer_surface_v1_set_margin(state->layer_surface,
            center_margin, cfg->margin_right, cfg->margin_bottom, cfg->margin_left);
    }
}

/* Spawn aside-reply input */
static void spawn_reply_input(const struct overlay_config *cfg,
                               const struct overlay_state *state)
{
    if (current_conv_id[0] == '\0') return;

    char margin_str[32], width_str[32];
    char margin_left_str[32], margin_right_str[32];
    snprintf(margin_str, sizeof(margin_str), "%u",
             reply_input_margin(cfg, state));
    snprintf(width_str, sizeof(width_str), "%u", cfg->width);
    snprintf(margin_left_str, sizeof(margin_left_str), "%u", cfg->margin_left);
    snprintf(margin_right_str, sizeof(margin_right_str), "%u", cfg->margin_right);

    const char *home = getenv("HOME");
    char bin[512] = "aside-reply";
    if (home) {
        snprintf(bin, sizeof(bin), "%s/.local/bin/aside-reply", home);
        if (access(bin, X_OK) != 0)
            snprintf(bin, sizeof(bin), "aside-reply");
    }

    kill_actions();

    int holdpipe[2];
    if (pipe(holdpipe) != 0) return;

    pid_t pid = fork();
    if (pid == 0) {
        close(holdpipe[0]);
        char hold_fd_str[16];
        snprintf(hold_fd_str, sizeof(hold_fd_str), "%d", holdpipe[1]);
        execl(bin, "aside-reply",
              "--conv-id", current_conv_id,
              "--width", width_str,
              "--margin-top", margin_str,
              "--position", cfg->position,
              "--margin-left", margin_left_str,
              "--margin-right", margin_right_str,
              "--hold-fd", hold_fd_str,
              NULL);
        _exit(1);
    } else if (pid > 0) {
        close(holdpipe[1]);
        actions_pid = pid;
        actions_hold_fd = holdpipe[0];
    } else {
        close(holdpipe[0]);
        close(holdpipe[1]);
    }
}

/* Send a JSON action to the aside daemon */
static void send_daemon_action(const char *action_json)
{
    const char *runtime_dir = getenv("XDG_RUNTIME_DIR");
    if (!runtime_dir) return;

    char path[256];
    snprintf(path, sizeof(path), "%s/aside.sock", runtime_dir);

    int fd = socket(AF_UNIX, SOCK_STREAM, 0);
    if (fd < 0) return;

    struct sockaddr_un addr = {0};
    addr.sun_family = AF_UNIX;
    snprintf(addr.sun_path, sizeof(addr.sun_path), "%s", path);

    if (connect(fd, (struct sockaddr *)&addr, sizeof(addr)) == 0)
        (void)write(fd, action_json, strlen(action_json));
    close(fd);
}

static void arm_timer(int fd, bool on)
{
    struct itimerspec ts = {0};
    if (on) {
        ts.it_interval.tv_nsec = 16666667;  /* ~60fps */
        ts.it_value.tv_nsec = 16666667;
    }
    timerfd_settime(fd, 0, &ts, NULL);
}

static void ensure_timer(int fd, bool *armed)
{
    if (!*armed) {
        arm_timer(fd, true);
        *armed = true;
    }
}

int main(int argc, char *argv[])
{
    (void)argc;
    (void)argv;

    /* Load configuration */
    struct overlay_config cfg;
    config_defaults(&cfg);

    char config_path[512];
    const char *config_home = getenv("XDG_CONFIG_HOME");
    if (config_home)
        snprintf(config_path, sizeof(config_path),
                 "%s/aside/overlay.conf", config_home);
    else
        snprintf(config_path, sizeof(config_path),
                 "%s/.config/aside/overlay.conf", getenv("HOME"));
    config_load(&cfg, config_path);

    struct renderer rend = {0};
    renderer_init(&rend, &cfg);

    struct overlay_state state = {0};
    state.shm_fd = -1;

    signal(SIGINT, handle_signal);
    signal(SIGTERM, handle_signal);
    signal(SIGPIPE, SIG_IGN);

    if (!wayland_init(&state)) {
        fprintf(stderr, "Failed to initialize Wayland\n");
        renderer_cleanup(&rend);
        return EXIT_FAILURE;
    }

    /* Do NOT create surface on startup -- wait for commands */

    /* Build socket path */
    char sock_path[512];
    if (cfg.socket_path[0]) {
        snprintf(sock_path, sizeof(sock_path), "%s", cfg.socket_path);
    } else {
        const char *runtime_dir = getenv("XDG_RUNTIME_DIR");
        if (!runtime_dir) {
            fprintf(stderr, "XDG_RUNTIME_DIR not set\n");
            renderer_cleanup(&rend);
            wayland_cleanup(&state);
            return EXIT_FAILURE;
        }
        snprintf(sock_path, sizeof(sock_path), "%s/aside-overlay.sock",
                 runtime_dir);
    }

    struct socket_server srv = {0};
    srv.client_fd = -1;
    if (!socket_init(&srv, sock_path)) {
        fprintf(stderr, "Failed to create socket at %s\n", sock_path);
        renderer_cleanup(&rend);
        wayland_cleanup(&state);
        return EXIT_FAILURE;
    }

    /* Create timerfd for animations (~60fps) */
    int timer_fd = timerfd_create(CLOCK_MONOTONIC, TFD_NONBLOCK);
    if (timer_fd < 0) {
        perror("timerfd_create");
        socket_cleanup(&srv);
        renderer_cleanup(&rend);
        wayland_cleanup(&state);
        return EXIT_FAILURE;
    }

    /* Animation state */
    struct animation scroll_anim = { .current = 0.0 };
    struct animation fade_anim = { .current = 1.0 };
    bool timer_armed = false;

    struct pollfd fds[5]; /* wayland, timer, socket_listen, socket_client, hold */
    fds[0].fd = wayland_get_fd(&state);
    fds[0].events = POLLIN;
    fds[1].fd = timer_fd;
    fds[1].events = POLLIN;

    /* Text accumulation buffer */
    char text_buf[65536] = {0};
    size_t text_len = 0;

    /* User scroll state: when true, auto-scroll-to-bottom is paused */
    bool user_scrolling = false;

    /* Linger state: wait before starting fade after CMD_DONE */
    uint64_t done_at = 0;        /* timestamp when CMD_DONE received, 0 = not waiting */
    uint32_t linger_ms = 3000;   /* ms to wait after done before fading */
    bool done_received = false;  /* true after CMD_DONE, prevents premature linger */

    while (!quit && !state.closed) {
        /* Only redraw when surface is visible and configured */
        if (state.needs_redraw && state.surface_visible && state.configured) {
            if (!wayland_alloc_buffer(&state)) {
                fprintf(stderr, "Failed to allocate buffer\n");
                break;
            }

            uint32_t s = state.scale > 1 ? state.scale : 1;
            uint32_t accent = user_mode ? cfg.user_accent_color : cfg.accent_color;
            enum draw_mode mode = DRAW_NORMAL;
            uint64_t anim_time = 0;
            if (listening_active) {
                mode = DRAW_LISTENING;
                anim_time = anim_now_ms() - listening_start;
            } else if (thinking_active) {
                mode = DRAW_THINKING;
                anim_time = anim_now_ms() - thinking_start;
            }
            renderer_draw(&rend, &cfg, state.pixels,
                          state.configured_width * s, state.configured_height * s,
                          text_buf, scroll_anim.current, fade_anim.current, accent,
                          mode, anim_time, show_buttons, hovered_button);

            wayland_commit(&state);
            state.needs_redraw = false;
        }

        int nfds = 2 + socket_get_fds(&srv, fds, 2);
        int hold_idx = -1;
        if (actions_hold_fd >= 0) {
            hold_idx = nfds;
            fds[nfds].fd = actions_hold_fd;
            fds[nfds].events = POLLIN;
            nfds++;
        }

        wl_display_flush(state.display);

        /* Reap reply input child; start linger when it exits (only after done) */
        if (reap_actions() && done_at == 0 && done_received && current_conv_id[0]) {
            done_at = anim_now_ms();
        }

        /* Check linger timer: start fade after delay, unless pointer hovers
         * or user is interacting with the reply input */
        if (done_at > 0 && !state.pointer_over && !actions_holding) {
            uint64_t now = anim_now_ms();
            if (now - done_at >= linger_ms) {
                done_at = 0;
                anim_set_target(&fade_anim, 0.0, cfg.fade_duration);
                ensure_timer(timer_fd, &timer_armed);
                state.needs_redraw = true;
            }
        }

        /* Don't block if there's buffered socket data to drain or linger pending */
        int poll_timeout = socket_has_pending(&srv) ? 0
                         : (done_at > 0) ? 100  /* poll frequently while lingering */
                         : -1;
        if (poll(fds, nfds, poll_timeout) < 0) {
            if (quit || errno == EINTR)
                break;
            perror("poll");
            break;
        }

        if (fds[0].revents & POLLIN) {
            if (!wayland_dispatch(&state))
                break;
        }

        /* --- Track button hover state --- */
        if (show_buttons && state.pointer_over && state.surface_visible) {
            int new_hover = -1;
            for (int i = 0; i < 3; i++) {
                struct button_rect *br = &rend.button_rects[i];
                if (br->w > 0 &&
                    state.pointer_x >= br->x && state.pointer_x <= br->x + br->w &&
                    state.pointer_y >= br->y && state.pointer_y <= br->y + br->h) {
                    new_hover = i;
                    break;
                }
            }
            if (new_hover != hovered_button) {
                hovered_button = new_hover;
                state.needs_redraw = true;
            }
        } else if (hovered_button >= 0) {
            hovered_button = -1;
            state.needs_redraw = true;
        }

        /* --- Read hold signals from reply input --- */
        if (hold_idx >= 0 && (fds[hold_idx].revents & POLLIN)) {
            char hbuf[16];
            ssize_t hn = read(actions_hold_fd, hbuf, sizeof(hbuf));
            if (hn > 0) {
                for (ssize_t i = hn - 1; i >= 0; i--) {
                    if (hbuf[i] == 'H') { actions_holding = true; break; }
                    if (hbuf[i] == 'R') {
                        actions_holding = false;
                        /* Fresh linger countdown after interaction ends */
                        if (done_received && current_conv_id[0])
                            done_at = anim_now_ms();
                        break;
                    }
                }
            } else if (hn == 0) {
                /* Pipe closed: reply input exited */
                close(actions_hold_fd);
                actions_hold_fd = -1;
                actions_holding = false;
            }
        }

        /* --- Pointer / actions-hold pauses fade --- */
        if ((state.pointer_over || actions_holding)
            && fade_anim.active && fade_anim.target < 0.5) {
            /* Pause: snap opacity back to full, cancel the fade */
            fade_anim.current = 1.0;
            fade_anim.active = false;
            if (current_conv_id[0]) {
                done_at = 0;  /* reset linger; will restart when pointer leaves */
            }
            state.needs_redraw = true;
        }
        /* Restart linger when pointer leaves after hover-pause
         * (only if user is not interacting with reply input) */
        if (!state.pointer_over && !actions_holding && done_at == 0
            && !fade_anim.active && done_received && current_conv_id[0]) {
            done_at = anim_now_ms();
        }

        /* --- Process user scroll input --- */
        if (state.pending_scroll_delta != 0.0 && state.surface_visible) {
            double delta = state.pending_scroll_delta;
            state.pending_scroll_delta = 0.0;

            int content_h = renderer_measure(&rend, &cfg, text_buf);
            uint32_t visible_h = (uint32_t)rend.line_height * cfg.max_lines;
            double max_scroll = content_h > (int)visible_h
                ? (double)(content_h - (int)visible_h) : 0.0;

            double new_pos = scroll_anim.current + delta;
            if (new_pos < 0.0) new_pos = 0.0;
            if (new_pos > max_scroll) new_pos = max_scroll;

            scroll_anim.current = new_pos;
            scroll_anim.target = new_pos;
            scroll_anim.active = false;

            /* If user scrolled away from bottom, pause auto-scroll */
            user_scrolling = (new_pos < max_scroll - 5.0);

            /* If user scrolls during fade-out or linger, cancel it */
            if (fade_anim.active && fade_anim.target < 0.5) {
                fade_anim.current = 1.0;
                fade_anim.active = false;
            }
            done_at = 0;

            state.needs_redraw = true;
        } else {
            state.pending_scroll_delta = 0.0;
        }

        /* --- Process pointer button clicks --- */
        if (state.pending_button && state.surface_visible) {
            uint32_t btn = state.pending_button;
            state.pending_button = 0;

            bool do_dismiss = false;

            if (btn == BTN_LEFT) {
                /* Check embedded button clicks first */
                if (show_buttons && hovered_button >= 0 && actions_pid == 0) {
                    if (hovered_button == 0) {
                        /* Mic: voice reply */
                        char msg[256];
                        snprintf(msg, sizeof(msg),
                                 "{\"action\":\"query\",\"conversation_id\":\"%s\",\"mic\":true}\n",
                                 current_conv_id);
                        send_daemon_action(msg);
                        do_dismiss = true;
                    } else if (hovered_button == 1) {
                        /* Open transcript */
                        pid_t p = fork();
                        if (p == 0) {
                            const char *h = getenv("HOME");
                            char aside_bin[512] = "aside";
                            if (h) {
                                snprintf(aside_bin, sizeof(aside_bin),
                                         "%s/.local/bin/aside", h);
                                if (access(aside_bin, X_OK) != 0)
                                    snprintf(aside_bin, sizeof(aside_bin), "aside");
                            }
                            execl(aside_bin, "aside", "open", current_conv_id, NULL);
                            _exit(1);
                        }
                        do_dismiss = true;
                    } else if (hovered_button == 2) {
                        /* Reply: spawn text input, keep overlay visible */
                        spawn_reply_input(&cfg, &state);
                    }
                } else {
                    /* Left click (not on button): dismiss overlay */
                    do_dismiss = true;
                }
            } else if (btn == BTN_RIGHT) {
                /* Right click: cancel query (stops stream + TTS + overlay) */
                send_daemon_action("{\"action\":\"cancel\"}\n");
                do_dismiss = true;
            } else if (btn == BTN_MIDDLE) {
                /* Middle click: stop TTS only, text keeps streaming */
                send_daemon_action("{\"action\":\"stop_tts\"}\n");
            }

            if (do_dismiss) {
                kill_actions();
                show_buttons = false;
                hovered_button = -1;
                text_buf[0] = '\0';
                text_len = 0;
                fade_anim.current = 1.0;
                fade_anim.active = false;
                done_at = 0;
                done_received = false;
                scroll_anim.current = 0.0;
                scroll_anim.active = false;
                user_scrolling = false;
                if (timer_armed) {
                    arm_timer(timer_fd, false);
                    timer_armed = false;
                }
                wayland_destroy_surface(&state);
            }
        } else {
            state.pending_button = 0;
        }

        /* Handle timer tick for animations */
        if (fds[1].revents & POLLIN) {
            uint64_t expirations;
            read(timer_fd, &expirations, sizeof(expirations));

            uint64_t now = anim_now_ms();
            bool scroll_active = anim_update(&scroll_anim, now);
            bool fade_active = anim_update(&fade_anim, now);

            /* Continuous animation modes always need redraws */
            if (listening_active || thinking_active) {
                state.needs_redraw = true;
            } else if (scroll_active || fade_active) {
                state.needs_redraw = true;
            } else {
                /* All animations done -- disarm timer */
                arm_timer(timer_fd, false);
                timer_armed = false;

                /* If fade completed (opacity ~0), destroy surface */
                if (fade_anim.current <= 0.01 && state.surface_visible) {
                    kill_actions();
                    show_buttons = false;
                    hovered_button = -1;
                    done_received = false;
                    wayland_destroy_surface(&state);
                }
            }
        }

        struct overlay_command cmd = {0};
        socket_process(&srv, fds, 2, &cmd);

        if (cmd.cmd == CMD_NONE)
            continue;

        switch (cmd.cmd) {
        case CMD_OPEN:
            kill_actions();
            show_buttons = false;
            hovered_button = -1;
            listening_active = false;
            thinking_active = false;
            strncpy(current_conv_id, cmd.conv_id,
                    sizeof(current_conv_id) - 1);
            current_conv_id[sizeof(current_conv_id) - 1] = '\0';
            user_mode = (strcmp(cmd.mode, "user") == 0);
            text_buf[0] = '\0';
            text_len = 0;
            /* Cancel fade/linger, reset opacity */
            fade_anim.current = 1.0;
            fade_anim.active = false;
            done_at = 0;
            done_received = false;
            /* Reset scroll */
            scroll_anim.current = 0.0;
            scroll_anim.active = false;
            user_scrolling = false;
            if (!state.surface_visible) {
                uint32_t h = cfg.padding_y * 2 + (uint32_t)rend.line_height;
                if (!wayland_create_surface(&state, cfg.width, h, &cfg)) {
                    fprintf(stderr, "Failed to create surface on CMD_OPEN\n");
                    break;
                }
            }
            state.needs_redraw = true;
            break;

        case CMD_TEXT:
            listening_active = false;
            thinking_active = false;
            /* Append text data to buffer */
            {
                size_t chunk_len = strlen(cmd.data);
                if (text_len + chunk_len < sizeof(text_buf) - 1) {
                    memcpy(text_buf + text_len, cmd.data, chunk_len);
                    text_len += chunk_len;
                    text_buf[text_len] = '\0';
                }
            }
            /* Implicit open if surface not visible */
            if (!state.surface_visible) {
                /* Cancel any lingering fade */
                fade_anim.current = 1.0;
                fade_anim.active = false;
                scroll_anim.current = 0.0;
                scroll_anim.active = false;
                uint32_t h = cfg.padding_y * 2 + (uint32_t)rend.line_height;
                if (!wayland_create_surface(&state, cfg.width, h, &cfg)) {
                    fprintf(stderr, "Failed to create surface on CMD_TEXT\n");
                    break;
                }
            }
            /* Resize surface if text height changed */
            {
                int content_h = renderer_measure(&rend, &cfg, text_buf);
                uint32_t max_h = cfg.padding_y * 2
                    + (uint32_t)rend.line_height * cfg.max_lines;
                uint32_t target_h = (uint32_t)content_h + cfg.padding_y * 2;
                if (target_h > max_h)
                    target_h = max_h;
                uint32_t min_h = cfg.padding_y * 2 + (uint32_t)rend.line_height;
                if (target_h < min_h)
                    target_h = min_h;
                if (target_h != state.height && state.layer_surface) {
                    zwlr_layer_surface_v1_set_size(state.layer_surface,
                                                   cfg.width, target_h);
                    state.height = target_h;
                    update_center_margin(&cfg, &state);
                    wl_surface_commit(state.surface);
                    /* Configure callback will set needs_redraw */
                }
            }
            /* Compute scroll target */
            {
                int content_h = renderer_measure(&rend, &cfg, text_buf);
                uint32_t visible_h = (uint32_t)rend.line_height * cfg.max_lines;

                /* Only auto-scroll to bottom if user hasn't scrolled up */
                if ((uint32_t)content_h > visible_h && !user_scrolling) {
                    double new_target = (double)(content_h - (int)visible_h);
                    if (new_target != scroll_anim.target || !scroll_anim.active) {
                        anim_set_target(&scroll_anim, new_target, cfg.scroll_duration);
                        ensure_timer(timer_fd, &timer_armed);
                    }
                }
            }
            state.needs_redraw = true;
            break;

        case CMD_DONE: {
            /* Show embedded action buttons */
            show_buttons = true;
            hovered_button = -1;

            /* Final resize including button bar */
            int content_h = renderer_measure(&rend, &cfg, text_buf);
            uint32_t max_h = cfg.padding_y * 2
                + (uint32_t)rend.line_height * cfg.max_lines + BUTTON_BAR_HEIGHT;
            uint32_t target_h = (uint32_t)content_h + cfg.padding_y * 2
                + BUTTON_BAR_HEIGHT;
            if (target_h > max_h) target_h = max_h;
            uint32_t min_h = cfg.padding_y * 2 + (uint32_t)rend.line_height
                + BUTTON_BAR_HEIGHT;
            if (target_h < min_h) target_h = min_h;

            if (target_h != state.height && state.layer_surface) {
                zwlr_layer_surface_v1_set_size(state.layer_surface,
                                                cfg.width, target_h);
                state.height = target_h;
                update_center_margin(&cfg, &state);
                wl_surface_commit(state.surface);
            }

            state.needs_redraw = true;
            done_received = true;
            done_at = anim_now_ms();
            break;
        }

        case CMD_CLEAR:
            kill_actions();
            show_buttons = false;
            hovered_button = -1;
            listening_active = false;
            thinking_active = false;
            text_buf[0] = '\0';
            text_len = 0;
            fade_anim.current = 1.0;
            fade_anim.active = false;
            done_at = 0;
            done_received = false;
            scroll_anim.current = 0.0;
            scroll_anim.active = false;
            user_scrolling = false;
            if (timer_armed) {
                arm_timer(timer_fd, false);
                timer_armed = false;
            }
            if (state.surface_visible)
                wayland_destroy_surface(&state);
            break;

        case CMD_REPLACE:
            listening_active = false;
            thinking_active = false;
            text_buf[0] = '\0';
            text_len = 0;
            {
                size_t chunk_len = strlen(cmd.data);
                if (chunk_len < sizeof(text_buf) - 1) {
                    memcpy(text_buf, cmd.data, chunk_len);
                    text_len = chunk_len;
                    text_buf[text_len] = '\0';
                }
            }
            if (!state.surface_visible) {
                fade_anim.current = 1.0;
                fade_anim.active = false;
                scroll_anim.current = 0.0;
                scroll_anim.active = false;
                uint32_t h = cfg.padding_y * 2 + (uint32_t)rend.line_height;
                if (!wayland_create_surface(&state, cfg.width, h, &cfg)) {
                    fprintf(stderr, "Failed to create surface on CMD_REPLACE\n");
                    break;
                }
            }
            /* Resize surface for new content */
            {
                int content_h = renderer_measure(&rend, &cfg, text_buf);
                uint32_t btn_extra = show_buttons ? BUTTON_BAR_HEIGHT : 0;
                uint32_t max_h = cfg.padding_y * 2
                    + (uint32_t)rend.line_height * cfg.max_lines + btn_extra;
                uint32_t target_h = (uint32_t)content_h + cfg.padding_y * 2
                    + btn_extra;
                if (target_h > max_h)
                    target_h = max_h;
                uint32_t min_h = cfg.padding_y * 2 + (uint32_t)rend.line_height
                    + btn_extra;
                if (target_h < min_h)
                    target_h = min_h;
                if (target_h != state.height && state.layer_surface) {
                    zwlr_layer_surface_v1_set_size(state.layer_surface,
                                                   cfg.width, target_h);
                    state.height = target_h;
                    update_center_margin(&cfg, &state);
                    wl_surface_commit(state.surface);
                }
            }
            /* Compute scroll target for replaced content */
            {
                int content_h = renderer_measure(&rend, &cfg, text_buf);
                uint32_t visible_h = (uint32_t)rend.line_height * cfg.max_lines;

                if ((uint32_t)content_h > visible_h && !user_scrolling) {
                    double new_target = (double)(content_h - (int)visible_h);
                    if (new_target != scroll_anim.target || !scroll_anim.active) {
                        anim_set_target(&scroll_anim, new_target, cfg.scroll_duration);
                        ensure_timer(timer_fd, &timer_armed);
                    }
                } else if ((uint32_t)content_h <= visible_h) {
                    scroll_anim.current = 0.0;
                    scroll_anim.active = false;
                    user_scrolling = false;
                }
            }
            state.needs_redraw = true;
            break;

        case CMD_LISTENING:
            listening_active = true;
            thinking_active = false;
            show_buttons = false;
            hovered_button = -1;
            listening_start = anim_now_ms();
            /* Resize to 2 lines for a nice waveform area */
            if (state.surface_visible && state.layer_surface) {
                uint32_t listen_h = cfg.padding_y * 2 + (uint32_t)rend.line_height * 2;
                if (listen_h != state.height) {
                    zwlr_layer_surface_v1_set_size(state.layer_surface,
                                                   cfg.width, listen_h);
                    state.height = listen_h;
                    update_center_margin(&cfg, &state);
                    wl_surface_commit(state.surface);
                }
            }
            ensure_timer(timer_fd, &timer_armed);
            state.needs_redraw = true;
            break;

        case CMD_THINKING:
            thinking_active = true;
            listening_active = false;
            thinking_start = anim_now_ms();
            ensure_timer(timer_fd, &timer_armed);
            state.needs_redraw = true;
            break;

        case CMD_NONE:
            break;
        }
    }

    close(timer_fd);
    socket_cleanup(&srv);
    renderer_cleanup(&rend);
    wayland_cleanup(&state);
    return EXIT_SUCCESS;
}
