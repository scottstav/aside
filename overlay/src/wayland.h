#ifndef WAYLAND_H
#define WAYLAND_H

#include <stdbool.h>
#include <stdint.h>
#include <wayland-client.h>
#include "wlr-layer-shell-unstable-v1-protocol.h"

/* Forward declarations for keyboard callback */
struct xkb_context;
struct xkb_keymap;
struct xkb_state;

/* Keyboard event callback: called on key press with keysym and UTF-8 text.
 * utf8 may be empty for non-printable keys. n is the byte length of utf8. */
typedef void (*keyboard_key_cb)(void *user_data, uint32_t keysym,
                                const char *utf8, int n);

struct overlay_state {
    /* Wayland globals */
    struct wl_display *display;
    struct wl_registry *registry;
    struct wl_compositor *compositor;
    struct wl_shm *shm;
    struct zwlr_layer_shell_v1 *layer_shell;
    struct wl_output *output;
    struct wl_seat *seat;
    struct wl_pointer *pointer;
    struct wl_keyboard *keyboard;

    /* Surface */
    struct wl_surface *surface;
    struct zwlr_layer_surface_v1 *layer_surface;
    struct wl_buffer *buffer;

    /* Pixel buffer */
    uint32_t *pixels;
    int shm_fd;
    size_t shm_size;

    /* Dimensions */
    uint32_t width;
    uint32_t height;
    uint32_t configured_width;
    uint32_t configured_height;

    /* Scale (detected from wl_output) */
    int32_t scale;

    /* Pointer / scroll input */
    double pending_scroll_delta;
    uint32_t pending_button;   /* button code from last press, 0 = none */
    double pointer_x, pointer_y;  /* current pointer position */
    bool pointer_over;
    bool input_enabled;

    /* Keyboard / xkb state */
    struct xkb_context *xkb_ctx;
    struct xkb_keymap  *xkb_keymap;
    struct xkb_state   *xkb_state;
    keyboard_key_cb     key_cb;
    void               *key_cb_data;

    /* State flags */
    bool surface_visible;
    bool configured;
    bool closed;
    bool needs_redraw;
};

bool wayland_init(struct overlay_state *state);
bool wayland_create_surface(struct overlay_state *state, uint32_t width, uint32_t height, uint32_t margin_top);
void wayland_destroy_surface(struct overlay_state *state);
bool wayland_alloc_buffer(struct overlay_state *state);
void wayland_commit(struct overlay_state *state);
void wayland_cleanup(struct overlay_state *state);
int wayland_get_fd(struct overlay_state *state);
bool wayland_dispatch(struct overlay_state *state);
void wayland_set_input_enabled(struct overlay_state *state, bool enabled);

#endif
