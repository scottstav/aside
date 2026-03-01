#ifndef CONFIG_H
#define CONFIG_H

#include <stdbool.h>
#include <stdint.h>

struct overlay_config {
    char font[256];          // Pango font description string
    uint32_t background;     // RGBA: 0xRRGGBBAA
    uint32_t text_color;     // RGBA: 0xRRGGBBAA
    uint32_t border_color;   // RGBA: 0xRRGGBBAA
    uint32_t accent_color;   // RGBA: 0xRRGGBBAA — top accent line (agent mode)
    uint32_t user_accent_color; // RGBA: 0xRRGGBBAA — accent for user/mic mode
    uint32_t width;
    uint32_t max_lines;
    uint32_t padding_x;
    uint32_t padding_y;
    uint32_t corner_radius;
    uint32_t border_width;
    uint32_t accent_height;  // pixels, 0 = disabled
    uint32_t margin_top;
    uint32_t margin_right;
    uint32_t margin_bottom;
    uint32_t margin_left;
    char position[16];       // "top-center", "top-left", "top-right", etc.
    uint32_t line_spacing;   // extra pixels between lines (Pango spacing)
    uint32_t scroll_duration; // milliseconds
    uint32_t fade_duration;   // milliseconds
    char socket_path[512];    // empty = default
};

void config_defaults(struct overlay_config *cfg);
bool config_load(struct overlay_config *cfg, const char *path);

#endif
