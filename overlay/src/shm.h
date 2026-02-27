#ifndef SHM_H
#define SHM_H

#include <stddef.h>
#include <stdint.h>

/* Create anonymous shm fd, mmap buffer. Returns pointer to pixel data. */
uint32_t *shm_alloc(size_t size, int *out_fd);

#endif
