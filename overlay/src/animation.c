#include "animation.h"
#include <time.h>

uint64_t anim_now_ms(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint64_t)ts.tv_sec * 1000 + (uint64_t)ts.tv_nsec / 1000000;
}

void anim_set_target(struct animation *a, double target, double duration_ms)
{
    a->start_value = a->current;
    a->target = target;
    a->duration_ms = duration_ms;
    a->start_time = anim_now_ms();
    a->active = true;
}

bool anim_update(struct animation *a, uint64_t now_ms)
{
    if (!a->active) return false;

    double elapsed = (double)(now_ms - a->start_time);
    double t = elapsed / a->duration_ms;
    if (t >= 1.0) {
        a->current = a->target;
        a->active = false;
        return false;
    }

    // Ease-out cubic: 1 - (1-t)^3
    double ease = 1.0 - (1.0 - t) * (1.0 - t) * (1.0 - t);
    a->current = a->start_value + (a->target - a->start_value) * ease;
    return true;
}
