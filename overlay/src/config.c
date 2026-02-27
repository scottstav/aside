#include "config.h"

#include <ctype.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

void config_defaults(struct overlay_config *cfg)
{
    snprintf(cfg->font, sizeof(cfg->font), "Sans 13");
    cfg->background      = 0x1a1a2ee6;
    cfg->text_color      = 0xe0e0e0ff;
    cfg->border_color    = 0x333355ff;
    cfg->accent_color    = 0xD4714Aff;
    cfg->width           = 600;
    cfg->max_lines       = 12;
    cfg->padding_x       = 12;
    cfg->padding_y       = 8;
    cfg->corner_radius   = 8;
    cfg->border_width    = 1;
    cfg->accent_height   = 3;
    cfg->margin_top      = 0;
    cfg->line_spacing    = 0;
    cfg->scroll_duration = 150;
    cfg->fade_duration   = 500;
    cfg->socket_path[0]  = '\0';
}

/* Trim leading and trailing whitespace in-place, return pointer into buf */
static char *trim(char *s)
{
    while (isspace((unsigned char)*s))
        s++;
    if (*s == '\0')
        return s;
    char *end = s + strlen(s) - 1;
    while (end > s && isspace((unsigned char)*end))
        *end-- = '\0';
    return s;
}

/* Parse #RRGGBB or #RRGGBBAA into a uint32_t RGBA value */
static bool parse_color(const char *s, uint32_t *out)
{
    if (*s == '#')
        s++;

    size_t len = strlen(s);
    if (len != 6 && len != 8)
        return false;

    char *end;
    unsigned long val = strtoul(s, &end, 16);
    if (*end != '\0')
        return false;

    if (len == 6)
        *out = (uint32_t)((val << 8) | 0xFF);
    else
        *out = (uint32_t)val;

    return true;
}

static void config_set(struct overlay_config *cfg, const char *key,
                       const char *value)
{
    if (strcmp(key, "font") == 0) {
        snprintf(cfg->font, sizeof(cfg->font), "%s", value);
    } else if (strcmp(key, "background") == 0) {
        parse_color(value, &cfg->background);
    } else if (strcmp(key, "text_color") == 0) {
        parse_color(value, &cfg->text_color);
    } else if (strcmp(key, "border_color") == 0) {
        parse_color(value, &cfg->border_color);
    } else if (strcmp(key, "accent_color") == 0) {
        parse_color(value, &cfg->accent_color);
    } else if (strcmp(key, "width") == 0) {
        cfg->width = (uint32_t)strtoul(value, NULL, 10);
    } else if (strcmp(key, "max_lines") == 0) {
        cfg->max_lines = (uint32_t)strtoul(value, NULL, 10);
    } else if (strcmp(key, "padding_x") == 0) {
        cfg->padding_x = (uint32_t)strtoul(value, NULL, 10);
    } else if (strcmp(key, "padding_y") == 0) {
        cfg->padding_y = (uint32_t)strtoul(value, NULL, 10);
    } else if (strcmp(key, "corner_radius") == 0) {
        cfg->corner_radius = (uint32_t)strtoul(value, NULL, 10);
    } else if (strcmp(key, "border_width") == 0) {
        cfg->border_width = (uint32_t)strtoul(value, NULL, 10);
    } else if (strcmp(key, "accent_height") == 0) {
        cfg->accent_height = (uint32_t)strtoul(value, NULL, 10);
    } else if (strcmp(key, "margin_top") == 0) {
        cfg->margin_top = (uint32_t)strtoul(value, NULL, 10);
    } else if (strcmp(key, "line_spacing") == 0) {
        cfg->line_spacing = (uint32_t)strtoul(value, NULL, 10);
    } else if (strcmp(key, "scroll_duration") == 0) {
        cfg->scroll_duration = (uint32_t)strtoul(value, NULL, 10);
    } else if (strcmp(key, "fade_duration") == 0) {
        cfg->fade_duration = (uint32_t)strtoul(value, NULL, 10);
    } else if (strcmp(key, "socket_path") == 0) {
        snprintf(cfg->socket_path, sizeof(cfg->socket_path), "%s", value);
    }
}

bool config_load(struct overlay_config *cfg, const char *path)
{
    FILE *fp = fopen(path, "r");
    if (!fp) {
        /* Missing file is fine -- just keep defaults */
        if (errno == ENOENT)
            return true;
        fprintf(stderr, "config_load: cannot open %s: %s\n",
                path, strerror(errno));
        return false;
    }

    char line[1024];
    while (fgets(line, sizeof(line), fp)) {
        char *s = trim(line);

        /* Skip empty lines and comments */
        if (*s == '\0' || *s == '#')
            continue;

        /* Split on first '=' */
        char *eq = strchr(s, '=');
        if (!eq)
            continue;

        *eq = '\0';
        char *key = trim(s);
        char *value = trim(eq + 1);

        if (*key == '\0')
            continue;

        config_set(cfg, key, value);
    }

    fclose(fp);
    return true;
}
