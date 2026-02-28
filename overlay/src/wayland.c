#include "wayland.h"
#include "shm.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>

/* --- wl_output listener (for scale detection) --- */

static void output_geometry(void *data, struct wl_output *output,
                            int32_t x, int32_t y, int32_t pw, int32_t ph,
                            int32_t subpixel, const char *make,
                            const char *model, int32_t transform)
{
    (void)data; (void)output; (void)x; (void)y; (void)pw; (void)ph;
    (void)subpixel; (void)make; (void)model; (void)transform;
}

static void output_mode(void *data, struct wl_output *output,
                        uint32_t flags, int32_t w, int32_t h, int32_t refresh)
{
    (void)data; (void)output; (void)flags; (void)w; (void)h; (void)refresh;
}

static void output_scale(void *data, struct wl_output *output, int32_t factor)
{
    (void)output;
    struct overlay_state *state = data;
    if (factor > state->scale)
        state->scale = factor;
}

static void output_done(void *data, struct wl_output *output)
{
    (void)data; (void)output;
}

static const struct wl_output_listener output_listener = {
    .geometry = output_geometry,
    .mode = output_mode,
    .done = output_done,
    .scale = output_scale,
};

/* --- wl_pointer listener (for scroll input) --- */

static void pointer_enter(void *data, struct wl_pointer *pointer,
                           uint32_t serial, struct wl_surface *surface,
                           wl_fixed_t sx, wl_fixed_t sy)
{
    (void)pointer; (void)serial; (void)surface; (void)sx; (void)sy;
    struct overlay_state *state = data;
    state->pointer_over = true;
}

static void pointer_leave(void *data, struct wl_pointer *pointer,
                           uint32_t serial, struct wl_surface *surface)
{
    (void)pointer; (void)serial; (void)surface;
    struct overlay_state *state = data;
    state->pointer_over = false;
}

static void pointer_motion(void *data, struct wl_pointer *p,
                            uint32_t time, wl_fixed_t sx, wl_fixed_t sy)
{
    (void)p; (void)time;
    struct overlay_state *state = data;
    state->pointer_x = wl_fixed_to_double(sx);
    state->pointer_y = wl_fixed_to_double(sy);
}

static void pointer_button(void *data, struct wl_pointer *p,
                            uint32_t serial, uint32_t time,
                            uint32_t button, uint32_t st)
{
    (void)p; (void)serial; (void)time;
    struct overlay_state *state = data;
    /* Record button on press (state==1), ignore release */
    if (st == WL_POINTER_BUTTON_STATE_PRESSED)
        state->pending_button = button;
}

static void pointer_axis(void *data, struct wl_pointer *pointer,
                          uint32_t time, uint32_t axis, wl_fixed_t value)
{
    (void)pointer; (void)time;
    if (axis != WL_POINTER_AXIS_VERTICAL_SCROLL) return;
    struct overlay_state *state = data;
    state->pending_scroll_delta += wl_fixed_to_double(value);
}

static void pointer_frame(void *data, struct wl_pointer *p)
{ (void)data; (void)p; }
static void pointer_axis_source(void *data, struct wl_pointer *p, uint32_t s)
{ (void)data; (void)p; (void)s; }
static void pointer_axis_stop(void *data, struct wl_pointer *p,
                               uint32_t time, uint32_t axis)
{ (void)data; (void)p; (void)time; (void)axis; }
static void pointer_axis_discrete(void *data, struct wl_pointer *p,
                                   uint32_t axis, int32_t discrete)
{ (void)data; (void)p; (void)axis; (void)discrete; }
static void pointer_axis_value120(void *data, struct wl_pointer *p,
                                   uint32_t axis, int32_t value120)
{ (void)data; (void)p; (void)axis; (void)value120; }
static void pointer_axis_relative_direction(void *data, struct wl_pointer *p,
                                             uint32_t axis, uint32_t dir)
{ (void)data; (void)p; (void)axis; (void)dir; }

static const struct wl_pointer_listener pointer_listener = {
    .enter = pointer_enter,
    .leave = pointer_leave,
    .motion = pointer_motion,
    .button = pointer_button,
    .axis = pointer_axis,
    .frame = pointer_frame,
    .axis_source = pointer_axis_source,
    .axis_stop = pointer_axis_stop,
    .axis_discrete = pointer_axis_discrete,
    .axis_value120 = pointer_axis_value120,
    .axis_relative_direction = pointer_axis_relative_direction,
};

/* --- wl_seat listener --- */

static void seat_capabilities(void *data, struct wl_seat *seat, uint32_t caps)
{
    struct overlay_state *state = data;
    if ((caps & WL_SEAT_CAPABILITY_POINTER) && !state->pointer) {
        state->pointer = wl_seat_get_pointer(seat);
        wl_pointer_add_listener(state->pointer, &pointer_listener, state);
    }
}

static void seat_name(void *data, struct wl_seat *seat, const char *name)
{ (void)data; (void)seat; (void)name; }

static const struct wl_seat_listener seat_listener = {
    .capabilities = seat_capabilities,
    .name = seat_name,
};

/* --- Registry listener --- */

static void registry_handle_global(void *data, struct wl_registry *registry,
                                   uint32_t name, const char *interface,
                                   uint32_t version)
{
    struct overlay_state *state = data;

    if (strcmp(interface, wl_compositor_interface.name) == 0)
        state->compositor = wl_registry_bind(registry, name,
                                             &wl_compositor_interface, 4);
    else if (strcmp(interface, wl_shm_interface.name) == 0)
        state->shm = wl_registry_bind(registry, name,
                                      &wl_shm_interface, 1);
    else if (strcmp(interface, zwlr_layer_shell_v1_interface.name) == 0)
        state->layer_shell = wl_registry_bind(registry, name,
                                              &zwlr_layer_shell_v1_interface, 1);
    else if (strcmp(interface, wl_seat_interface.name) == 0) {
        uint32_t bind_ver = version >= 5 ? 5 : version;
        state->seat = wl_registry_bind(registry, name,
                                       &wl_seat_interface, bind_ver);
        wl_seat_add_listener(state->seat, &seat_listener, state);
    }
    else if (strcmp(interface, wl_output_interface.name) == 0) {
        /* Bind version 2+ to get the scale event */
        uint32_t bind_ver = version >= 2 ? 2 : version;
        struct wl_output *output = wl_registry_bind(registry, name,
                                                    &wl_output_interface, bind_ver);
        wl_output_add_listener(output, &output_listener, state);
        /* Keep first output reference for potential future use */
        if (!state->output)
            state->output = output;
    }
}

static void registry_handle_global_remove(void *data,
                                          struct wl_registry *registry,
                                          uint32_t name)
{
    (void)data;
    (void)registry;
    (void)name;
}

static const struct wl_registry_listener registry_listener = {
    .global = registry_handle_global,
    .global_remove = registry_handle_global_remove,
};

/* --- Layer surface listener --- */

static void layer_surface_configure(void *data,
                                    struct zwlr_layer_surface_v1 *surface,
                                    uint32_t serial,
                                    uint32_t width, uint32_t height)
{
    struct overlay_state *state = data;
    state->configured_width = width ? width : state->width;
    state->configured_height = height ? height : state->height;
    state->configured = true;
    state->needs_redraw = true;
    zwlr_layer_surface_v1_ack_configure(surface, serial);
}

static void layer_surface_closed(void *data,
                                 struct zwlr_layer_surface_v1 *surface)
{
    (void)surface;
    struct overlay_state *state = data;
    state->closed = true;
}

static const struct zwlr_layer_surface_v1_listener layer_surface_listener = {
    .configure = layer_surface_configure,
    .closed = layer_surface_closed,
};

/* --- Public API --- */

bool wayland_init(struct overlay_state *state)
{
    state->scale = 1;  /* default until output reports otherwise */

    state->display = wl_display_connect(NULL);
    if (!state->display) {
        fprintf(stderr, "wayland_init: failed to connect to display\n");
        return false;
    }

    state->registry = wl_display_get_registry(state->display);
    wl_registry_add_listener(state->registry, &registry_listener, state);

    /* First roundtrip discovers globals (including wl_output) */
    wl_display_roundtrip(state->display);
    /* Second roundtrip delivers output events (mode, scale, done) */
    wl_display_roundtrip(state->display);

    if (!state->compositor) {
        fprintf(stderr, "wayland_init: compositor not found\n");
        return false;
    }
    if (!state->shm) {
        fprintf(stderr, "wayland_init: wl_shm not found\n");
        return false;
    }
    if (!state->layer_shell) {
        fprintf(stderr, "wayland_init: zwlr_layer_shell_v1 not found\n");
        return false;
    }

    fprintf(stderr, "aside-overlay: detected output scale %d\n", state->scale);
    return true;
}

bool wayland_create_surface(struct overlay_state *state,
                            uint32_t width, uint32_t height,
                            uint32_t margin_top)
{
    state->width = width;
    state->height = height;

    state->surface = wl_compositor_create_surface(state->compositor);
    if (!state->surface) {
        fprintf(stderr, "wayland_create_surface: failed to create surface\n");
        return false;
    }

    /* Set buffer scale for HiDPI */
    if (state->scale > 1)
        wl_surface_set_buffer_scale(state->surface, state->scale);

    state->layer_surface = zwlr_layer_shell_v1_get_layer_surface(
        state->layer_shell, state->surface, NULL,
        ZWLR_LAYER_SHELL_V1_LAYER_OVERLAY, "aside-overlay");

    if (!state->layer_surface) {
        fprintf(stderr, "wayland_create_surface: failed to create layer surface\n");
        return false;
    }

    /* Anchor top only -- centers horizontally */
    zwlr_layer_surface_v1_set_anchor(state->layer_surface,
        ZWLR_LAYER_SURFACE_V1_ANCHOR_TOP);

    /* 0 exclusive zone = respect others' reserved space, don't reserve our own */
    zwlr_layer_surface_v1_set_exclusive_zone(state->layer_surface, 0);

    zwlr_layer_surface_v1_set_margin(state->layer_surface, margin_top, 0, 0, 0);

    /* Size is in logical pixels */
    zwlr_layer_surface_v1_set_size(state->layer_surface, width, height);
    zwlr_layer_surface_v1_add_listener(state->layer_surface,
                                       &layer_surface_listener, state);

    /* Accept all pointer input (scroll + click) */
    state->input_enabled = true;

    wl_surface_commit(state->surface);
    state->surface_visible = true;
    return true;
}

void wayland_destroy_surface(struct overlay_state *state)
{
    if (state->buffer) {
        wl_buffer_destroy(state->buffer);
        state->buffer = NULL;
    }
    if (state->pixels && state->shm_size > 0) {
        munmap(state->pixels, state->shm_size);
        state->pixels = NULL;
    }
    if (state->shm_fd >= 0) {
        close(state->shm_fd);
        state->shm_fd = -1;
    }
    if (state->layer_surface) {
        zwlr_layer_surface_v1_destroy(state->layer_surface);
        state->layer_surface = NULL;
    }
    if (state->surface) {
        wl_surface_destroy(state->surface);
        state->surface = NULL;
    }
    state->surface_visible = false;
    state->configured = false;
    state->input_enabled = false;
    state->pointer_over = false;
}

bool wayland_alloc_buffer(struct overlay_state *state)
{
    int32_t s = state->scale > 1 ? state->scale : 1;
    uint32_t buf_w = state->configured_width * (uint32_t)s;
    uint32_t buf_h = state->configured_height * (uint32_t)s;
    int stride = (int)buf_w * 4;
    size_t size = (size_t)stride * buf_h;

    /* Reuse existing buffer if size matches */
    if (state->buffer && state->shm_size == size)
        return true;

    /* Free old buffer */
    if (state->buffer) {
        wl_buffer_destroy(state->buffer);
        state->buffer = NULL;
    }
    if (state->pixels && state->shm_size > 0) {
        munmap(state->pixels, state->shm_size);
        state->pixels = NULL;
    }
    if (state->shm_fd >= 0) {
        close(state->shm_fd);
        state->shm_fd = -1;
    }

    state->pixels = shm_alloc(size, &state->shm_fd);
    if (!state->pixels) {
        fprintf(stderr, "wayland_alloc_buffer: shm_alloc failed\n");
        return false;
    }
    state->shm_size = size;

    struct wl_shm_pool *pool = wl_shm_create_pool(state->shm, state->shm_fd,
                                                   (int32_t)size);
    state->buffer = wl_shm_pool_create_buffer(pool, 0,
        (int32_t)buf_w, (int32_t)buf_h,
        stride, WL_SHM_FORMAT_ARGB8888);
    wl_shm_pool_destroy(pool);

    return true;
}

void wayland_commit(struct overlay_state *state)
{
    int32_t s = state->scale > 1 ? state->scale : 1;
    wl_surface_attach(state->surface, state->buffer, 0, 0);
    wl_surface_damage_buffer(state->surface, 0, 0,
                             (int32_t)(state->configured_width * (uint32_t)s),
                             (int32_t)(state->configured_height * (uint32_t)s));
    wl_surface_commit(state->surface);
}

void wayland_set_input_enabled(struct overlay_state *state, bool enabled)
{
    if (!state->surface || !state->compositor)
        return;
    if (enabled == state->input_enabled)
        return;

    if (enabled) {
        /* NULL input region = entire surface accepts input */
        wl_surface_set_input_region(state->surface, NULL);
    } else {
        /* Empty region = passthrough */
        struct wl_region *empty = wl_compositor_create_region(state->compositor);
        wl_surface_set_input_region(state->surface, empty);
        wl_region_destroy(empty);
    }
    wl_surface_commit(state->surface);
    state->input_enabled = enabled;
}

void wayland_cleanup(struct overlay_state *state)
{
    wayland_destroy_surface(state);

    if (state->pointer) {
        wl_pointer_destroy(state->pointer);
        state->pointer = NULL;
    }
    if (state->seat) {
        wl_seat_destroy(state->seat);
        state->seat = NULL;
    }
    if (state->output) {
        wl_output_destroy(state->output);
        state->output = NULL;
    }
    if (state->layer_shell) {
        zwlr_layer_shell_v1_destroy(state->layer_shell);
        state->layer_shell = NULL;
    }
    if (state->compositor) {
        wl_compositor_destroy(state->compositor);
        state->compositor = NULL;
    }
    if (state->shm) {
        wl_shm_destroy(state->shm);
        state->shm = NULL;
    }
    if (state->registry) {
        wl_registry_destroy(state->registry);
        state->registry = NULL;
    }
    if (state->display) {
        wl_display_disconnect(state->display);
        state->display = NULL;
    }
}

int wayland_get_fd(struct overlay_state *state)
{
    return wl_display_get_fd(state->display);
}

bool wayland_dispatch(struct overlay_state *state)
{
    if (wl_display_dispatch(state->display) < 0)
        return false;
    return !state->closed;
}
