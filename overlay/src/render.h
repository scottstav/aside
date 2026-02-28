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

/* Rectangle for button hit-testing */
struct button_rect { double x, y, w, h; };

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
// draw_buttons: if true, draw action buttons and populate btn_rects.
// btn_count: number of buttons (BTN_ACTION_COUNT).
// draw_input: if true, draw text input box instead of buttons.
// input_text: text currently in the input box (only used if draw_input).
void renderer_draw(struct renderer *r, const struct overlay_config *cfg,
                   uint32_t *pixels, uint32_t buf_width, uint32_t buf_height,
                   const char *text, double scroll_y, double opacity,
                   bool draw_buttons, struct button_rect *btn_rects,
                   int btn_count,
                   bool draw_input, const char *input_text);

void renderer_cleanup(struct renderer *r);

#endif
