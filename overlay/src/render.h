#ifndef RENDER_H
#define RENDER_H

#include <stdbool.h>
#include <stdint.h>
#include <pango/pangocairo.h>
#include "config.h"

enum draw_mode {
    DRAW_NORMAL = 0,
    DRAW_LISTENING,
    DRAW_THINKING,
};

#define BUTTON_BAR_HEIGHT 36

struct button_rect {
    double x, y, w, h;
};

struct renderer {
    PangoFontDescription *font_desc;
    int line_height;  // Pixel height of one line of text
    struct button_rect button_rects[3];  // filled by renderer_draw when buttons shown
};

// Initialize Pango font and measure line height.
void renderer_init(struct renderer *r, const struct overlay_config *cfg);

// Compute the pixel height needed to render the given text at the given
// width (accounting for word-wrap, padding). Returns total content height
// (just the text, not including padding).
int renderer_measure(struct renderer *r, const struct overlay_config *cfg,
                     const char *text);

// Render text into an ARGB8888 pixel buffer.
// scroll_y: how many pixels of content to skip from the top (for scrolling).
// opacity: 0.0-1.0 for fade animation.
// accent: accent color override (used instead of cfg->accent_color).
// mode: DRAW_NORMAL, DRAW_LISTENING (waveform), or DRAW_THINKING (pulsing).
// anim_time_ms: monotonic time for animations (only used when mode != DRAW_NORMAL).
// show_buttons: if true, render action buttons at the bottom of the panel.
// hovered_button: index of hovered button (0-2), or -1 for none.
void renderer_draw(struct renderer *r, const struct overlay_config *cfg,
                   uint32_t *pixels, uint32_t buf_width, uint32_t buf_height,
                   const char *text, double scroll_y, double opacity,
                   uint32_t accent, enum draw_mode mode,
                   uint64_t anim_time_ms,
                   bool show_buttons, int hovered_button);

void renderer_cleanup(struct renderer *r);

#endif
