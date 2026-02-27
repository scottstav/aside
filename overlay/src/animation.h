#ifndef ANIMATION_H
#define ANIMATION_H

#include <stdbool.h>
#include <stdint.h>

struct animation {
    double current;
    double target;
    double duration_ms;
    double start_value;
    uint64_t start_time;
    bool active;
};

// Set a new target. Starts animating from current value.
void anim_set_target(struct animation *a, double target, double duration_ms);

// Update current value based on elapsed time. Uses ease-out cubic.
// Returns true if animation is still in progress.
bool anim_update(struct animation *a, uint64_t now_ms);

// Get current monotonic time in milliseconds.
uint64_t anim_now_ms(void);

#endif
