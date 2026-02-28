#define _GNU_SOURCE
#include <math.h>
#include <string.h>
#include <cairo/cairo.h>
#include <pango/pangocairo.h>
#include "render.h"

void renderer_init(struct renderer *r, const struct overlay_config *cfg)
{
    r->font_desc = pango_font_description_from_string(cfg->font);

    /* Create a tiny dummy surface just to measure font metrics */
    cairo_surface_t *tmp_surf = cairo_image_surface_create(CAIRO_FORMAT_ARGB32, 1, 1);
    cairo_t *tmp_cr = cairo_create(tmp_surf);
    PangoLayout *tmp_layout = pango_cairo_create_layout(tmp_cr);
    pango_layout_set_font_description(tmp_layout, r->font_desc);

    PangoContext *ctx = pango_layout_get_context(tmp_layout);
    PangoFontMetrics *metrics = pango_context_get_metrics(ctx, r->font_desc, NULL);

    int ascent = pango_font_metrics_get_ascent(metrics);
    int descent = pango_font_metrics_get_descent(metrics);
    r->line_height = (ascent + descent) / PANGO_SCALE;

    pango_font_metrics_unref(metrics);
    g_object_unref(tmp_layout);
    cairo_destroy(tmp_cr);
    cairo_surface_destroy(tmp_surf);
}

static void setup_layout(PangoLayout *layout, struct renderer *r,
                         const struct overlay_config *cfg, uint32_t width)
{
    pango_layout_set_font_description(layout, r->font_desc);
    pango_layout_set_width(layout, (int)(width - 2 * cfg->padding_x) * PANGO_SCALE);
    pango_layout_set_wrap(layout, PANGO_WRAP_WORD_CHAR);
    if (cfg->line_spacing > 0)
        pango_layout_set_spacing(layout, (int)cfg->line_spacing * PANGO_SCALE);
}

int renderer_measure(struct renderer *r, const struct overlay_config *cfg,
                     const char *text)
{
    cairo_surface_t *tmp_surf = cairo_image_surface_create(CAIRO_FORMAT_ARGB32, 1, 1);
    cairo_t *tmp_cr = cairo_create(tmp_surf);
    PangoLayout *layout = pango_cairo_create_layout(tmp_cr);

    setup_layout(layout, r, cfg, cfg->width);
    pango_layout_set_text(layout, text, -1);

    int text_w, text_h;
    pango_layout_get_pixel_size(layout, &text_w, &text_h);

    g_object_unref(layout);
    cairo_destroy(tmp_cr);
    cairo_surface_destroy(tmp_surf);

    return text_h;
}

static void rounded_rect(cairo_t *cr, double x, double y,
                         double w, double h, double r)
{
    cairo_new_sub_path(cr);
    cairo_arc(cr, x + w - r, y + r,     r, -M_PI / 2, 0);
    cairo_arc(cr, x + w - r, y + h - r, r, 0,          M_PI / 2);
    cairo_arc(cr, x + r,     y + h - r, r, M_PI / 2,   M_PI);
    cairo_arc(cr, x + r,     y + r,     r, M_PI,        3 * M_PI / 2);
    cairo_close_path(cr);
}

/* Extract RGBA channels from 0xRRGGBBAA color */
static void color_rgba(uint32_t c, double *r, double *g, double *b, double *a)
{
    *r = ((c >> 24) & 0xFF) / 255.0;
    *g = ((c >> 16) & 0xFF) / 255.0;
    *b = ((c >> 8)  & 0xFF) / 255.0;
    *a = (c & 0xFF) / 255.0;
}

/* Draw action buttons at the bottom of the overlay */
static void draw_buttons(struct renderer *r, const struct overlay_config *cfg,
                         cairo_t *cr, double logical_w, double logical_h,
                         struct button_rect *rects, int count)
{
    if (count <= 0) return;

    double ac_r, ac_g, ac_b, ac_a;
    color_rgba(cfg->accent_color, &ac_r, &ac_g, &ac_b, &ac_a);

    double bg_r, bg_g, bg_b, bg_a;
    color_rgba(cfg->background, &bg_r, &bg_g, &bg_b, &bg_a);

    double btn_h = r->line_height + 4;
    double row_y = logical_h - cfg->padding_y - btn_h;
    double total_w = logical_w - 2 * cfg->padding_x;
    double gap = 8.0;
    double btn_w = (total_w - gap * (count - 1)) / count;

    const char *labels[] = { "mic", "open", "reply" };

    for (int i = 0; i < count; i++) {
        double bx = cfg->padding_x + i * (btn_w + gap);
        double by = row_y;

        /* Store rect for hit-testing (logical coords) */
        if (rects) {
            rects[i].x = bx;
            rects[i].y = by;
            rects[i].w = btn_w;
            rects[i].h = btn_h;
        }

        /* Button fill: lighter version of background */
        rounded_rect(cr, bx, by, btn_w, btn_h, 4.0);
        cairo_set_source_rgba(cr,
            fmin(bg_r + 0.08, 1.0), fmin(bg_g + 0.08, 1.0),
            fmin(bg_b + 0.08, 1.0), bg_a);
        cairo_fill(cr);

        /* Button border: subtle */
        rounded_rect(cr, bx, by, btn_w, btn_h, 4.0);
        cairo_set_source_rgba(cr, ac_r, ac_g, ac_b, 0.3);
        cairo_set_line_width(cr, 1.0);
        cairo_stroke(cr);

        /* Button label */
        const char *label = (i < 3) ? labels[i] : "?";
        PangoLayout *layout = pango_cairo_create_layout(cr);
        pango_layout_set_font_description(layout, r->font_desc);
        pango_layout_set_text(layout, label, -1);

        int tw, th;
        pango_layout_get_pixel_size(layout, &tw, &th);
        double tx = bx + (btn_w - tw) / 2.0;
        double ty = by + (btn_h - th) / 2.0;

        cairo_move_to(cr, tx, ty);
        cairo_set_source_rgba(cr, ac_r, ac_g, ac_b, ac_a);
        pango_cairo_show_layout(cr, layout);
        g_object_unref(layout);
    }
}

/* Draw text input box at the bottom of the overlay */
static void draw_input_box(struct renderer *r, const struct overlay_config *cfg,
                           cairo_t *cr, double logical_w, double logical_h,
                           const char *input_text)
{
    double ac_r, ac_g, ac_b, ac_a;
    color_rgba(cfg->accent_color, &ac_r, &ac_g, &ac_b, &ac_a);

    double bg_r, bg_g, bg_b, bg_a;
    color_rgba(cfg->background, &bg_r, &bg_g, &bg_b, &bg_a);

    double tc_r, tc_g, tc_b, tc_a;
    color_rgba(cfg->text_color, &tc_r, &tc_g, &tc_b, &tc_a);

    double box_h = r->line_height + 8;
    double box_y = logical_h - cfg->padding_y - box_h;
    double box_x = cfg->padding_x;
    double box_w = logical_w - 2 * cfg->padding_x;

    /* Input box background: slightly different from overlay bg */
    rounded_rect(cr, box_x, box_y, box_w, box_h, 4.0);
    cairo_set_source_rgba(cr,
        fmin(bg_r + 0.05, 1.0), fmin(bg_g + 0.05, 1.0),
        fmin(bg_b + 0.05, 1.0), bg_a);
    cairo_fill(cr);

    /* Input box border: accent color */
    rounded_rect(cr, box_x, box_y, box_w, box_h, 4.0);
    cairo_set_source_rgba(cr, ac_r, ac_g, ac_b, 0.5);
    cairo_set_line_width(cr, 1.0);
    cairo_stroke(cr);

    /* Text or placeholder */
    PangoLayout *layout = pango_cairo_create_layout(cr);
    pango_layout_set_font_description(layout, r->font_desc);

    double text_x = box_x + 8.0;
    double text_max_w = box_w - 16.0;
    pango_layout_set_width(layout, (int)(text_max_w) * PANGO_SCALE);
    pango_layout_set_ellipsize(layout, PANGO_ELLIPSIZE_NONE);

    bool has_text = input_text && input_text[0] != '\0';

    if (has_text) {
        /* Build display string with cursor */
        size_t len = strlen(input_text);
        char *display = malloc(len + 2);
        if (display) {
            memcpy(display, input_text, len);
            display[len] = '|';
            display[len + 1] = '\0';
            pango_layout_set_text(layout, display, -1);
            free(display);
        } else {
            pango_layout_set_text(layout, input_text, -1);
        }
        cairo_set_source_rgba(cr, tc_r, tc_g, tc_b, tc_a);
    } else {
        pango_layout_set_text(layout, "Type a reply...", -1);
        cairo_set_source_rgba(cr, tc_r, tc_g, tc_b, 0.4);
    }

    int tw, th;
    pango_layout_get_pixel_size(layout, &tw, &th);
    double text_y = box_y + (box_h - th) / 2.0;

    cairo_move_to(cr, text_x, text_y);
    pango_cairo_show_layout(cr, layout);
    g_object_unref(layout);
}

void renderer_draw(struct renderer *r, const struct overlay_config *cfg,
                   uint32_t *pixels, uint32_t buf_width, uint32_t buf_height,
                   const char *text, double scroll_y, double opacity,
                   bool draw_buttons_flag, struct button_rect *btn_rects,
                   int btn_count,
                   bool draw_input, const char *input_text)
{
    cairo_surface_t *surface = cairo_image_surface_create_for_data(
        (unsigned char *)pixels, CAIRO_FORMAT_ARGB32,
        (int)buf_width, (int)buf_height, (int)(buf_width * 4));
    cairo_t *cr = cairo_create(surface);

    /* Clear to transparent */
    cairo_set_operator(cr, CAIRO_OPERATOR_CLEAR);
    cairo_paint(cr);
    cairo_set_operator(cr, CAIRO_OPERATOR_OVER);

    /* Derive scale from buffer vs logical width for HiDPI */
    double scale = (double)buf_width / (double)cfg->width;
    if (scale < 1.0) scale = 1.0;
    cairo_scale(cr, scale, scale);
    double logical_w = buf_width / scale;
    double logical_h = buf_height / scale;

    /* Push a group so we can apply global opacity at the end */
    cairo_push_group(cr);

    double bw = cfg->border_width;
    double inset = bw / 2.0;
    double rx = inset, ry = inset;
    double rw = logical_w - 2 * inset;
    double rh = logical_h - 2 * inset;
    double cr_radius = cfg->corner_radius;

    /* --- Background with subtle vertical gradient --- */
    rounded_rect(cr, rx, ry, rw, rh, cr_radius);

    double bg_r, bg_g, bg_b, bg_a;
    color_rgba(cfg->background, &bg_r, &bg_g, &bg_b, &bg_a);

    cairo_pattern_t *bg_grad = cairo_pattern_create_linear(0, 0, 0, logical_h);
    /* Slightly lighter at top, base color at bottom */
    cairo_pattern_add_color_stop_rgba(bg_grad, 0.0,
        fmin(bg_r + 0.03, 1.0), fmin(bg_g + 0.03, 1.0), fmin(bg_b + 0.03, 1.0), bg_a);
    cairo_pattern_add_color_stop_rgba(bg_grad, 1.0, bg_r, bg_g, bg_b, bg_a);
    cairo_set_source(cr, bg_grad);
    cairo_fill_preserve(cr);
    cairo_pattern_destroy(bg_grad);

    /* --- Border --- */
    if (cfg->border_width > 0) {
        double br, bg, bb, ba;
        color_rgba(cfg->border_color, &br, &bg, &bb, &ba);
        cairo_set_source_rgba(cr, br, bg, bb, ba);
        cairo_set_line_width(cr, bw);
        cairo_stroke(cr);
    } else {
        cairo_new_path(cr);
    }

    /* --- Top accent line: stroke along the top edge of the rounded rect --- */
    if (cfg->accent_height > 0) {
        cairo_save(cr);
        double ah = cfg->accent_height;

        /* Clip to the rounded rect so accent stays inside */
        rounded_rect(cr, rx, ry, rw, rh, cr_radius);
        cairo_clip(cr);

        double ac_r, ac_g, ac_b, ac_a;
        color_rgba(cfg->accent_color, &ac_r, &ac_g, &ac_b, &ac_a);

        /* Draw the top edge path of the rounded rect as a thick stroke */
        cairo_new_sub_path(cr);
        cairo_arc(cr, rx + cr_radius, ry + cr_radius, cr_radius, M_PI, 3 * M_PI / 2);
        cairo_arc(cr, rx + rw - cr_radius, ry + cr_radius, cr_radius, -M_PI / 2, 0);

        /* Gradient source: fade in from left edge, solid middle, fade out right */
        cairo_pattern_t *accent_grad = cairo_pattern_create_linear(rx, 0, rx + rw, 0);
        cairo_pattern_add_color_stop_rgba(accent_grad, 0.0,  ac_r, ac_g, ac_b, 0.0);
        cairo_pattern_add_color_stop_rgba(accent_grad, 0.12, ac_r, ac_g, ac_b, ac_a);
        cairo_pattern_add_color_stop_rgba(accent_grad, 0.88, ac_r, ac_g, ac_b, ac_a);
        cairo_pattern_add_color_stop_rgba(accent_grad, 1.0,  ac_r, ac_g, ac_b, 0.0);
        cairo_set_source(cr, accent_grad);
        cairo_set_line_width(cr, ah * 2);  /* doubled because half is outside clip */
        cairo_set_line_cap(cr, CAIRO_LINE_CAP_BUTT);
        cairo_stroke(cr);
        cairo_pattern_destroy(accent_grad);

        /* Subtle glow/bloom below the accent */
        cairo_pattern_t *glow = cairo_pattern_create_linear(0, ry, 0, ry + 40);
        cairo_pattern_add_color_stop_rgba(glow, 0.0, ac_r, ac_g, ac_b, 0.06);
        cairo_pattern_add_color_stop_rgba(glow, 1.0, ac_r, ac_g, ac_b, 0.0);
        cairo_set_source(cr, glow);
        cairo_rectangle(cr, rx, ry, rw, 40);
        cairo_fill(cr);
        cairo_pattern_destroy(glow);

        cairo_restore(cr);
    }

    /* --- Inner highlight along top edge (glass effect) --- */
    {
        cairo_save(cr);
        rounded_rect(cr, rx, ry, rw, rh, cr_radius);
        cairo_clip(cr);

        /* Thin white highlight just below the top border */
        cairo_new_sub_path(cr);
        double hi_inset = bw + 0.5;
        double hi_r = cr_radius - hi_inset;
        if (hi_r < 1) hi_r = 1;
        cairo_arc(cr, rx + hi_inset + hi_r, ry + hi_inset + hi_r, hi_r,
                  M_PI, 3 * M_PI / 2);
        cairo_arc(cr, rx + rw - hi_inset - hi_r, ry + hi_inset + hi_r, hi_r,
                  -M_PI / 2, 0);

        cairo_pattern_t *hi_grad = cairo_pattern_create_linear(rx, 0, rx + rw, 0);
        cairo_pattern_add_color_stop_rgba(hi_grad, 0.0,  1, 1, 1, 0.0);
        cairo_pattern_add_color_stop_rgba(hi_grad, 0.2,  1, 1, 1, 0.06);
        cairo_pattern_add_color_stop_rgba(hi_grad, 0.8,  1, 1, 1, 0.06);
        cairo_pattern_add_color_stop_rgba(hi_grad, 1.0,  1, 1, 1, 0.0);
        cairo_set_source(cr, hi_grad);
        cairo_set_line_width(cr, 1.0);
        cairo_stroke(cr);
        cairo_pattern_destroy(hi_grad);

        cairo_restore(cr);
    }

    /* --- Text content (rendered into a sub-group for bottom fade) --- */
    {
        cairo_save(cr);
        double px = cfg->padding_x;
        double py = cfg->padding_y;
        double content_w = logical_w - 2 * px;
        /* Reserve space for button/input row if active */
        double bottom_row = (draw_buttons_flag || draw_input)
            ? (double)(r->line_height + 16) : 0.0;
        double content_h = logical_h - 2 * py - bottom_row;

        cairo_rectangle(cr, px, py, content_w, content_h);
        cairo_clip(cr);

        /* Render text into a group so we can mask the bottom */
        cairo_push_group(cr);

        /* Apply scroll offset */
        cairo_translate(cr, px, py - scroll_y);

        /* Create Pango layout for text rendering */
        PangoLayout *layout = pango_cairo_create_layout(cr);
        setup_layout(layout, r, cfg, (uint32_t)logical_w);
        pango_layout_set_text(layout, text, -1);

        /* Set text color and render */
        double tc_r, tc_g, tc_b, tc_a;
        color_rgba(cfg->text_color, &tc_r, &tc_g, &tc_b, &tc_a);
        cairo_set_source_rgba(cr, tc_r, tc_g, tc_b, tc_a);
        pango_cairo_show_layout(cr, layout);

        g_object_unref(layout);

        /* Edge fades: soft fade at top/bottom when content is clipped */
        int content_text_h = renderer_measure(r, cfg, text);
        uint32_t visible_h = (uint32_t)r->line_height * cfg->max_lines;
        double max_scroll = content_text_h > (int)visible_h
            ? (double)(content_text_h - (int)visible_h) : 0.0;

        /* Top fade when scrolled down (content above) */
        if (scroll_y > 1.0) {
            double fade_h = 24.0;
            cairo_set_operator(cr, CAIRO_OPERATOR_DEST_OUT);
            cairo_pattern_t *fade = cairo_pattern_create_linear(
                0, py, 0, py + fade_h);
            cairo_pattern_add_color_stop_rgba(fade, 0.0, 0, 0, 0, 1.0);
            cairo_pattern_add_color_stop_rgba(fade, 1.0, 0, 0, 0, 0.0);
            cairo_set_source(cr, fade);
            cairo_rectangle(cr, px, py, content_w, fade_h);
            cairo_fill(cr);
            cairo_pattern_destroy(fade);
            cairo_set_operator(cr, CAIRO_OPERATOR_OVER);
        }

        /* Bottom fade when more content below */
        if (scroll_y < max_scroll - 1.0) {
            double fade_h = 24.0;
            double fade_top = py + content_h - fade_h;
            cairo_set_operator(cr, CAIRO_OPERATOR_DEST_OUT);
            cairo_pattern_t *fade = cairo_pattern_create_linear(
                0, fade_top, 0, py + content_h);
            cairo_pattern_add_color_stop_rgba(fade, 0.0, 0, 0, 0, 0.0);
            cairo_pattern_add_color_stop_rgba(fade, 1.0, 0, 0, 0, 1.0);
            cairo_set_source(cr, fade);
            cairo_rectangle(cr, px, fade_top, content_w, fade_h);
            cairo_fill(cr);
            cairo_pattern_destroy(fade);
            cairo_set_operator(cr, CAIRO_OPERATOR_OVER);
        }

        cairo_pop_group_to_source(cr);
        cairo_paint(cr);
        cairo_restore(cr);
    }

    /* --- Action buttons or input box --- */
    if (draw_buttons_flag && btn_rects && btn_count > 0) {
        draw_buttons(r, cfg, cr, logical_w, logical_h,
                     btn_rects, btn_count);
    } else if (draw_input) {
        draw_input_box(r, cfg, cr, logical_w, logical_h, input_text);
    }

    /* Pop group and paint with global opacity */
    cairo_pop_group_to_source(cr);
    cairo_paint_with_alpha(cr, opacity);

    cairo_destroy(cr);
    cairo_surface_destroy(surface);
}

void renderer_cleanup(struct renderer *r)
{
    if (r->font_desc) {
        pango_font_description_free(r->font_desc);
        r->font_desc = NULL;
    }
}
