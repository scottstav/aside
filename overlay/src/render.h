#ifndef RENDER_H
#define RENDER_H

#include <stdbool.h>
#include <stdint.h>
#include <pango/pangocairo.h>
#include "config.h"

struct renderer {
    PangoFontDescription *font_desc;
    int line_height;  // Pixel height of one line of text
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
void renderer_draw(struct renderer *r, const struct overlay_config *cfg,
                   uint32_t *pixels, uint32_t buf_width, uint32_t buf_height,
                   const char *text, double scroll_y, double opacity,
                   uint32_t accent);

void renderer_cleanup(struct renderer *r);

#endif
