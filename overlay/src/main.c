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
#include <linux/input-event-codes.h>
#include <xkbcommon/xkbcommon.h>
#include "wayland.h"
#include "config.h"
#include "render.h"
#include "socket.h"
#include "animation.h"

static volatile sig_atomic_t quit = 0;
static char current_conv_id[64] = "";

/* --- Action buttons --- */
enum overlay_button { BTN_ACTION_MIC = 0, BTN_ACTION_OPEN, BTN_ACTION_REPLY, BTN_ACTION_COUNT };
static struct button_rect action_buttons[BTN_ACTION_COUNT];
static bool show_buttons = false;

/* --- Text input state --- */
static bool input_active = false;
static char input_buf[4096] = "";
static size_t input_len = 0;

/* Button row height: set after renderer init */
static uint32_t button_row_height = 0;

static void handle_signal(int sig) { (void)sig; quit = 1; }

/* JSON-escape a string for safe embedding in JSON values */
static size_t json_escape(const char *in, char *out, size_t out_size)
{
    size_t j = 0;
    for (size_t i = 0; in[i] && j < out_size - 2; i++) {
        switch (in[i]) {
        case '"':  if (j+2 < out_size) { out[j++] = '\\'; out[j++] = '"'; }  break;
        case '\\': if (j+2 < out_size) { out[j++] = '\\'; out[j++] = '\\'; } break;
        case '\n': if (j+2 < out_size) { out[j++] = '\\'; out[j++] = 'n'; }  break;
        case '\r': if (j+2 < out_size) { out[j++] = '\\'; out[j++] = 'r'; }  break;
        case '\t': if (j+2 < out_size) { out[j++] = '\\'; out[j++] = 't'; }  break;
        default:
            if ((unsigned char)in[i] < 0x20) {
                if (j+6 < out_size) j += (size_t)snprintf(out+j, out_size-j, "\\u%04x", (unsigned char)in[i]);
            } else {
                out[j++] = in[i];
            }
        }
    }
    out[j] = '\0';
    return j;
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

/* Forward-declared dismiss helper; defined after main locals are available */
static struct overlay_state *g_state = NULL;  /* set in main() for callbacks */
static int g_timer_fd = -1;
static bool *g_timer_armed = NULL;
static char *g_text_buf = NULL;
static size_t *g_text_len = NULL;
static struct animation *g_fade_anim = NULL;
static struct animation *g_scroll_anim = NULL;
static uint64_t *g_done_at = NULL;
static bool *g_user_scrolling = NULL;

static void dismiss_overlay(void)
{
    g_text_buf[0] = '\0';
    *g_text_len = 0;
    g_fade_anim->current = 1.0;
    g_fade_anim->active = false;
    *g_done_at = 0;
    g_scroll_anim->current = 0.0;
    g_scroll_anim->active = false;
    *g_user_scrolling = false;
    show_buttons = false;
    input_active = false;
    input_len = 0;
    input_buf[0] = '\0';
    if (*g_timer_armed) {
        /* disarm inline -- can't call arm_timer yet (declared below) */
        struct itimerspec ts = {0};
        timerfd_settime(g_timer_fd, 0, &ts, NULL);
        *g_timer_armed = false;
    }
    wayland_destroy_surface(g_state);
}

static void handle_button_click(int btn)
{
    switch (btn) {
    case BTN_ACTION_MIC: {
        char json[256];
        snprintf(json, sizeof(json),
                 "{\"action\":\"query\",\"conversation_id\":\"%s\",\"mic\":true}\n",
                 current_conv_id);
        send_daemon_action(json);
        dismiss_overlay();
        break;
    }
    case BTN_ACTION_OPEN:
        if (fork() == 0) {
            execlp("aside", "aside", "open", current_conv_id, NULL);
            _exit(1);
        }
        break;
    case BTN_ACTION_REPLY:
        input_active = true;
        input_len = 0;
        input_buf[0] = '\0';
        show_buttons = false;
        g_state->needs_redraw = true;
        break;
    }
}

/* Keyboard callback: receives key events from wayland.c */
static void on_key(void *user_data, uint32_t sym, const char *utf8, int n)
{
    (void)user_data;
    if (!input_active) return;

    if (sym == XKB_KEY_Escape) {
        input_active = false;
        show_buttons = true;
        g_state->needs_redraw = true;
        return;
    }

    if (sym == XKB_KEY_Return || sym == XKB_KEY_KP_Enter) {
        if (input_len > 0) {
            /* JSON-escape the input */
            char escaped[8192];
            json_escape(input_buf, escaped, sizeof(escaped));

            char json[8500];
            snprintf(json, sizeof(json),
                     "{\"action\":\"query\",\"text\":\"%s\","
                     "\"conversation_id\":\"%s\"}\n",
                     escaped, current_conv_id);
            send_daemon_action(json);
        }
        input_active = false;
        dismiss_overlay();
        return;
    }

    if (sym == XKB_KEY_BackSpace) {
        if (input_len > 0) {
            /* Handle UTF-8: find start of last character */
            size_t i = input_len - 1;
            while (i > 0 && (input_buf[i] & 0xC0) == 0x80) i--;
            input_len = i;
            input_buf[input_len] = '\0';
        }
        g_state->needs_redraw = true;
        return;
    }

    /* Printable character */
    if (n > 0 && (unsigned char)utf8[0] >= 0x20) {
        if (input_len + (size_t)n < sizeof(input_buf) - 1) {
            memcpy(input_buf + input_len, utf8, (size_t)n);
            input_len += (size_t)n;
            input_buf[input_len] = '\0';
        }
    }
    g_state->needs_redraw = true;
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

    /* Button row height: button + padding above/below */
    button_row_height = (uint32_t)rend.line_height + 16;

    struct overlay_state state = {0};
    state.shm_fd = -1;

    signal(SIGINT, handle_signal);
    signal(SIGTERM, handle_signal);

    if (!wayland_init(&state)) {
        fprintf(stderr, "Failed to initialize Wayland\n");
        renderer_cleanup(&rend);
        return EXIT_FAILURE;
    }

    /* Wire up keyboard callback */
    state.key_cb = on_key;
    state.key_cb_data = &state;

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

    /* Wire up global pointers for callback functions */
    g_state = &state;
    g_timer_fd = timer_fd;
    g_timer_armed = &timer_armed;
    g_fade_anim = &fade_anim;
    g_scroll_anim = &scroll_anim;

    struct pollfd fds[4]; /* wayland, timer, socket_listen, socket_client */
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

    /* Wire up remaining global pointers for callbacks */
    g_text_buf = text_buf;
    g_text_len = &text_len;
    g_done_at = &done_at;
    g_user_scrolling = &user_scrolling;

    while (!quit && !state.closed) {
        /* Only redraw when surface is visible and configured */
        if (state.needs_redraw && state.surface_visible && state.configured) {
            if (!wayland_alloc_buffer(&state)) {
                fprintf(stderr, "Failed to allocate buffer\n");
                break;
            }

            uint32_t s = state.scale > 1 ? state.scale : 1;
            renderer_draw(&rend, &cfg, state.pixels,
                          state.configured_width * s, state.configured_height * s,
                          text_buf, scroll_anim.current, fade_anim.current,
                          show_buttons, action_buttons, BTN_ACTION_COUNT,
                          input_active, input_buf);

            wayland_commit(&state);
            state.needs_redraw = false;
        }

        int nfds = 2 + socket_get_fds(&srv, fds, 2);

        wl_display_flush(state.display);

        /* Check linger timer: start fade after delay, unless pointer hovers */
        if (done_at > 0 && !state.pointer_over) {
            uint64_t now = anim_now_ms();
            if (now - done_at >= linger_ms) {
                done_at = 0;
                show_buttons = false;
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

        /* --- Pointer hover pauses fade --- */
        if (state.pointer_over && fade_anim.active && fade_anim.target < 0.5) {
            /* Pause: snap opacity back to full, cancel the fade */
            fade_anim.current = 1.0;
            fade_anim.active = false;
            /* Restore buttons if we have a conversation */
            if (current_conv_id[0] && !input_active) {
                show_buttons = true;
                done_at = 0;  /* reset linger; will restart when pointer leaves */
            }
            state.needs_redraw = true;
        }
        /* Restart linger when pointer leaves after hover-pause */
        if (!state.pointer_over && show_buttons && done_at == 0
            && !fade_anim.active && !input_active) {
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

            if (btn == BTN_LEFT) {
                /* Check action button hits first */
                bool btn_hit = false;
                if (show_buttons) {
                    for (int i = 0; i < BTN_ACTION_COUNT; i++) {
                        if (state.pointer_x >= action_buttons[i].x &&
                            state.pointer_x <= action_buttons[i].x + action_buttons[i].w &&
                            state.pointer_y >= action_buttons[i].y &&
                            state.pointer_y <= action_buttons[i].y + action_buttons[i].h) {
                            handle_button_click(i);
                            btn_hit = true;
                            break;
                        }
                    }
                }
                if (btn_hit) {
                    /* Button handled; don't dismiss */
                } else if (input_active) {
                    /* Clicking while input is active: ignore (keep focus) */
                } else {
                    /* Left click: dismiss overlay */
                    text_buf[0] = '\0';
                    text_len = 0;
                    fade_anim.current = 1.0;
                    fade_anim.active = false;
                    done_at = 0;
                    scroll_anim.current = 0.0;
                    scroll_anim.active = false;
                    user_scrolling = false;
                    show_buttons = false;
                    input_active = false;
                    if (timer_armed) {
                        arm_timer(timer_fd, false);
                        timer_armed = false;
                    }
                    wayland_destroy_surface(&state);
                }
            } else if (btn == BTN_RIGHT) {
                /* Right click: cancel query (stops stream + TTS + overlay) */
                send_daemon_action("{\"action\":\"cancel\"}\n");
                text_buf[0] = '\0';
                text_len = 0;
                fade_anim.current = 1.0;
                fade_anim.active = false;
                done_at = 0;
                scroll_anim.current = 0.0;
                scroll_anim.active = false;
                user_scrolling = false;
                show_buttons = false;
                input_active = false;
                input_len = 0;
                input_buf[0] = '\0';
                if (timer_armed) {
                    arm_timer(timer_fd, false);
                    timer_armed = false;
                }
                wayland_destroy_surface(&state);
            } else if (btn == BTN_MIDDLE) {
                /* Middle click: stop TTS only, text keeps streaming */
                send_daemon_action("{\"action\":\"stop_tts\"}\n");
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

            if (scroll_active || fade_active) {
                state.needs_redraw = true;
            } else {
                /* Both animations done -- disarm timer */
                arm_timer(timer_fd, false);
                timer_armed = false;

                /* If fade completed (opacity ~0), destroy surface */
                if (fade_anim.current <= 0.01 && state.surface_visible) {
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
            strncpy(current_conv_id, cmd.conv_id,
                    sizeof(current_conv_id) - 1);
            current_conv_id[sizeof(current_conv_id) - 1] = '\0';
            text_buf[0] = '\0';
            text_len = 0;
            /* Cancel fade/linger, reset opacity */
            fade_anim.current = 1.0;
            fade_anim.active = false;
            done_at = 0;
            /* Reset scroll */
            scroll_anim.current = 0.0;
            scroll_anim.active = false;
            user_scrolling = false;
            /* Reset buttons/input */
            show_buttons = false;
            input_active = false;
            input_len = 0;
            input_buf[0] = '\0';
            if (!state.surface_visible) {
                uint32_t h = cfg.padding_y * 2 + (uint32_t)rend.line_height;
                if (!wayland_create_surface(&state, cfg.width, h, cfg.margin_top)) {
                    fprintf(stderr, "Failed to create surface on CMD_OPEN\n");
                    break;
                }
            }
            state.needs_redraw = true;
            break;

        case CMD_TEXT:
            /* Streaming text: clear buttons/input */
            show_buttons = false;
            input_active = false;
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
                if (!wayland_create_surface(&state, cfg.width, h, cfg.margin_top)) {
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
                    wl_surface_commit(state.surface);
                    state.height = target_h;
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

        case CMD_DONE:
            /* Show action buttons */
            show_buttons = true;
            /* Resize surface to include button row */
            {
                int content_h = renderer_measure(&rend, &cfg, text_buf);
                uint32_t extra_h = button_row_height;
                uint32_t max_h = cfg.padding_y * 2
                    + (uint32_t)rend.line_height * cfg.max_lines + extra_h;
                uint32_t target_h = (uint32_t)content_h + cfg.padding_y * 2 + extra_h;
                if (target_h > max_h)
                    target_h = max_h;
                uint32_t min_h = cfg.padding_y * 2 + (uint32_t)rend.line_height + extra_h;
                if (target_h < min_h)
                    target_h = min_h;
                if (target_h != state.height && state.layer_surface) {
                    zwlr_layer_surface_v1_set_size(state.layer_surface,
                                                   cfg.width, target_h);
                    wl_surface_commit(state.surface);
                    state.height = target_h;
                }
            }
            state.needs_redraw = true;
            /* Start linger period -- fade begins after delay */
            done_at = anim_now_ms();
            break;

        case CMD_CLEAR:
            text_buf[0] = '\0';
            text_len = 0;
            fade_anim.current = 1.0;
            fade_anim.active = false;
            done_at = 0;
            scroll_anim.current = 0.0;
            scroll_anim.active = false;
            user_scrolling = false;
            show_buttons = false;
            input_active = false;
            input_len = 0;
            input_buf[0] = '\0';
            if (timer_armed) {
                arm_timer(timer_fd, false);
                timer_armed = false;
            }
            if (state.surface_visible)
                wayland_destroy_surface(&state);
            break;

        case CMD_REPLACE:
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
                if (!wayland_create_surface(&state, cfg.width, h, cfg.margin_top)) {
                    fprintf(stderr, "Failed to create surface on CMD_REPLACE\n");
                    break;
                }
            }
            /* Resize surface for new content */
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
                    wl_surface_commit(state.surface);
                    state.height = target_h;
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
